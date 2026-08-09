"""Ports (interfaces) for adapters — STT, analysis, storage."""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from .models import KeyPoints, Transcript


@runtime_checkable
class TranscriptionBackend(Protocol):
    name: str
    description: str

    def transcribe(self, wav_path: Path) -> "Transcript": ...

    def get_speaker_ids(self) -> list[str]: ...

    def warmup(self) -> None: ...

    def unload(self) -> None: ...


@runtime_checkable
class Analyzer(Protocol):
    name: str

    def analyze(self, transcript: "Transcript") -> "KeyPoints": ...


@runtime_checkable
class EntryStorePort(Protocol):
    def save_bundle(
        self,
        transcript: Any,
        key_points: Any | None = None,
        *,
        audio_path: Path | str | None = None,
        backend: str | None = None,
        device: str | None = None,
        entry_id: str | None = None,
    ) -> Any: ...

    def list_entries(self, *, limit: int | None = None, include_archived: bool = False) -> list[Any]: ...

    def get_entry(self, entry_id: str) -> Any | None: ...

    def delete_entry(self, entry_id: str, *, delete_audio: bool = False) -> dict: ...

    def archive_entry(self, entry_id: str, *, unarchive: bool = False) -> Any: ...
