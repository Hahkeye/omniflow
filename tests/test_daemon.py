"""Localhost daemon protocol tests (no GPU / STT)."""
from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from diary_app.core.daemon import OmniflowDaemon, read_state, stop_daemon, clear_state
from diary_app.core.daemon_client import DaemonClient, DaemonError


@pytest.fixture
def daemon_env(tmp_path, monkeypatch):
    root = tmp_path / "diary"
    root.mkdir()
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("DIARY_DIR", str(root))
    # Point history default if needed
    import diary_app.core.daemon as d
    import diary_app.core.history as h

    monkeypatch.setattr(d, "diary_root", lambda: root)
    monkeypatch.setattr(h, "DEFAULT_DIARY_DIR", root)
    clear_state(root)
    yield root
    try:
        stop_daemon(root=root, timeout=3.0)
    except Exception:
        pass
    clear_state(root)


def _start_daemon(root: Path, port: int = 0) -> OmniflowDaemon:
    d = OmniflowDaemon(host="127.0.0.1", port=port, diary_dir=root, token="test-token")
    t = threading.Thread(target=d.serve_forever, daemon=True)
    t.start()
    # wait for state
    for _ in range(50):
        st = read_state(root)
        if st and st.get("port"):
            return d
        time.sleep(0.05)
    raise RuntimeError("daemon failed to start")


def test_ping_and_history(daemon_env):
    root = daemon_env
    d = _start_daemon(root, port=0)
    st = read_state(root)
    assert st is not None
    client = DaemonClient(
        host=st["host"],
        port=int(st["port"]),
        token=st["token"],
        timeout=10.0,
    )
    assert client.ping(timeout=2.0)

    # light API via daemon
    progress = []
    result = client.request(
        "history_list",
        {"limit": 5},
        on_progress=lambda m: progress.append(m),
        timeout=10.0,
    )
    assert result.get("ok") is True
    assert "entries" in result

    # bad token rejected
    bad = DaemonClient(host=st["host"], port=int(st["port"]), token="wrong")
    r = bad.request("history_list", {}, timeout=5.0)
    assert r.get("ok") is False
    assert "unauthorized" in str(r.get("error") or "").lower()

    d.request_shutdown()
    time.sleep(0.3)


def test_cancel_flag(daemon_env):
    root = daemon_env
    d = _start_daemon(root, port=0)
    st = read_state(root)
    client = DaemonClient.from_state(st)
    # cancel with nothing running
    r = client.cancel()
    assert r.get("ok") is True
    d.request_shutdown()
