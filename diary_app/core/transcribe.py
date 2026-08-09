"""Transcription backend base + re-exports of domain models (compat layer)."""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

# Canonical models live in diary_app.domain — re-export for existing imports.
from diary_app.domain.models import KeyPoints, SpeakerSegment, Transcript

__all__ = [
    "SpeakerSegment",
    "Transcript",
    "KeyPoints",
    "TranscriptionBackend",
    "BaseTranscriptionBackend",
]


class TranscriptionBackend:
    """Legacy Protocol-like base (duck typing). Prefer domain.ports.TranscriptionBackend."""

    name: str
    description: str

    def transcribe(self, wav_path: Path) -> Transcript:
        raise NotImplementedError

    def get_speaker_ids(self) -> list[str]:
        raise NotImplementedError

    def warmup(self) -> None:
        return None


class BaseTranscriptionBackend(ABC):
    """Base class for transcription backends with common utilities."""

    speaker_prefix = "Speaker"
    name: str = "base"
    description: str = ""

    def __init__(self, max_speakers: int = 4):
        self.max_speakers = max_speakers

    def get_speaker_ids(self) -> list[str]:
        return [f"{self.speaker_prefix} {i}" for i in range(1, self.max_speakers + 1)]

    def map_speaker_label(self, label: str | int) -> str:
        if isinstance(label, int):
            return f"{self.speaker_prefix} {label + 1}"
        return str(label)

    @abstractmethod
    def transcribe(self, wav_path: Path) -> Transcript:
        ...

    def warmup(self) -> None:
        return None

    def unload(self) -> None:
        return None
