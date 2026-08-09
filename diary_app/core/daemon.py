"""
Long-lived Omniflow daemon — localhost NDJSON TCP service.

Product path for Tauri / desktop: one Python process keeps STT models warm
and multiplexes JSON commands with streaming progress.

Protocol (one JSON object per line, UTF-8):

  Request:
    {"v":1,"id":"<req-id>","token":"<auth>","cmd":"<name>","params":{...}}

  Server messages (same id):
    {"v":1,"id":"...","type":"progress","phase":"...","fraction":0.5,"message":"..."}
    {"v":1,"id":"...","type":"result","ok":true,...}   # success payload merged in
    {"v":1,"id":"...","type":"result","ok":false,"error":"..."}

Special commands (not in core.api.COMMANDS):
  ping, shutdown, warmup, cancel, status

State file: ~/diary/daemon.json  (host, port, pid, token, started_at)
"""
from __future__ import annotations

import json
import os
import secrets
import signal
import socketserver
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .logutil import (
    CancelledError,
    ensure_logging,
    get_logger,
    reset_cancel_check,
    reset_progress_sink,
    set_cancel_check,
    set_progress_sink,
)

log = get_logger("daemon")

PROTOCOL_VERSION = 1
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 17432  # fixed default; 0 = ephemeral
STATE_NAME = "daemon.json"
LOG_NAME = "daemon.log"


def diary_root() -> Path:
    if os.environ.get("DIARY_DIR") or os.environ.get("OMNIFLOW_DIARY_DIR"):
        return Path(os.environ.get("DIARY_DIR") or os.environ["OMNIFLOW_DIARY_DIR"]).expanduser()
    try:
        from diary_app.config import get_config

        return Path(get_config().diary_dir)
    except Exception:
        return Path.home() / "diary"


def state_path(root: Path | None = None) -> Path:
    return (root or diary_root()) / STATE_NAME


def log_path(root: Path | None = None) -> Path:
    return (root or diary_root()) / LOG_NAME


def read_state(root: Path | None = None) -> dict[str, Any] | None:
    path = state_path(root)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def write_state(data: dict[str, Any], root: Path | None = None) -> Path:
    root = root or diary_root()
    root.mkdir(parents=True, exist_ok=True)
    path = state_path(root)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return path


def clear_state(root: Path | None = None) -> None:
    path = state_path(root)
    try:
        if path.is_file():
            path.unlink()
    except OSError:
        pass


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists but not ours
    except OSError:
        return False
    return True


def is_process_alive(state: dict[str, Any] | None = None) -> bool:
    state = state or read_state()
    if not state:
        return False
    pid = int(state.get("pid") or 0)
    return _pid_alive(pid)


# ─── Job cancellation registry ───────────────────────────────────────────────

class _JobRegistry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._events: dict[str, threading.Event] = {}
        self._current: str | None = None

    def begin(self, request_id: str) -> threading.Event:
        ev = threading.Event()
        with self._lock:
            self._events[request_id] = ev
            self._current = request_id
        return ev

    def end(self, request_id: str) -> None:
        with self._lock:
            self._events.pop(request_id, None)
            if self._current == request_id:
                self._current = None

    def cancel(self, request_id: str | None = None) -> bool:
        with self._lock:
            rid = request_id or self._current
            if not rid:
                return False
            ev = self._events.get(rid)
            if not ev:
                return False
            ev.set()
            return True

    def current(self) -> str | None:
        with self._lock:
            return self._current


JOBS = _JobRegistry()

# Serialize heavy STT / record work so the GPU is not contested
_HEAVY_LOCK = threading.Lock()
_HEAVY_CMDS = frozenset({"transcribe", "record", "warmup"})


