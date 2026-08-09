"""Backend and analyzer registries (plugin-style)."""
from __future__ import annotations

from typing import Any, Callable

from diary_app.config import get_config
from diary_app.core.logutil import get_logger

log = get_logger("registry")

_BACKENDS: dict[str, Callable[..., Any]] = {}
_ANALYZERS: dict[str, Callable[..., Any]] = {}


def register_backend(name: str):
    """Decorator: register a transcription backend factory/class."""

    def deco(cls_or_factory):
        _BACKENDS[name.lower()] = cls_or_factory
        return cls_or_factory

    return deco


def register_analyzer(name: str):
    def deco(cls_or_factory):
        _ANALYZERS[name.lower()] = cls_or_factory
        return cls_or_factory

    return deco


def available_backends() -> list[str]:
    _ensure_builtins()
    return sorted(_BACKENDS)


def available_analyzers() -> list[str]:
    _ensure_builtins()
    return sorted(_ANALYZERS)


def _ensure_builtins() -> None:
    if _BACKENDS:
        return
    # Lazy import to avoid hard deps at import time
    try:
        from diary_app.core.moss_backend import MossBackend

        _BACKENDS.setdefault("moss", MossBackend)
    except Exception as e:
        log.debug("moss not registered: %s", e)
    try:
        from diary_app.core.whisper_backend import WhisperBackend

        _BACKENDS.setdefault("whisper", WhisperBackend)
    except Exception as e:
        log.debug("whisper not registered: %s", e)
    try:
        from diary_app.core.nemo_backend import NeMoBackend

        _BACKENDS.setdefault("nemo", NeMoBackend)
    except Exception as e:
        log.debug("nemo not registered: %s", e)

    if not _ANALYZERS:
        from diary_app.core.analyzer import HeuristicAnalyzer

        _ANALYZERS["heuristic"] = HeuristicAnalyzer


def create_backend(
    name: str | None = None,
    *,
    device: str | None = None,
    max_speakers: int | None = None,
    **kwargs: Any,
) -> Any:
    """
    Instantiate a backend by name, or auto-try configured order.

    name: auto | moss | whisper | nemo | None (→ config.default_backend)
    """
    _ensure_builtins()
    cfg = get_config()
    name = (name or cfg.default_backend or "auto").lower()
    device = device or cfg.default_device
    max_speakers = max_speakers if max_speakers is not None else cfg.max_speakers

    def _make(key: str):
        factory = _BACKENDS.get(key)
        if not factory:
            raise RuntimeError(f"Backend not available: {key}")
        try:
            return factory(max_speakers=max_speakers, device=device, **kwargs)
        except TypeError:
            try:
                return factory(max_speakers=max_speakers, device=device)
            except TypeError:
                try:
                    return factory(max_speakers=max_speakers)
                except TypeError:
                    return factory()

    if name != "auto":
        return _make(name)

    errors: list[str] = []
    order = list(cfg.auto_backend_order) or ["moss", "whisper", "nemo"]
    for key in order:
        if key not in _BACKENDS:
            # try ensure again / skip
            continue
        try:
            return _make(key)
        except Exception as e:
            errors.append(f"{key}: {e}")
            log.warning("Backend %s failed: %s", key, e)
    raise RuntimeError(
        "No transcription backend available.\n"
        + "\n".join(f"  - {e}" for e in errors)
        + "\nInstall: pip install -e . && python -m diary_app.install_torch"
    )


def create_analyzer(name: str | None = None, **kwargs: Any) -> Any:
    _ensure_builtins()
    cfg = get_config()
    name = (name or cfg.analyzer or "heuristic").lower()
    factory = _ANALYZERS.get(name)
    if not factory:
        raise RuntimeError(f"Analyzer not available: {name}. Have: {list(_ANALYZERS)}")
    try:
        return factory(**kwargs)
    except TypeError:
        return factory()
