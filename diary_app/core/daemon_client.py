"""Client for the Omniflow localhost daemon (NDJSON TCP)."""
from __future__ import annotations

import json
import os
import secrets
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable

from .daemon import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    PROTOCOL_VERSION,
    diary_root,
    is_process_alive,
    read_state,
    state_path,
)
from .logutil import get_logger

log = get_logger("daemon_client")

ProgressCallback = Callable[[dict[str, Any]], None]


class DaemonError(RuntimeError):
    pass


class DaemonClient:
    def __init__(
        self,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        token: str = "",
        *,
        timeout: float = 600.0,
    ):
        self.host = host
        self.port = int(port)
        self.token = token
        self.timeout = timeout

    @classmethod
    def from_state(cls, state: dict[str, Any] | None = None) -> "DaemonClient":
        st = state if state is not None else read_state()
        if not st:
            raise DaemonError("No daemon state file (is the daemon running?)")
        return cls(
            host=str(st.get("host") or DEFAULT_HOST),
            port=int(st.get("port") or DEFAULT_PORT),
            token=str(st.get("token") or ""),
        )

    def _connect(self, timeout: float | None = None) -> socket.socket:
        sock = socket.create_connection(
            (self.host, self.port),
            timeout=timeout if timeout is not None else min(self.timeout, 30.0),
        )
        sock.settimeout(self.timeout)
        return sock

    def ping(self, timeout: float = 2.0) -> bool:
        try:
            result = self.request("ping", {}, timeout=timeout)
            return bool(result.get("ok") and result.get("pong"))
        except Exception:
            return False

    def request(
        self,
        cmd: str,
        params: dict[str, Any] | None = None,
        *,
        timeout: float | None = None,
        on_progress: ProgressCallback | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Send one command and wait for the final result message.
        Progress messages invoke on_progress when provided.
        """
        rid = request_id or secrets.token_hex(8)
        req = {
            "v": PROTOCOL_VERSION,
            "id": rid,
            "token": self.token,
            "cmd": cmd,
            "params": params or {},
        }
        old_timeout = self.timeout
        if timeout is not None:
            self.timeout = timeout
        try:
            sock = self._connect(timeout=min(self.timeout, 30.0))
        finally:
            if timeout is not None:
                self.timeout = old_timeout

        try:
            sock.settimeout(timeout if timeout is not None else self.timeout)
            line = json.dumps(req, ensure_ascii=False) + "\n"
            sock.sendall(line.encode("utf-8"))
            buf = b""
            while True:
                chunk = sock.recv(65536)
                if not chunk:
                    raise DaemonError("Connection closed before result")
                buf += chunk
                while b"\n" in buf:
                    raw, buf = buf.split(b"\n", 1)
                    if not raw.strip():
                        continue
                    try:
                        msg = json.loads(raw.decode("utf-8"))
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(msg, dict):
                        continue
                    # Ignore messages for other ids if multiplexed later
                    if msg.get("id") not in (None, rid) and cmd != "ping":
                        continue
                    mtype = msg.get("type")
                    if mtype == "progress":
                        if on_progress:
                            on_progress(msg)
                        continue
                    if mtype == "result" or "ok" in msg:
                        return msg
        finally:
            try:
                sock.close()
            except OSError:
                pass

    def cancel(self, request_id: str | None = None) -> dict[str, Any]:
        return self.request("cancel", {"request_id": request_id} if request_id else {})


def ensure_daemon(
    *,
    project_root: Path | None = None,
    python_bin: str | None = None,
    wait_seconds: float = 30.0,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    warmup: bool | None = None,
) -> DaemonClient:
    """
    Return a live DaemonClient, starting the daemon if needed.

    warmup: if True (default when OMNIFLOW_DAEMON_WARMUP is not 0), fire a
    best-effort ``warmup`` request so the next STT job does not pay cold load.
    Used by Tauri / CLI ensure.
    """
    if warmup is None:
        warmup = os.environ.get("OMNIFLOW_DAEMON_WARMUP", "1").strip().lower() not in (
            "0",
            "false",
            "no",
            "off",
        )

    client: DaemonClient | None = None
    st = read_state()
    if st and is_process_alive(st):
        client = DaemonClient.from_state(st)
        if not client.ping(timeout=1.5):
            log.warning("Daemon pid alive but ping failed; restarting")
            from .daemon import stop_daemon

            stop_daemon(timeout=3.0)
            client = None

    if client is None:
        root = project_root or _guess_project_root()
        py = (
            python_bin
            or os.environ.get("DIARY_PYTHON")
            or os.environ.get("PYTHON")
            or sys.executable
        )

        cmd = [
            py,
            "-m",
            "diary_app",
            "serve",
            "--detach",
            "--host",
            host,
            "--port",
            str(port),
        ]
        log.info("Starting daemon: %s (cwd=%s)", " ".join(cmd), root)
        env = os.environ.copy()
        env["PYTHONPATH"] = str(root) + os.pathsep + env.get("PYTHONPATH", "")
        subprocess.Popen(
            cmd,
            cwd=str(root),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )

        deadline = time.time() + wait_seconds
        last_err = "timeout"
        while time.time() < deadline:
            st = read_state()
            if st and is_process_alive(st):
                try:
                    client = DaemonClient.from_state(st)
                    if client.ping(timeout=1.0):
                        break
                except Exception as e:
                    last_err = str(e)
                    client = None
            time.sleep(0.2)
        else:
            raise DaemonError(f"Failed to start daemon within {wait_seconds}s: {last_err}")

    assert client is not None

    if warmup:
        try:
            # Non-blocking-ish: short timeout; model load may continue server-side if slow
            client.request(
                "warmup",
                {"backend": "auto", "device": "auto"},
                timeout=float(os.environ.get("OMNIFLOW_WARMUP_TIMEOUT", "120")),
            )
            log.info("Daemon warmup completed")
        except Exception as e:
            log.warning("Daemon warmup skipped/failed: %s", e)

    return client


def _guess_project_root() -> Path:
    # diary_app/core/daemon_client.py → repo root
    here = Path(__file__).resolve()
    candidate = here.parents[2]
    if (candidate / "diary_app" / "main.py").is_file():
        return candidate
    env = os.environ.get("DIARY_PROJECT_ROOT") or os.environ.get("OMNIFLOW_ROOT")
    if env:
        return Path(env)
    return Path.cwd()