class OmniflowDaemon:
    """TCP NDJSON daemon bound to localhost."""

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        *,
        token: str | None = None,
        diary_dir: Path | None = None,
    ):
        self.host = host
        self.port = int(port)
        self.token = token or secrets.token_urlsafe(24)
        self.diary_dir = Path(diary_dir) if diary_dir else diary_root()
        self.started_at = datetime.now(timezone.utc).isoformat()
        self._server: socketserver.ThreadingTCPServer | None = None
        self._shutdown = threading.Event()
        self.pid = os.getpid()

    def state_dict(self, bound_port: int | None = None) -> dict[str, Any]:
        return {
            "v": PROTOCOL_VERSION,
            "host": self.host,
            "port": bound_port if bound_port is not None else self.port,
            "pid": self.pid,
            "token": self.token,
            "started_at": self.started_at,
            "diary_dir": str(self.diary_dir),
        }

    def serve_forever(self) -> None:
        ensure_logging()
        host = self.host
        # Force loopback for product safety unless explicitly overridden
        if host not in ("127.0.0.1", "localhost", "::1") and os.environ.get(
            "OMNIFLOW_DAEMON_ALLOW_REMOTE"
        ) != "1":
            log.warning("Refusing non-loopback bind %s; using 127.0.0.1", host)
            host = "127.0.0.1"
            self.host = host

        owner = self

        class _Handler(socketserver.StreamRequestHandler):
            def handle(self) -> None:  # noqa: N802
                owner._handle_connection(self)

        class _Server(socketserver.ThreadingTCPServer):
            allow_reuse_address = True
            daemon_threads = True

        try:
            server = _Server((host, self.port), _Handler)
        except OSError as e:
            log.error("Failed to bind %s:%s — %s", host, self.port, e)
            raise

        self._server = server
        bound_port = int(server.server_address[1])
        self.port = bound_port
        write_state(self.state_dict(bound_port), self.diary_dir)
        log.info(
            "Omniflow daemon listening on %s:%s pid=%s",
            host,
            bound_port,
            self.pid,
        )
        print(
            json.dumps(
                {
                    "ok": True,
                    "listening": True,
                    "host": host,
                    "port": bound_port,
                    "pid": self.pid,
                    "state": str(state_path(self.diary_dir)),
                }
            ),
            flush=True,
        )

        def _on_signal(signum, _frame):
            log.info("Signal %s — shutting down", signum)
            self.request_shutdown()

        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                signal.signal(sig, _on_signal)
            except (ValueError, OSError):
                pass

        try:
            server.serve_forever(poll_interval=0.5)
        finally:
            try:
                server.server_close()
            except OSError:
                pass
            st = read_state(self.diary_dir)
            if st and int(st.get("pid") or 0) == self.pid:
                clear_state(self.diary_dir)
            log.info("Daemon stopped")

    def request_shutdown(self) -> None:
        self._shutdown.set()
        if self._server:
            try:
                self._server.shutdown()
            except Exception:
                pass

    def _handle_connection(self, handler: socketserver.StreamRequestHandler) -> None:
        rfile = handler.rfile
        wfile = handler.wfile
        write_lock = threading.Lock()

        def send(obj: dict[str, Any]) -> None:
            line = json.dumps(obj, ensure_ascii=False) + "\n"
            with write_lock:
                try:
                    wfile.write(line.encode("utf-8"))
                    wfile.flush()
                except OSError:
                    pass

        while not self._shutdown.is_set():
            raw = rfile.readline()
            if not raw:
                break
            line = raw.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            try:
                req = json.loads(line)
            except json.JSONDecodeError as e:
                send(
                    {
                        "v": PROTOCOL_VERSION,
                        "id": None,
                        "type": "result",
                        "ok": False,
                        "error": f"invalid JSON: {e}",
                    }
                )
                continue
            if not isinstance(req, dict):
                send(
                    {
                        "v": PROTOCOL_VERSION,
                        "id": None,
                        "type": "result",
                        "ok": False,
                        "error": "request must be an object",
                    }
                )
                continue
            self._dispatch_request(req, send)

    def _dispatch_request(
        self,
        req: dict[str, Any],
        send: Callable[[dict[str, Any]], None],
    ) -> None:
        rid = str(req.get("id") or secrets.token_hex(8))
        token = str(req.get("token") or "")
        cmd = str(req.get("cmd") or req.get("command") or "").strip()
        params = req.get("params") if isinstance(req.get("params"), dict) else {}
        # allow top-level params merge for convenience
        if not params:
            params = {
                k: v
                for k, v in req.items()
                if k not in ("v", "id", "token", "cmd", "command", "params")
            }

        def reply_progress(payload: dict[str, Any]) -> None:
            msg = {
                "v": PROTOCOL_VERSION,
                "id": rid,
                "type": "progress",
                "phase": payload.get("phase"),
                "fraction": payload.get("fraction"),
                "message": payload.get("message"),
            }
            for k, v in payload.items():
                if k not in msg:
                    msg[k] = v
            send(msg)

        def reply_result(result: dict[str, Any]) -> None:
            out = {"v": PROTOCOL_VERSION, "id": rid, "type": "result"}
            out.update(result)
            if "ok" not in out:
                out["ok"] = True
            send(out)

        # Auth (ping without token only if state allows? require token always after start)
        if cmd != "ping" and token != self.token:
            # allow ping without token for liveness probes
            if cmd not in ("ping",):
                reply_result({"ok": False, "error": "unauthorized (bad token)"})
                return

        if cmd == "ping":
            reply_result(
                {
                    "ok": True,
                    "pong": True,
                    "pid": self.pid,
                    "port": self.port,
                    "started_at": self.started_at,
                    "current_job": JOBS.current(),
                }
            )
            return

        if cmd == "status":
            if token != self.token:
                reply_result({"ok": False, "error": "unauthorized (bad token)"})
                return
            reply_result(
                {
                    "ok": True,
                    "pid": self.pid,
                    "port": self.port,
                    "host": self.host,
                    "started_at": self.started_at,
                    "current_job": JOBS.current(),
                    "diary_dir": str(self.diary_dir),
                }
            )
            return

        if cmd == "shutdown":
            if token != self.token:
                reply_result({"ok": False, "error": "unauthorized (bad token)"})
                return
            reply_result({"ok": True, "shutting_down": True})
            threading.Thread(target=self.request_shutdown, daemon=True).start()
            return

        if cmd == "cancel":
            if token != self.token:
                reply_result({"ok": False, "error": "unauthorized (bad token)"})
                return
            target = params.get("request_id") or params.get("id")
            ok = JOBS.cancel(str(target) if target else None)
            reply_result({"ok": True, "cancelled": ok, "request_id": target or JOBS.current()})
            return

        if cmd == "warmup":
            if token != self.token:
                reply_result({"ok": False, "error": "unauthorized (bad token)"})
                return
            result = self._run_warmup(rid, params, reply_progress)
            reply_result(result)
            return

        # Delegate to core.api
        from .api import COMMANDS, dispatch

        if cmd not in COMMANDS:
            reply_result(
                {
                    "ok": False,
                    "error": f"Unknown command: {cmd}",
                    "commands": sorted(list(COMMANDS) + ["ping", "status", "shutdown", "cancel", "warmup"]),
                }
            )
            return

        cancel_ev = JOBS.begin(rid)
        sink_tok = set_progress_sink(reply_progress)
        cancel_tok = set_cancel_check(cancel_ev.is_set)
        try:
            heavy = cmd in _HEAVY_CMDS
            if heavy:
                acquired = _HEAVY_LOCK.acquire(timeout=float(params.get("lock_timeout") or 600))
                if not acquired:
                    reply_result({"ok": False, "error": "Another heavy job is running"})
                    return
            try:
                if cancel_ev.is_set():
                    raise CancelledError()
                result = dispatch(cmd, params)
                if cancel_ev.is_set() and result.get("ok"):
                    # finished but cancel was requested mid-flight after completion — still ok
                    pass
                reply_result(result)
            except CancelledError as e:
                reply_result({"ok": False, "error": str(e), "cancelled": True})
            except Exception as e:
                log.exception("daemon cmd %s failed", cmd)
                reply_result({"ok": False, "error": str(e)})
            finally:
                if heavy:
                    _HEAVY_LOCK.release()
        finally:
            reset_progress_sink(sink_tok)
            reset_cancel_check(cancel_tok)
            JOBS.end(rid)

    def _run_warmup(
        self,
        rid: str,
        params: dict,
        progress: Callable[[dict[str, Any]], None],
    ) -> dict[str, Any]:
        cancel_ev = JOBS.begin(rid)
        sink_tok = set_progress_sink(progress)
        cancel_tok = set_cancel_check(cancel_ev.is_set)
        try:
            with _HEAVY_LOCK:
                progress({"type": "progress", "phase": "warmup", "fraction": 0.1, "message": "Loading MOSS"})
                backend_name = (params.get("backend") or "moss").lower()
                device = params.get("device") or "auto"
                if backend_name in ("moss", "auto"):
                    from .moss_backend import MossBackend

                    MossBackend(max_speakers=int(params.get("max_speakers") or 4), device=device)
                elif backend_name == "whisper":
                    from .whisper_backend import WhisperBackend

                    WhisperBackend(max_speakers=4, device=device)
                else:
                    return {"ok": False, "error": f"warmup not supported for {backend_name}"}
                progress({"type": "progress", "phase": "warmup", "fraction": 1.0, "message": "Ready"})
                return {"ok": True, "backend": backend_name, "device": device}
        except CancelledError as e:
            return {"ok": False, "error": str(e), "cancelled": True}
        except Exception as e:
            log.exception("warmup failed")
            return {"ok": False, "error": str(e)}
        finally:
            reset_progress_sink(sink_tok)
            reset_cancel_check(cancel_tok)
            JOBS.end(rid)


