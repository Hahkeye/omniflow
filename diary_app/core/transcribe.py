"""Transcription backend abstraction for multi-speaker diarization + ASR."""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

import numpy as np
from pydantic import BaseModel, Field

# ─── Data models ────────────────────────────────────────────────────────────────

@dataclass
class SpeakerSegment:
    """A segment of speech from one speaker."""
    speaker: str  # speaker label like "Speaker 1", "Speaker 2", etc.
    start_time: float  # start time in seconds
    end_time: float  # end time in seconds
    text: str  # transcribed text

    def __str__(self):
        return f"[{self.speaker}] ({self.start_time:.1f}s - {self.end_time:.1f}s): {self.text}"

    def to_dict(self):
        return {"speaker": self.speaker, "start_time": self.start_time, "end_time": self.end_time, "text": self.text}

    @classmethod
    def from_dict(cls, d):
        return cls(speaker=d["speaker"], start_time=d["start_time"], end_time=d["end_time"], text=d["text"])

@dataclass
class Transcript:
    """Complete transcript with speaker-tagged segments."""
    segments: list[SpeakerSegment] = field(default_factory=list)

    @property
    def speakers(self) -> list[str]:
        return sorted(set(s.speaker for s in self.segments))

    @property
    def full_text(self) -> str:
        return " ".join(s.text for s in self.segments)

    @property
    def duration(self) -> float:
        if not self.segments:
            return 0.0
        return self.segments[-1].end_time - self.segments[0].start_time

    def by_speaker(self) -> dict[str, list[SpeakerSegment]]:
        result: dict[str, list[SpeakerSegment]] = {}
        for seg in self.segments:
            result.setdefault(seg.speaker, []).append(seg)
        return result

    def format(self) -> str:
        lines = []
        for seg in self.segments:
            lines.append(f"{seg}")
        return "\n".join(lines)

    def to_json(self) -> dict:
        return {"segments": [s.to_dict() for s in self.segments]}

    @classmethod
    def from_json(cls, d):
        return cls(segments=[SpeakerSegment.from_dict(seg) for seg in d["segments"]])

@dataclass
class KeyPoints:
    """Analysis results from a transcript."""
    summary: str = ""
    key_points: list[str] = field(default_factory=list)
    takeaways: list[str] = field(default_factory=list)
    topics: list[str] = field(default_factory=list)
    speaker_stats: dict[str, dict] = field(default_factory=dict)
    def to_json(self) -> dict:
        return {"summary": self.summary, "key_points": self.key_points, "takeaways": self.takeaways, "topics": self.topics, "speaker_stats": self.speaker_stats}

    @classmethod
    def from_json(cls, d):
        return cls(summary=d.get("summary", ""), key_points=d.get("key_points", []), takeaways=d.get("takeaways", []), topics=d.get("topics", []), speaker_stats=d.get("speaker_stats", {}))
# ─── Backend protocol ───────────────────────────────────────────────────────────

class TranscriptionBackend(Protocol):
    """Protocol defining the interface for transcription backends."""

    name: str
    description: str

    @abstractmethod
    def transcribe(self, wav_path: Path) -> Transcript:
        """Transcribe a WAV audio file, returning speaker-tagged segments."""
        ...

    @abstractmethod
    def get_speaker_ids(self) -> list[str]:
        """Return the list of speaker IDs that will be used."""
        ...

    @abstractmethod
    def warmup(self) -> None:
        """Warm up the model (download weights, init GPU, etc.)."""
        ...

# ─── Base backend ───────────────────────────────────────────────────────────────

class BaseTranscriptionBackend(ABC):
    """Base class for transcription backends with common utilities."""

    speaker_prefix = "Speaker"

    def __init__(self, max_speakers: int = 4):
        self.max_speakers = max_speakers

    def get_speaker_ids(self) -> list[str]:
        return [f"{self.speaker_prefix} {i}" for i in range(1, self.max_speakers + 1)]

    def map_speaker_label(self, label: str | int) -> str:
        """Map model-specific speaker labels to human-readable names."""
        if isinstance(label, int):
            return f"{self.speaker_prefix} {label + 1}"
        return str(label)

    def ensure_audio_config(self, wav_path: Path, sample_rate: int) -> Path:
        """Ensure the audio file has the correct sample rate and format.
        
        Note: Our audio recorder already records as 16kHz mono WAV,
        so this is typically a no-op. Kept for potential future use.
        """
        return wav_path
