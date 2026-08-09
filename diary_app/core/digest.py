"""Daily / weekly digests over diary history."""
from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .history import (
    DEFAULT_DIARY_DIR,
    DiaryEntry,
    list_entries,
    load_analysis_data,
    load_transcript_data,
)


@dataclass
class DayDigest:
    date: str  # YYYY-MM-DD
    entry_ids: list[str] = field(default_factory=list)
    entry_count: int = 0
    total_duration_s: float = 0.0
    speakers: list[str] = field(default_factory=list)
    topics: list[str] = field(default_factory=list)
    action_items: list[str] = field(default_factory=list)
    decisions: list[str] = field(default_factory=list)
    key_points: list[str] = field(default_factory=list)
    summaries: list[str] = field(default_factory=list)
    titles: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _entry_date(entry: DiaryEntry) -> str:
    """Best-effort calendar date for grouping."""
    if entry.created_at:
        # ISO or "2026-07-09T..."
        s = entry.created_at[:10]
        if len(s) == 10 and s[4] == "-" and s[7] == "-":
            return s
    if entry.id and len(entry.id) >= 8 and entry.id[:8].isdigit():
        y, m, d = entry.id[:4], entry.id[4:6], entry.id[6:8]
        return f"{y}-{m}-{d}"
    if entry.created_ts:
        return datetime.fromtimestamp(entry.created_ts).strftime("%Y-%m-%d")
    return "unknown"


def _uniq(seq: list[str], limit: int = 20) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for x in seq:
        x = (x or "").strip()
        if not x:
            continue
        key = x.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(x)
        if len(out) >= limit:
            break
    return out


def build_day_digest(entries: list[DiaryEntry], date: str, diary_dir: Path) -> DayDigest:
    dig = DayDigest(date=date)
    speakers: list[str] = []
    topics: list[str] = []
    actions: list[str] = []
    decisions: list[str] = []
    kps: list[str] = []
    summaries: list[str] = []
    titles: list[str] = []

    for e in entries:
        dig.entry_ids.append(e.id)
        dig.total_duration_s += float(e.duration_s or 0)
        if e.title:
            titles.append(e.title)
        try:
            from .speakers import display_speakers_for_entry
            speakers.extend(display_speakers_for_entry(e, diary_dir=diary_dir))
        except Exception:
            speakers.extend(e.speakers or [])

        analysis = load_analysis_data(e)
        kp = analysis.get("key_points", analysis) if analysis else {}
        if not isinstance(kp, dict):
            kp = {}
        if kp.get("summary"):
            summaries.append(str(kp["summary"]))
        topics.extend(kp.get("topics") or [])
        actions.extend(kp.get("action_items") or [])
        decisions.extend(kp.get("decisions") or [])
        kps.extend(kp.get("key_points") or [])

    dig.entry_count = len(dig.entry_ids)
    dig.total_duration_s = round(dig.total_duration_s, 1)
    dig.speakers = _uniq(speakers)
    dig.topics = _uniq(topics, 15)
    dig.action_items = _uniq(actions, 30)
    dig.decisions = _uniq(decisions, 20)
    dig.key_points = _uniq(kps, 15)
    dig.summaries = summaries[:10]
    dig.titles = titles[:20]
    return dig


def digests_for_range(
    *,
    diary_dir: Path | None = None,
    start: str | None = None,
    end: str | None = None,
    days: int | None = 7,
) -> list[DayDigest]:
    """
    Build per-day digests.

    If start/end are ISO dates, use that range. Else last `days` calendar days
    that have entries (not empty days).
    """
    root = Path(diary_dir) if diary_dir else DEFAULT_DIARY_DIR
    entries = list_entries(root, limit=None)
    by_day: dict[str, list[DiaryEntry]] = defaultdict(list)
    for e in entries:
        by_day[_entry_date(e)].append(e)

    if start or end:
        # inclusive filter on date strings YYYY-MM-DD
        dates = sorted(d for d in by_day if d != "unknown")
        if start:
            dates = [d for d in dates if d >= start]
        if end:
            dates = [d for d in dates if d <= end]
    else:
        dates = sorted((d for d in by_day if d != "unknown"), reverse=True)
        if days is not None:
            dates = dates[: max(1, days)]
        dates = sorted(dates)

    return [build_day_digest(by_day[d], d, root) for d in dates if d in by_day]


