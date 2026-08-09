"""SessionService — single product facade for CLI, API, Gradio, and scripts.

All STT backend construction goes through the registry. UIs must not import
moss/whisper/nemo backends directly.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from diary_app.config import AppConfig, get_config
from diary_app.core.registry import available_backends, create_backend
from diary_app.core.store import EntryStore, get_store
from diary_app.domain.models import KeyPoints, Transcript
from diary_app.services.pipeline import (
    PipelineResult,
    analyze_transcript,
    record_audio,
    run_session,
)


def format_key_points_markdown(key_points: KeyPoints | dict | None) -> str:
    """Shared Markdown rendering for Gradio / docs (not CLI panels)."""
    if not key_points:
        return ""
    if isinstance(key_points, KeyPoints):
        d = key_points.to_json()
    elif isinstance(key_points, dict):
        # Nested analysis docs: {"key_points": {...}}
        nested = key_points.get("key_points")
        d = nested if isinstance(nested, dict) else key_points
    else:
        return ""

    lines: list[str] = []
    if d.get("summary"):
        lines.append(f"## Summary\n{d['summary']}")
    if d.get("decisions"):
        lines.append("## Decisions")
        for item in d["decisions"]:
            lines.append(f"✓ {item}")
    if d.get("action_items"):
        lines.append("## Action items")
        for item in d["action_items"]:
            lines.append(f"☐ {item}")
    if d.get("key_points") and isinstance(d["key_points"], list):
        lines.append("## Key Points")
        for i, kp in enumerate(d["key_points"], 1):
            lines.append(f"{i}. {kp}")
    if d.get("topics"):
        lines.append("## Topics")
        for t in d["topics"]:
            lines.append(f"• {t}")
    if d.get("takeaways"):
        lines.append("## Takeaways")
        for ta in d["takeaways"]:
            lines.append(f"• {ta}")
    return "\n\n".join(lines)


def format_transcript_lines(transcript: Transcript | dict | None) -> str:
    """Plain multi-line transcript for UIs."""
    if transcript is None:
        return ""
    if isinstance(transcript, dict):
        transcript = Transcript.from_json(transcript)
    lines = [
        f"[{seg.speaker}] ({seg.start_time:.1f}s - {seg.end_time:.1f}s): {seg.text}"
        for seg in transcript.segments
    ]
    return "\n".join(lines)


class BackendCache:
    """Process-local warm backend cache (Gradio / long-lived UIs)."""

    def __init__(self) -> None:
        self._backend: Any | None = None
        self._key: tuple | None = None

    def get(
        self,
        name: str | None = None,
        *,
        device: str | None = None,
        max_speakers: int | None = None,
        model_size: str | None = None,
        warmup: bool = True,
    ) -> Any:
        cfg = get_config()
        name = (name or cfg.default_backend or "auto").lower()
        device = device or cfg.default_device
        max_speakers = max_speakers if max_speakers is not None else cfg.max_speakers
        key = (name, device, max_speakers, model_size, warmup)
        if self._backend is not None and self._key == key:
            return self._backend
        self.clear()
        self._backend = create_backend(
            name,
            device=device,
            max_speakers=max_speakers,
            model_size=model_size,
            warmup=warmup,
        )
        self._key = key
        return self._backend

    def clear(self) -> None:
        if self._backend is not None:
            try:
                unload = getattr(self._backend, "unload", None)
                if callable(unload):
                    unload()
            except Exception:
                pass
        self._backend = None
        self._key = None


class SessionService:
    """Product-facing session API used by CLI handlers, Gradio, and tests."""

    def __init__(
        self,
        config: AppConfig | None = None,
        store: EntryStore | None = None,
        *,
        cache: BackendCache | None = None,
    ):
        self.config = config or get_config()
        self.store = store or get_store(self.config.diary_dir)
        self.cache = cache if cache is not None else BackendCache()

    @property
    def diary_dir(self) -> Path:
        return Path(self.config.diary_dir)

    def available_backends(self) -> list[str]:
        return available_backends()

    def create_backend(
        self,
        name: str | None = None,
        *,
        device: str | None = None,
        max_speakers: int | None = None,
        model_size: str | None = None,
        warmup: bool = True,
        use_cache: bool = False,
    ) -> Any:
        if use_cache:
            return self.cache.get(
                name,
                device=device,
                max_speakers=max_speakers,
                model_size=model_size,
                warmup=warmup,
            )
        return create_backend(
            name,
            device=device or self.config.default_device,
            max_speakers=max_speakers if max_speakers is not None else self.config.max_speakers,
            model_size=model_size,
            warmup=warmup,
        )

    def record(
        self,
        *,
        duration: float = 30,
        diary_dir: Path | str | None = None,
        silence_stop: bool = False,
        device_id: int | None = None,
    ) -> Path:
        return record_audio(
            duration=duration,
            diary_dir=Path(diary_dir) if diary_dir else self.diary_dir,
            silence_stop=silence_stop,
            device_id=device_id,
        )

    def run(
        self,
        *,
        audio_path: Path | str | None = None,
        record_duration: float | None = None,
        backend: str | None = None,
        device: str | None = None,
        diary_dir: Path | str | None = None,
        analyze: bool = True,
        persist: bool = True,
        sync_action_inbox: bool = True,
        silence_stop: bool = False,
        max_speakers: int | None = None,
        model_size: str | None = None,
        use_cache: bool = False,
    ) -> PipelineResult:
        """Full pipeline. Optionally reuse a warm cached backend (Gradio)."""
        root = Path(diary_dir) if diary_dir else self.diary_dir
        be = None
        if use_cache:
            try:
                be = self.create_backend(
                    backend or self.config.default_backend,
                    device=device or self.config.default_device,
                    max_speakers=max_speakers,
                    model_size=model_size,
                    use_cache=True,
                )
            except Exception as e:
                return PipelineResult(ok=False, error=str(e))

        return run_session(
            audio_path=audio_path,
            record_duration=record_duration,
            backend=backend or self.config.default_backend,
            device=device or self.config.default_device,
            diary_dir=root,
            analyze=analyze,
            persist=persist,
            sync_action_inbox=sync_action_inbox,
            silence_stop=silence_stop,
            max_speakers=max_speakers,
            model_size=model_size,
            backend_instance=be,
        )

    def analyze_transcript_data(
        self,
        data: dict | Transcript,
        *,
        analyzer_name: str | None = None,
    ) -> KeyPoints:
        if isinstance(data, Transcript):
            transcript = data
        else:
            transcript = Transcript.from_json(data)
        return analyze_transcript(transcript, analyzer_name=analyzer_name)

    def analyze_file(
        self,
        path: Path | str,
        *,
        analyzer_name: str | None = None,
    ) -> tuple[Transcript, KeyPoints]:
        p = Path(path).expanduser()
        import json

        with open(p, encoding="utf-8") as f:
            data = json.load(f)
        transcript = Transcript.from_json(data)
        kp = analyze_transcript(transcript, analyzer_name=analyzer_name)
        return transcript, kp

    def list_history(self, **kwargs: Any) -> list[dict]:
        return self.store.entries_for_api(**kwargs)

    def get_entry(self, entry_id: str) -> Any:
        return self.store.get_entry(entry_id)


# Module-level default for simple callers
_default_service: SessionService | None = None


def get_session_service() -> SessionService:
    global _default_service
    if _default_service is None:
        _default_service = SessionService()
    return _default_service


def reset_session_service() -> None:
    """Test helper: drop the cached service (and any warm backends)."""
    global _default_service
    if _default_service is not None:
        _default_service.cache.clear()
    _default_service = None
