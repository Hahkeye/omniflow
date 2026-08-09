"""Canonical domain models (schema_version=2).

Internal times use `start` / `end` only. Serialization may still emit legacy
`start_time` / `end_time` keys for older clients.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from diary_app.config import SCHEMA_VERSION


@dataclass
class SpeakerSegment:
    """A segment of speech from one speaker."""

    speaker: str
    start: float = 0.0  # seconds (canonical)
    end: float = 0.0
    text: str = ""

    def __init__(
        self,
        speaker: str,
        start: float = 0.0,
        end: float = 0.0,
        text: str = "",
        *,
        start_time: float | None = None,
        end_time: float | None = None,
    ):
        # Accept legacy start_time/end_time kwargs used by backends
        object.__setattr__(self, "speaker", speaker)
        object.__setattr__(
            self,
            "start",
            float(start_time if start_time is not None else start),
        )
        object.__setattr__(
            self,
            "end",
            float(end_time if end_time is not None else end),
        )
        object.__setattr__(self, "text", text)

    # Back-compat properties
    @property
    def start_time(self) -> float:
        return self.start

    @property
    def end_time(self) -> float:
        return self.end

    def __str__(self) -> str:
        return f"[{self.speaker}] ({self.start:.1f}s - {self.end:.1f}s): {self.text}"

    def to_dict(self, *, legacy_keys: bool = True) -> dict[str, Any]:
        d: dict[str, Any] = {
            "speaker": self.speaker,
            "start": self.start,
            "end": self.end,
            "text": self.text,
        }
        if legacy_keys:
            d["start_time"] = self.start
            d["end_time"] = self.end
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "SpeakerSegment":
        start = d.get("start", d.get("start_time", 0.0))
        end = d.get("end", d.get("end_time", 0.0))
        return cls(
            speaker=str(d.get("speaker") or "Speaker 1"),
            start=float(start or 0.0),
            end=float(end or 0.0),
            text=str(d.get("text") or ""),
        )


@dataclass
class Transcript:
    """Complete transcript with speaker-tagged segments."""

    segments: list[SpeakerSegment] = field(default_factory=list)
    raw_text: str = ""
    warnings: list[str] = field(default_factory=list)
    schema_version: int = SCHEMA_VERSION

    @property
    def speakers(self) -> list[str]:
        return sorted({s.speaker for s in self.segments})

    @property
    def full_text(self) -> str:
        if self.segments:
            return " ".join(s.text for s in self.segments)
        return (self.raw_text or "").strip()

    @property
    def duration(self) -> float:
        if not self.segments:
            return 0.0
        return max(s.end for s in self.segments) - min(s.start for s in self.segments)

    def by_speaker(self) -> dict[str, list[SpeakerSegment]]:
        result: dict[str, list[SpeakerSegment]] = {}
        for seg in self.segments:
            result.setdefault(seg.speaker, []).append(seg)
        return result

    def format(self) -> str:
        return "\n".join(str(seg) for seg in self.segments)

    def to_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "schema_version": self.schema_version,
            "segments": [s.to_dict() for s in self.segments],
        }
        if self.raw_text:
            out["raw_text"] = self.raw_text
        if self.warnings:
            out["warnings"] = list(self.warnings)
        return out

    @classmethod
    def from_json(cls, d: dict[str, Any]) -> "Transcript":
        if "transcript" in d and isinstance(d["transcript"], dict):
            d = d["transcript"]
        return cls(
            segments=[SpeakerSegment.from_dict(seg) for seg in d.get("segments", []) or []],
            raw_text=d.get("raw_text", "") or "",
            warnings=list(d.get("warnings") or []),
            schema_version=int(d.get("schema_version") or SCHEMA_VERSION),
        )


@dataclass
class KeyPoints:
    """Analysis results from a transcript."""

    summary: str = ""
    key_points: list[str] = field(default_factory=list)
    takeaways: list[str] = field(default_factory=list)
    topics: list[str] = field(default_factory=list)
    speaker_stats: dict[str, dict] = field(default_factory=dict)
    action_items: list[str] = field(default_factory=list)
    decisions: list[str] = field(default_factory=list)
    schema_version: int = SCHEMA_VERSION

    def to_json(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "summary": self.summary,
            "key_points": self.key_points,
            "takeaways": self.takeaways,
            "topics": self.topics,
            "speaker_stats": self.speaker_stats,
            "action_items": self.action_items,
            "decisions": self.decisions,
        }

    @classmethod
    def from_json(cls, d: dict[str, Any]) -> "KeyPoints":
        if "key_points" in d and isinstance(d["key_points"], dict):
            d = d["key_points"]
        return cls(
            summary=d.get("summary", "") or "",
            key_points=d.get("key_points", []) if isinstance(d.get("key_points"), list) else [],
            takeaways=list(d.get("takeaways") or []),
            topics=list(d.get("topics") or []),
            speaker_stats=dict(d.get("speaker_stats") or {}),
            action_items=list(d.get("action_items") or []),
            decisions=list(d.get("decisions") or []),
            schema_version=int(d.get("schema_version") or SCHEMA_VERSION),
        )
