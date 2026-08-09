"""Export diary entries to Markdown, SRT, plain text, and JSON bundles."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from .history import (
    DEFAULT_DIARY_DIR,
    DiaryEntry,
    get_entry,
    load_transcript_data,
    load_analysis_data,
    format_transcript_text,
)
from .search import get_entry_segments


@dataclass
class ExportResult:
    entry_id: str
    out_dir: str
    files: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"entry_id": self.entry_id, "out_dir": self.out_dir, "files": self.files}


def _srt_timestamp(seconds: float) -> str:
    if seconds < 0:
        seconds = 0.0
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int(round((seconds - int(seconds)) * 1000))
    if ms >= 1000:
        s += 1
        ms = 0
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def segments_to_srt(segments: list[dict]) -> str:
    """Build WebVTT-adjacent SRT from segment dicts with start/end/text."""
    lines: list[str] = []
    n = 0
    for seg in segments:
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        try:
            start = float(seg.get("start", 0) or 0)
            end = float(seg.get("end", start + 1.0) or (start + 1.0))
        except (TypeError, ValueError):
            continue
        if end <= start:
            end = start + 0.5
        speaker = seg.get("speaker") or ""
        body = f"[{speaker}] {text}" if speaker else text
        n += 1
        lines.append(str(n))
        lines.append(f"{_srt_timestamp(start)} --> {_srt_timestamp(end)}")
        lines.append(body)
        lines.append("")
    return "\n".join(lines).rstrip() + ("\n" if lines else "")


def entry_to_markdown(
    entry: DiaryEntry,
    *,
    diary_dir: Path | None = None,
    include_analysis: bool = True,
) -> str:
    root = Path(diary_dir) if diary_dir else DEFAULT_DIARY_DIR
    data = load_transcript_data(entry)
    analysis = load_analysis_data(entry) if include_analysis else {}
    smap = {}
    try:
        from .speakers import get_entry_speaker_map, display_speakers_for_entry
        smap = get_entry_speaker_map(entry, root)
        speakers = display_speakers_for_entry(entry, diary_dir=root)
    except Exception:
        speakers = list(entry.speakers or [])

    tx = format_transcript_text(data, speaker_map=smap) if data else ""
    segs = get_entry_segments(entry.id, diary_dir=root)

    lines = [
        f"# Diary — {entry.id}",
        "",
        f"- **When:** {entry.created_at}",
        f"- **Duration:** {entry.duration_s:.0f}s" if entry.duration_s else "- **Duration:** —",
        f"- **Speakers:** {', '.join(speakers) or '—'}",
        f"- **Backend:** {entry.backend or '—'}",
        f"- **Audio:** `{entry.audio_path or '—'}`",
        "",
    ]
    if entry.title or entry.preview:
        lines += [f"> {entry.title or entry.preview}", ""]

    kp = {}
    if analysis:
        kp = analysis.get("key_points", analysis)
        if not isinstance(kp, dict):
            kp = {}

    if kp.get("summary"):
        lines += ["## Summary", "", kp["summary"], ""]

    if kp.get("decisions"):
        lines += ["## Decisions", ""]
        for d in kp["decisions"]:
            lines.append(f"- ✓ {d}")
        lines.append("")

    if kp.get("action_items"):
        lines += ["## Action items", ""]
        for a in kp["action_items"]:
            lines.append(f"- [ ] {a}")
        lines.append("")

    if kp.get("key_points"):
        lines += ["## Key points", ""]
        for i, p in enumerate(kp["key_points"], 1):
            lines.append(f"{i}. {p}")
        lines.append("")

    if kp.get("topics"):
        lines += ["## Topics", ""]
        for t in kp["topics"]:
            lines.append(f"- {t}")
        lines.append("")

    lines += ["## Transcript", ""]
    if segs:
        for s in segs:
            lines.append(
                f"**[{s['start']:.1f}s–{s['end']:.1f}s] {s['speaker']}:** {s['text']}"
            )
            lines.append("")
    elif tx:
        lines.append("```")
        lines.append(tx)
        lines.append("```")
        lines.append("")
    else:
        lines.append("_No transcript._")
        lines.append("")

    lines.append(f"_Exported {datetime.now().isoformat(timespec='seconds')}_")
    lines.append("")
    return "\n".join(lines)


def entry_to_plain_text(entry: DiaryEntry, *, diary_dir: Path | None = None) -> str:
    root = Path(diary_dir) if diary_dir else DEFAULT_DIARY_DIR
    data = load_transcript_data(entry)
    try:
        from .speakers import get_entry_speaker_map
        smap = get_entry_speaker_map(entry, root)
    except Exception:
        smap = {}
    header = f"Diary {entry.id}\n{entry.created_at}\n{'=' * 40}\n\n"
    body = format_transcript_text(data, speaker_map=smap) if data else "(no transcript)"
    return header + body + "\n"


def export_entry(
    entry_id: str,
    *,
    diary_dir: Path | None = None,
    out_dir: Path | None = None,
    formats: list[str] | None = None,
) -> ExportResult:
    """
    Export one entry to disk.

    formats: subset of md, srt, txt, json (default all).
    """
    root = Path(diary_dir) if diary_dir else DEFAULT_DIARY_DIR
    entry = get_entry(entry_id, root)
    if not entry:
        raise ValueError(f"Entry not found: {entry_id}")

    formats = [f.lower().lstrip(".") for f in (formats or ["md", "srt", "txt", "json"])]
    out = Path(out_dir) if out_dir else (root / "exports" / entry.id)
    out.mkdir(parents=True, exist_ok=True)

    written: list[str] = []
    segs = get_entry_segments(entry.id, diary_dir=root)
    data = load_transcript_data(entry)
    analysis = load_analysis_data(entry)

    if "md" in formats or "markdown" in formats:
        path = out / f"{entry.id}.md"
        path.write_text(entry_to_markdown(entry, diary_dir=root), encoding="utf-8")
        written.append(str(path))

    if "srt" in formats:
        path = out / f"{entry.id}.srt"
        path.write_text(segments_to_srt(segs), encoding="utf-8")
        written.append(str(path))

    if "txt" in formats or "text" in formats:
        path = out / f"{entry.id}.txt"
        path.write_text(entry_to_plain_text(entry, diary_dir=root), encoding="utf-8")
        written.append(str(path))

    if "json" in formats:
        path = out / f"{entry.id}.json"
        payload = {
            "entry": entry.to_dict(),
            "transcript": data,
            "analysis": analysis,
            "segments": segs,
            "exported_at": datetime.now().isoformat(timespec="seconds"),
        }
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        written.append(str(path))

    return ExportResult(entry_id=entry.id, out_dir=str(out), files=written)


def export_for_api(
    entry_id: str,
    formats: list[str] | None = None,
    out_dir: str | None = None,
    diary_dir: Path | None = None,
) -> dict[str, Any]:
    result = export_entry(
        entry_id,
        formats=formats,
        out_dir=Path(out_dir) if out_dir else None,
        diary_dir=diary_dir,
    )
    return result.to_dict()