def detach_and_serve(
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    *,
    diary_dir: Path | None = None,
    token: str | None = None,
) -> int:
    """
    Background the process (Unix double-fork) then serve.
    On Windows, caller should use subprocess CREATE_NEW_PROCESS_GROUP instead.
    Returns 0 after parent exits; child does not return until shutdown.
    """
    root = Path(diary_dir) if diary_dir else diary_root()
    root.mkdir(parents=True, exist_ok=True)
    log_file = log_path(root)

    if os.name == "nt":
        # Parent should have already spawned us; just serve in foreground of this process
        daemon = OmniflowDaemon(host=host, port=port, token=token, diary_dir=root)
        daemon.serve_forever()
        return 0

    # Unix detach
    if os.fork() > 0:
        return 0
    os.setsid()
    if os.fork() > 0:
        os._exit(0)

    sys.stdout.flush()
    sys.stderr.flush()
    with open(log_file, "a", encoding="utf-8") as lf:
        os.dup2(lf.fileno(), sys.stdout.fileno())
        os.dup2(lf.fileno(), sys.stderr.fileno())

    ensure_logging()
    daemon = OmniflowDaemon(host=host, port=port, token=token, diary_dir=root)
    daemon.serve_forever()
    return 0


def run_serve_argv(argv: list[str] | None = None) -> int:
    import argparse

    ensure_logging()
    p = argparse.ArgumentParser(prog="diary_app serve", description="Omniflow local daemon")
    p.add_argument("--host", default=os.environ.get("OMNIFLOW_DAEMON_HOST", DEFAULT_HOST))
    p.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("OMNIFLOW_DAEMON_PORT", str(DEFAULT_PORT))),
        help="TCP port (0 = ephemeral)",
    )
    p.add_argument("--detach", "-d", action="store_true", help="Run in background (Unix)")
    p.add_argument("--token", default=None, help="Auth token (default: random, stored in daemon.json)")
    p.add_argument("--dir", default=None, help="Diary directory (default ~/diary)")
    p.add_argument(
        "--replace",
        action="store_true",
        help="Stop an existing daemon before starting",
    )
    args = p.parse_args(argv)
    root = Path(args.dir).expanduser() if args.dir else diary_root()

    if args.replace:
        stop_daemon(root=root, timeout=5.0)

    existing = read_state(root)
    if existing and is_process_alive(existing):
        # Try ping — if alive, refuse unless replace
        from .daemon_client import DaemonClient

        try:
            client = DaemonClient.from_state(existing)
            if client.ping(timeout=1.0):
                print(
                    json.dumps(
                        {
                            "ok": False,
                            "error": "daemon already running",
                            "state": {k: existing[k] for k in existing if k != "token"},
                            "hint": "use --replace or: python -m diary_app daemon stop",
                        }
                    ),
                    flush=True,
                )
                return 1
        except Exception:
            pass
        # stale state
        clear_state(root)

    if args.detach and os.name != "nt":
        # Parent waits briefly for state file
        token = args.token or secrets.token_urlsafe(24)
        # fork path needs token known to parent — pre-write? child writes state
        # Pass token via env to child simplicity: run detach_and_serve in child after fork
        rc = detach_and_serve(host=args.host, port=args.port, diary_dir=root, token=token)
        # parent returns immediately from first fork
        deadline = time.time() + 15
        while time.time() < deadline:
            st = read_state(root)
            if st and is_process_alive(st):
                print(json.dumps({"ok": True, "detached": True, "state": _public_state(st)}), flush=True)
                return 0
            time.sleep(0.15)
        print(json.dumps({"ok": False, "error": "daemon did not become ready in time"}), flush=True)
        return 1

    if args.detach and os.name == "nt":
        # Spawn a new process without --detach
        import subprocess

        cmd = [
            sys.executable,
            "-m",
            "diary_app",
            "serve",
            "--host",
            args.host,
            "--port",
            str(args.port),
        ]
        if args.token:
            cmd.extend(["--token", args.token])
        if args.dir:
            cmd.extend(["--dir", args.dir])
        creation = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(
            subprocess, "DETACHED_PROCESS", 0x00000008
        )
        subprocess.Popen(
            cmd,
            cwd=str(Path(__file__).resolve().parents[2]),
            stdout=open(log_path(root), "a", encoding="utf-8"),
            stderr=subprocess.STDOUT,
            creationflags=creation,
            close_fds=True,
        )
        deadline = time.time() + 20
        while time.time() < deadline:
            st = read_state(root)
            if st and is_process_alive(st):
                print(json.dumps({"ok": True, "detached": True, "state": _public_state(st)}), flush=True)
                return 0
            time.sleep(0.2)
        print(json.dumps({"ok": False, "error": "daemon did not become ready"}), flush=True)
        return 1

    # Foreground
    daemon = OmniflowDaemon(
        host=args.host,
        port=args.port,
        token=args.token,
        diary_dir=root,
    )
    daemon.serve_forever()
    return 0


