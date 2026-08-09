"""SessionService — high-level facade for CLI / API / daemon."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from diary_app.config import AppConfig, get_config
from diary_app.core.store import EntryStore, get_store
from diary_app.services.pipeline import PipelineResult, run_session


class SessionService:
    """Product-facing session API."""

    def __init__(self, config: AppConfig | None = None, store: EntryStore | None = None):
        self.config = config or get_config()
        self.store = store or get_store(self.config.diary_dir)

    def transcribe(
        self,
        audio_path: str | Path,
        *,
        backend: str | None = None,
        device: str | None = None,
    ) -> PipelineResult:
        return run_session(
            audio_path=audio_path,
            backend=backend or self.config.default_backend,
            device=device or self.config.default_device,
            diary_dir=self.config.diary_dir,
        )

    def record_and_transcribe(
        self,
        *,
        duration: float = 30,
        backend: str | None = None,
        device: str | None = None,
        silence_stop: bool = False,
    ) -> PipelineResult:
        return run_session(
            record_duration=duration,
            backend=backend or self.config.default_backend,
            device=device or self.config.default_device,
            diary_dir=self.config.diary_dir,
            silence_stop=silence_stop,
        )

    def list_history(self, **kwargs: Any) -> list[dict]:
        return self.store.entries_for_api(**kwargs)

    def get_entry(self, entry_id: str) -> Any:
        return self.store.get_entry(entry_id)
