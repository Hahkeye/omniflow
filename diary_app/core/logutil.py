"""Structured logging for diary_app (CLI, API, backends)."""
from __future__ import annotations

import json
import logging
import os
import sys
from contextvars import ContextVar
from typing import Any, Callable

_CONFIGURED = False
LOGGER_NAME = "diary_app"

# Optional sink for daemon / in-process progress (in addition to stderr).
ProgressSink = Callable[[dict[str, Any]], None]
_progress_sink: ContextVar[ProgressSink | None] = ContextVar("progress_sink", default=None)
_cancel_check: ContextVar[Callable[[], bool] | None] = ContextVar("cancel_check", default=None)


def set_progress_sink(sink: ProgressSink | None):
    """Install a progress callback for the current context; returns a token for reset."""
    return _progress_sink.set(sink)


def reset_progress_sink(token) -> None:
    _progress_sink.reset(token)


def set_cancel_check(fn: Callable[[], bool] | None):
    return _cancel_check.set(fn)


def reset_cancel_check(token) -> None:
    _cancel_check.reset(token)


def is_cancelled() -> bool:
    fn = _cancel_check.get()
    return bool(fn and fn())


class CancelledError(RuntimeError):
    """Raised when a long job is cancelled via the daemon."""

    def __init__(self, message: str = "Operation cancelled"):
        super().__init__(message)


def get_logger(name: str | None = None) -> logging.Logger:
    """Return a child logger under diary_app."""
    ensure_logging()
    if name:
        return logging.getLogger(f"{LOGGER_NAME}.{name}")
    return logging.getLogger(LOGGER_NAME)


def ensure_logging(level: str | int | None = None) -> None:
    """Idempotent logging setup. Level from DIARY_LOG_LEVEL or INFO."""
    global _CONFIGURED
    if _CONFIGURED:
        if level is not None:
            logging.getLogger(LOGGER_NAME).setLevel(_parse_level(level))
        return

    env_level = os.environ.get("DIARY_LOG_LEVEL", "INFO")
    lvl = _parse_level(level if level is not None else env_level)
    root = logging.getLogger(LOGGER_NAME)
    root.setLevel(lvl)
    root.handlers.clear()
    root.propagate = False

    handler = logging.StreamHandler(sys.stderr)
    handler.setLevel(lvl)
    fmt = os.environ.get("DIARY_LOG_FORMAT", "text")
    if fmt == "json":
        handler.setFormatter(_JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s", "%H:%M:%S")
        )
    root.addHandler(handler)
    _CONFIGURED = True


def _parse_level(level: str | int) -> int:
    if isinstance(level, int):
        return level
    return getattr(logging, str(level).upper(), logging.INFO)


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def emit_progress(
    phase: str,
    fraction: float | None = None,
    message: str = "",
    **extra: Any,
) -> None:
    """
    Emit a machine-readable progress event on stderr (one NDJSON line).

    Prefix PROGRESS_JSON so UIs can filter reliably without mistaking logs.
    Also forwards to the context progress sink (daemon TCP clients).
    Raises CancelledError if a cancel check is installed and tripped.
    """
    if is_cancelled():
        raise CancelledError()
    payload: dict[str, Any] = {
        "type": "progress",
        "phase": phase,
        "message": message or phase,
    }
    if fraction is not None:
        payload["fraction"] = max(0.0, min(1.0, float(fraction)))
    payload.update(extra)
    line = "PROGRESS_JSON " + json.dumps(payload, ensure_ascii=False)
    print(line, file=sys.stderr, flush=True)
    sink = _progress_sink.get()
    if sink is not None:
        try:
            sink(payload)
        except CancelledError:
            raise
        except Exception:
            pass