def _public_state(st: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in st.items() if k != "token"}


def stop_daemon(root: Path | None = None, timeout: float = 8.0) -> dict[str, Any]:
    from .daemon_client import DaemonClient

    root = root or diary_root()
    st = read_state(root)
    if not st:
        return {"ok": True, "stopped": False, "reason": "no state file"}
    if not is_process_alive(st):
        clear_state(root)
        return {"ok": True, "stopped": False, "reason": "stale state cleared"}
    try:
        client = DaemonClient.from_state(st)
        client.request("shutdown", {}, timeout=timeout)
    except Exception as e:
        # force kill
        pid = int(st.get("pid") or 0)
        if pid:
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError as kill_err:
                return {"ok": False, "error": f"shutdown failed: {e}; kill: {kill_err}"}
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not is_process_alive(st):
            clear_state(root)
            return {"ok": True, "stopped": True}
        time.sleep(0.1)
    # hard kill
    pid = int(st.get("pid") or 0)
    if pid:
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass
    clear_state(root)
    return {"ok": True, "stopped": True, "forced": True}


def daemon_status(root: Path | None = None) -> dict[str, Any]:
    from .daemon_client import DaemonClient

    root = root or diary_root()
    st = read_state(root)
    if not st:
        return {"ok": True, "running": False}
    alive = is_process_alive(st)
    out: dict[str, Any] = {
        "ok": True,
        "running": alive,
        "state": _public_state(st),
    }
    if alive:
        try:
            client = DaemonClient.from_state(st)
            pong = client.request("ping", {}, timeout=2.0)
            out["ping"] = pong
        except Exception as e:
            out["ping_error"] = str(e)
            out["running"] = False
    return out