def digest_to_markdown(digests: list[DayDigest], *, title: str = "Diary digest") -> str:
    lines = [
        f"# {title}",
        "",
        f"_Generated {datetime.now().isoformat(timespec='seconds')}_",
        "",
    ]
    if not digests:
        lines.append("_No entries in range._")
        lines.append("")
        return "\n".join(lines)

    total_entries = sum(d.entry_count for d in digests)
    total_dur = sum(d.total_duration_s for d in digests)
    lines += [
        f"**Days:** {len(digests)} · **Sessions:** {total_entries} · "
        f"**Audio time:** {total_dur / 60:.1f} min",
        "",
    ]

    # Roll-up actions/decisions across range
    all_actions: list[str] = []
    all_decisions: list[str] = []
    for d in digests:
        all_actions.extend(d.action_items)
        all_decisions.extend(d.decisions)
    all_actions = _uniq(all_actions, 40)
    all_decisions = _uniq(all_decisions, 30)

    if all_decisions:
        lines += ["## Decisions (range)", ""]
        for x in all_decisions:
            lines.append(f"- ✓ {x}")
        lines.append("")
    if all_actions:
        lines += ["## Action items (range)", ""]
        for x in all_actions:
            lines.append(f"- [ ] {x}")
        lines.append("")

    for d in reversed(digests):  # newest first in body optional — show chrono
        lines += [
            f"## {d.date}",
            "",
            f"- Sessions: **{d.entry_count}** (`{', '.join(d.entry_ids)}`)",
            f"- Duration: **{d.total_duration_s / 60:.1f} min**",
            f"- Speakers: {', '.join(d.speakers) or '—'}",
            f"- Topics: {', '.join(d.topics) or '—'}",
            "",
        ]
        if d.decisions:
            lines.append("### Decisions")
            for x in d.decisions:
                lines.append(f"- ✓ {x}")
            lines.append("")
        if d.action_items:
            lines.append("### Action items")
            for x in d.action_items:
                lines.append(f"- [ ] {x}")
            lines.append("")
        if d.key_points:
            lines.append("### Key points")
            for x in d.key_points[:8]:
                lines.append(f"- {x}")
            lines.append("")
        if d.summaries:
            lines.append("### Session summaries")
            for s in d.summaries:
                lines.append(f"- {s}")
            lines.append("")
    return "\n".join(lines)


def write_digest(
    *,
    diary_dir: Path | None = None,
    out_path: Path | None = None,
    days: int = 7,
    start: str | None = None,
    end: str | None = None,
    fmt: str = "md",
) -> Path:
    root = Path(diary_dir) if diary_dir else DEFAULT_DIARY_DIR
    digests = digests_for_range(diary_dir=root, start=start, end=end, days=days)
    exports = root / "exports"
    exports.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if out_path is None:
        out_path = exports / f"digest_{stamp}.{'json' if fmt == 'json' else 'md'}"
    else:
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)

    if fmt == "json":
        payload = {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "days": [d.to_dict() for d in digests],
        }
        out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    else:
        title = "Diary digest"
        if start or end:
            title = f"Diary digest ({start or '…'} → {end or '…'})"
        elif days:
            title = f"Diary digest (last {days} active days)"
        out_path.write_text(digest_to_markdown(digests, title=title), encoding="utf-8")
    return out_path


def digests_for_api(
    days: int = 7,
    start: str | None = None,
    end: str | None = None,
    diary_dir: Path | None = None,
) -> dict[str, Any]:
    digests = digests_for_range(days=days, start=start, end=end, diary_dir=diary_dir)
    return {
        "days": [d.to_dict() for d in digests],
        "markdown": digest_to_markdown(digests),
    }
