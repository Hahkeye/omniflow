"""Full-text search over diary history with segment-level hits for audio seek.

Performance: when SQLite FTS is available, only candidate entry ids are loaded
(no full history scan). Transcript/analysis JSON is opened only for candidates.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Any

from .history import (
    DiaryEntry,
    get_diary_dir,
    get_entry,
    get_entries_by_ids,
    list_entries,
    load_transcript_data,
    load_analysis_data,
)
from .logutil import get_logger

log = get_logger("search")


@dataclass
class SegmentHit:
    """One matching transcript segment (click → seek to start_time)."""
    entry_id: str
    segment_index: int
    speaker: str  # display name when available
    raw_speaker: str
    start: float
    end: float
    text: str
    snippet: str  # text with simple highlight markers
    score: float = 1.0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class SearchHit:
    """An entry that matched the query, with ranked segment hits."""
    entry_id: str
    created_at: str
    title: str
    preview: str
    audio_path: str | None
    has_audio: bool
    has_transcript: bool
    speakers: list[str] = field(default_factory=list)
    score: float = 0.0
    match_fields: list[str] = field(default_factory=list)
    segments: list[SegmentHit] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["segments"] = [s.to_dict() if isinstance(s, SegmentHit) else s for s in self.segments]
        return d


def _tokenize_query(query: str) -> list[str]:
    """Split query into search terms; keep quoted phrases intact."""
    query = (query or "").strip()
    if not query:
        return []
    phrases = re.findall(r'"([^"]+)"', query)
    rest = re.sub(r'"[^"]+"', " ", query)
    terms = [t.lower() for t in re.findall(r"\w+", rest) if len(t) > 1]
    terms.extend(p.lower() for p in phrases if p.strip())
    seen = set()
    out = []
    for t in terms:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


def _highlight(text: str, terms: list[str], max_len: int = 160) -> str:
    """Return a short snippet with **term** markers around first match."""
    if not text:
        return ""
    lower = text.lower()
    pos = -1
    matched = None
    for t in terms:
        i = lower.find(t)
        if i >= 0 and (pos < 0 or i < pos):
            pos = i
            matched = t
    if pos < 0:
        snippet = text[:max_len] + ("…" if len(text) > max_len else "")
        return snippet

    start = max(0, pos - 40)
    end = min(len(text), pos + len(matched) + 80)
    chunk = text[start:end]
    for t in sorted(terms, key=len, reverse=True):
        chunk = re.sub(
            f"({re.escape(t)})",
            r"**\1**",
            chunk,
            flags=re.IGNORECASE,
        )
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(text) else ""
    return prefix + chunk + suffix


def _score_text(text: str, terms: list[str]) -> float:
    if not text or not terms:
        return 0.0
    lower = text.lower()
    score = 0.0
    for t in terms:
        count = lower.count(t)
        if count:
            score += 1.0 + 0.25 * (count - 1)
            if lower.startswith(t) or f" {t}" in lower[:40]:
                score += 0.15
    if all(t in lower for t in terms):
        score += 0.5 * len(terms)
    return score


def _segments_from_data(data: dict) -> list[dict]:
    if "transcript" in data and isinstance(data["transcript"], dict):
        segs = data["transcript"].get("segments", [])
    else:
        segs = data.get("segments", [])
    return segs if isinstance(segs, list) else []


def _display_map_for_entry(entry: DiaryEntry, diary_dir: Path) -> dict[str, str]:
    try:
        from .speakers import get_entry_speaker_map, resolve_display_map, raw_labels_from_transcript_data

        data = load_transcript_data(entry)
        raw = raw_labels_from_transcript_data(data) if data else (entry.speakers or [])
        smap = get_entry_speaker_map(entry, diary_dir)
        return resolve_display_map(raw, entry_map=smap)
    except Exception:
        return {}


def _person_matches(entry: DiaryEntry, person: str, root: Path) -> bool:
    if not person:
        return True
    try:
        from .speakers import filter_entries_by_person

        # reuse single-entry check via display names / map
        hits = filter_entries_by_person(person, diary_dir=root, limit=None)
        return any(h.id == entry.id for h in hits)
    except Exception:
        p = person.lower()
        names = " ".join(entry.speakers or []).lower()
        return p in names or p in (entry.preview or "").lower()


def _score_entry(
    entry: DiaryEntry,
    terms: list[str],
    root: Path,
    *,
    person: str | None,
    max_segments_per_entry: int,
) -> SearchHit | None:
    match_fields: list[str] = []
    entry_score = 0.0
    segment_hits: list[SegmentHit] = []

    dmap = _display_map_for_entry(entry, root)
    try:
        from .speakers import display_speakers_for_entry

        speakers_display = display_speakers_for_entry(entry, diary_dir=root)
    except Exception:
        speakers_display = list(entry.speakers or [])

    if person:
        match_fields.append("person")

    if terms:
        title_score = _score_text(entry.title or "", terms) * 1.5
        preview_score = _score_text(entry.preview or "", terms) * 0.8
        if title_score:
            entry_score += title_score
            match_fields.append("title")
        if preview_score:
            entry_score += preview_score
            match_fields.append("preview")

        analysis = load_analysis_data(entry)
        if analysis:
            kp = analysis.get("key_points", analysis)
            if isinstance(kp, dict):
                blob = " ".join(
                    [
                        str(kp.get("summary") or ""),
                        " ".join(kp.get("key_points") or []),
                        " ".join(kp.get("topics") or []),
                        " ".join(kp.get("takeaways") or []),
                        " ".join(kp.get("action_items") or []),
                        " ".join(kp.get("decisions") or []),
                    ]
                )
                a_score = _score_text(blob, terms) * 1.1
                if a_score:
                    entry_score += a_score
                    match_fields.append("analysis")

        data = load_transcript_data(entry)
        segs = _segments_from_data(data)
        try:
            from .speakers import normalize_label
        except Exception:
            def normalize_label(x):  # type: ignore
                return x

        for idx, seg in enumerate(segs):
            if not isinstance(seg, dict):
                continue
            text = (seg.get("text") or "").strip()
            if not text:
                continue
            raw_sp = str(seg.get("speaker") or "?")
            display_sp = (
                dmap.get(raw_sp) or dmap.get(normalize_label(raw_sp)) or raw_sp
            )
            blob = f"{display_sp} {text}"
            s_score = _score_text(blob, terms)
            if s_score <= 0:
                continue
            try:
                start = float(seg.get("start", seg.get("start_time", 0)) or 0)
                end = float(seg.get("end", seg.get("end_time", start)) or start)
            except (TypeError, ValueError):
                start, end = 0.0, 0.0
            segment_hits.append(
                SegmentHit(
                    entry_id=entry.id,
                    segment_index=idx,
                    speaker=display_sp,
                    raw_speaker=raw_sp,
                    start=start,
                    end=end,
                    text=text,
                    snippet=_highlight(text, terms),
                    score=s_score,
                )
            )
            entry_score += s_score

        if segment_hits:
            match_fields.append("transcript")
            segment_hits.sort(key=lambda h: h.score, reverse=True)
            segment_hits = segment_hits[:max_segments_per_entry]
            segment_hits.sort(key=lambda h: h.start)

    if not terms and person:
        entry_score = max(entry_score, 0.5)

    if entry_score <= 0 and terms:
        return None
    if not terms and not person:
        return None

    entry_score += min(0.5, (entry.created_ts or 0) / 1e12)

    return SearchHit(
        entry_id=entry.id,
        created_at=entry.created_at,
        title=entry.title,
        preview=entry.preview,
        audio_path=entry.audio_path if entry.has_audio else None,
        has_audio=entry.has_audio,
        has_transcript=entry.has_transcript,
        speakers=speakers_display,
        score=round(entry_score, 3),
        match_fields=sorted(set(match_fields)),
        segments=segment_hits,
    )


def search_diary(
    query: str,
    *,
    diary_dir: Path | None = None,
    person: str | None = None,
    limit: int = 50,
    max_segments_per_entry: int = 8,
) -> list[SearchHit]:
    """
    Search transcript text, titles, and analysis across history.

    When FTS index exists and query has terms: only candidate ids are loaded.
    When FTS empty (no matches): returns [] without scanning the library.
    When no index: falls back to scanning list_entries (legacy).
    """
    root = Path(diary_dir) if diary_dir else get_diary_dir()
    terms = _tokenize_query(query)
    person = (person or "").strip() or None
    if not terms and not person:
        return []

    entries: list[DiaryEntry] = []
    used_fts = False

    if terms:
        try:
            from .index_db import search_ids, db_path

            if db_path(root).exists():
                fts_ids = search_ids(root, " ".join(terms), limit=max(limit * 4, 50))
                used_fts = True
                if not fts_ids:
                    # Index says no matches — don't full-scan
                    log.debug("search: FTS empty for %r", query)
                    if person:
                        # person-only refinement with empty FTS: nothing to refine
                        return []
                    return []
                by_id = get_entries_by_ids(fts_ids, root)
                entries = [by_id[i] for i in fts_ids if i in by_id]
                log.debug("search: FTS candidates=%d loaded=%d", len(fts_ids), len(entries))
        except Exception as e:
            log.debug("search FTS unavailable: %s", e)
            used_fts = False
            entries = []

    if not used_fts:
        # No index or FTS failed — legacy full list (person filter optional)
        if person:
            try:
                from .speakers import filter_entries_by_person

                entries = filter_entries_by_person(person, diary_dir=root, limit=None)
            except Exception:
                entries = list_entries(root, limit=None)
        else:
            entries = list_entries(root, limit=None)
    elif person:
        entries = [e for e in entries if _person_matches(e, person, root)]

    if not terms and person:
        # Person-only search: filter list (bounded by list_entries hot path)
        try:
            from .speakers import filter_entries_by_person

            entries = filter_entries_by_person(person, diary_dir=root, limit=limit)
        except Exception:
            entries = [e for e in list_entries(root, limit=None) if _person_matches(e, person, root)]

    hits: list[SearchHit] = []
    for entry in entries:
        if not entry.has_transcript and not terms:
            if person:
                hits.append(
                    SearchHit(
                        entry_id=entry.id,
                        created_at=entry.created_at,
                        title=entry.title,
                        preview=entry.preview,
                        audio_path=entry.audio_path if entry.has_audio else None,
                        has_audio=entry.has_audio,
                        has_transcript=entry.has_transcript,
                        speakers=list(entry.speakers or []),
                        score=0.1,
                        match_fields=["person"],
                        segments=[],
                    )
                )
            continue

        hit = _score_entry(
            entry,
            terms,
            root,
            person=person,
            max_segments_per_entry=max_segments_per_entry,
        )
        if hit:
            hits.append(hit)

    hits.sort(key=lambda h: h.score, reverse=True)
    return hits[:limit]


def get_entry_segments(
    entry_id: str,
    *,
    diary_dir: Path | None = None,
) -> list[dict[str, Any]]:
    """All segments for an entry with display names + times (for click-to-seek UI)."""
    root = Path(diary_dir) if diary_dir else get_diary_dir()
    entry = get_entry(entry_id, root)
    if not entry:
        return []
    data = load_transcript_data(entry)
    segs = _segments_from_data(data)
    dmap = _display_map_for_entry(entry, root)
    try:
        from .speakers import normalize_label
    except Exception:
        def normalize_label(x):  # type: ignore
            return x

    out = []
    for idx, seg in enumerate(segs):
        if not isinstance(seg, dict):
            continue
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        raw_sp = str(seg.get("speaker") or "?")
        display_sp = dmap.get(raw_sp) or dmap.get(normalize_label(raw_sp)) or raw_sp
        try:
            start = float(seg.get("start", seg.get("start_time", 0)) or 0)
            end = float(seg.get("end", seg.get("end_time", start)) or start)
        except (TypeError, ValueError):
            start, end = 0.0, 0.0
        out.append({
            "segment_index": idx,
            "speaker": display_sp,
            "raw_speaker": raw_sp,
            "start": start,
            "end": end,
            "text": text,
        })
    return out


def search_for_api(
    query: str,
    *,
    person: str | None = None,
    limit: int = 50,
    diary_dir: Path | None = None,
) -> list[dict]:
    return [
        h.to_dict()
        for h in search_diary(query, person=person, limit=limit, diary_dir=diary_dir)
    ]
