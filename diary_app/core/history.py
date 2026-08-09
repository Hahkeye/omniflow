"""Diary history: list, load, and link past recordings + transcripts + analysis."""
from __future__ import annotations

import json
import re
import secrets
import wave
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from .logutil import get_logger

log = get_logger("history")


def get_diary_dir() -> Path:
    """Single source of truth for diary root (delegates to AppConfig)."""
    try:
        from diary_app.config import get_diary_dir as _cfg_dir

        return _cfg_dir()
    except Exception:
        return Path.home() / "diary"


def _default_diary_dir() -> Path:
    return get_diary_dir()


# Back-compat: many modules import DEFAULT_DIARY_DIR as a Path.
# Prefer get_diary_dir() for new code — this value is refreshed at process start.
DEFAULT_DIARY_DIR = Path.home() / "diary"
SCHEMA_VERSION = 2

# In-process cache for list_entries (invalidated on writes)
_index_cache: dict = {"key": None, "entries": None, "built_at": 0.0}


def invalidate_index_cache() -> None:
    """Drop cached history listing (call after any entry write)."""
    _index_cache["key"] = None
    _index_cache["entries"] = None
    _index_cache["built_at"] = 0.0


def new_entry_id(when: datetime | None = None) -> str:
    """Unique entry id: YYYYMMDD_HHMMSS_<6 hex> (collision-safe)."""
    dt = when or datetime.now()
    return f"{dt.strftime('%Y%m%d_%H%M%S')}_{secrets.token_hex(3)}"


# Files that change without meaning "history content changed" (must not bust SQLite freshness)
_FP_IGNORE_NAMES = frozenset({
    "index.sqlite",
    "index.sqlite-wal",
    "index.sqlite-shm",
    "index.sqlite-journal",
    "daemon.json",
    "daemon.log",
    ".key",
    "actions.json",  # inbox mutations shouldn't force full re-scan of transcripts
})


def _index_fingerprint(root: Path) -> str:
    """Cheap fingerprint of diary *content* for cache / SQLite freshness.

    Ignores index.sqlite, daemon state, and similar side-car files so that
    writing the SQLite index does not immediately invalidate itself.
    """
    parts: list[str] = []
    try:
        for sub in (root / "entries", root / "tmp"):
            if not sub.exists():
                continue
            try:
                names = sorted(
                    p.name for p in sub.iterdir() if p.name not in _FP_IGNORE_NAMES
                )
                mtimes = []
                for name in names[:200]:
                    try:
                        mtimes.append(str((sub / name).stat().st_mtime_ns))
                    except OSError:
                        pass
                parts.append(f"{sub.name}:{len(names)}:{':'.join(mtimes[:50])}")
            except Exception:
                pass
        # Loose transcript/analysis/recording at diary root (not side-cars)
        if root.exists():
            loose = []
            for p in root.iterdir():
                if not p.is_file():
                    continue
                if p.name in _FP_IGNORE_NAMES:
                    continue
                if p.name.startswith(("transcript_", "analysis_", "recording_", "entry_")):
                    try:
                        loose.append(f"{p.name}:{p.stat().st_mtime_ns}")
                    except OSError:
                        pass
            loose.sort()
            parts.append(f"loose:{len(loose)}:{':'.join(loose[:80])}")
        sp = root / "speakers.json"
        if sp.exists():
            parts.append(f"spk:{sp.stat().st_mtime_ns}")
    except Exception:
        parts.append("err")
    return "|".join(parts)

# recording_2026-07-09_181713.wav  OR  recording_20260709_181713.wav
_AUDIO_TS = re.compile(
    r"recording_(\d{4})-?(\d{2})-?(\d{2})[_T]?(\d{2})(\d{2})(\d{2})",
    re.IGNORECASE,
)
# transcript_20260709_181713.json / analysis_...
_JSON_TS = re.compile(
    r"(?:transcript|analysis)_(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})",
    re.IGNORECASE,
)


@dataclass
class DiaryEntry:
    """One diary session: optional audio + transcript + analysis."""
    id: str
    created_at: str  # ISO-ish display
    created_ts: float  # for sorting
    audio_path: str | None = None
    transcript_path: str | None = None
    analysis_path: str | None = None
    preview: str = ""
    speakers: list[str] = field(default_factory=list)
    segment_count: int = 0
    duration_s: float = 0.0
    audio_size_mb: float = 0.0
    backend: str | None = None
    title: str = ""
    # raw label → display name for this entry (e.g. "Speaker 1" → "Alex")
    speaker_map: dict = field(default_factory=dict)
    # User organization
    tags: list[str] = field(default_factory=list)
    notes: str = ""
    starred: bool = False
    archived: bool = False
    schema_version: int = SCHEMA_VERSION

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def has_audio(self) -> bool:
        return bool(self.audio_path and Path(self.audio_path).exists())

    @property
    def has_transcript(self) -> bool:
        return bool(self.transcript_path and Path(self.transcript_path).exists())


def diary_dirs(root: Path | None = None) -> list[Path]:
    """Search roots: diary_dir and diary_dir/tmp."""
    root = Path(root) if root else _default_diary_dir()
    dirs = [root, root / "tmp"]
    return [d for d in dirs if d.exists()]


def _parse_ts_from_name(name: str) -> datetime | None:
    m = _AUDIO_TS.search(name) or _JSON_TS.search(name)
    if not m:
        return None
    y, mo, d, h, mi, s = (int(x) for x in m.groups())
    try:
        return datetime(y, mo, d, h, mi, s)
    except ValueError:
        return None


def _entry_id_from_dt(dt: datetime, suffix: str = "") -> str:
    base = dt.strftime("%Y%m%d_%H%M%S")
    return f"{base}{suffix}"


def _wav_duration(path: Path) -> float:
    try:
        with wave.open(str(path), "rb") as wf:
            rate = wf.getframerate() or 1
            return wf.getnframes() / float(rate)
    except Exception:
        try:
            return path.stat().st_size / (16000 * 2)  # rough 16k mono int16
        except Exception:
            return 0.0


def _load_json(path: Path) -> dict:
    try:
        from .crypto import read_json

        return read_json(path)
    except Exception as e:
        log.debug("crypto read_json failed for %s: %s; trying plain", path, e)
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception as e2:
            log.warning("Failed to load JSON %s: %s", path, e2)
            return {}


def _write_json(path: Path, data: dict) -> None:
    try:
        from .crypto import write_json

        write_json(path, data)
    except Exception as e:
        log.warning("crypto write_json failed for %s: %s; writing plain", path, e)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _transcript_preview(data: dict, max_chars: int = 160) -> tuple[str, list[str], int, float]:
    """Return preview, speakers, segment_count, duration from transcript JSON."""
    # Normalize shape
    if "transcript" in data and isinstance(data["transcript"], dict):
        segs = data["transcript"].get("segments", [])
    else:
        segs = data.get("segments", [])
    if not isinstance(segs, list):
        segs = []

    speakers: list[str] = []
    texts: list[str] = []
    t0, t1 = None, None
    for seg in segs:
        if not isinstance(seg, dict):
            continue
        sp = seg.get("speaker")
        if sp and sp not in speakers:
            speakers.append(sp)
        text = (seg.get("text") or "").strip()
        if text:
            texts.append(text)
        start = seg.get("start", seg.get("start_time"))
        end = seg.get("end", seg.get("end_time"))
        try:
            if start is not None:
                sf = float(start)
                t0 = sf if t0 is None else min(t0, sf)
            if end is not None:
                ef = float(end)
                t1 = ef if t1 is None else max(t1, ef)
        except (TypeError, ValueError):
            pass

    preview = " ".join(texts).strip()
    if len(preview) > max_chars:
        preview = preview[: max_chars - 1].rstrip() + "…"
    duration = (t1 - t0) if t0 is not None and t1 is not None else 0.0
    return preview, speakers, len(segs), duration


def _meta_from_payload(data: dict) -> dict:
    meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
    return meta or {}


def save_entry_bundle(
    transcript: Any,
    key_points: Any | None = None,
    *,
    audio_path: Path | str | None = None,
    diary_dir: Path | None = None,
    backend: str | None = None,
    device: str | None = None,
    entry_id: str | None = None,
) -> DiaryEntry:
    """
    Persist a linked history entry (transcript + optional analysis + audio ref).

    Writes:
      ~/diary/entries/<id>.json   (canonical linked record)
      ~/diary/transcript_<id>.json
      ~/diary/analysis_<id>.json  (if key_points provided)
    """
    diary_dir = Path(diary_dir) if diary_dir else DEFAULT_DIARY_DIR
    diary_dir.mkdir(parents=True, exist_ok=True)
    entries_dir = diary_dir / "entries"
    entries_dir.mkdir(parents=True, exist_ok=True)

    now = datetime.now()
    eid = entry_id or new_entry_id(now)
    created_at = now.isoformat(timespec="seconds")

    # Transcript payload
    if hasattr(transcript, "to_json"):
        t_json = transcript.to_json()
    elif isinstance(transcript, dict):
        t_json = transcript
    else:
        raise TypeError("transcript must be Transcript or dict")

    kp_json = None
    if key_points is not None:
        if hasattr(key_points, "to_json"):
            kp_json = key_points.to_json()
        elif isinstance(key_points, dict):
            kp_json = key_points

    audio_str = str(Path(audio_path).resolve()) if audio_path else None
    if audio_str and not Path(audio_str).exists():
        # keep path even if missing later
        pass

    # Suggest speaker names from remembered defaults (cross-session memory)
    speaker_map: dict[str, str] = {}
    try:
        from .speakers import SpeakerStore

        store = SpeakerStore.load(diary_dir)
        raw_labels = []
        segs = t_json.get("segments") if isinstance(t_json, dict) else None
        if isinstance(segs, list):
            for seg in segs:
                if isinstance(seg, dict) and seg.get("speaker"):
                    sp = str(seg["speaker"])
                    if sp not in raw_labels:
                        raw_labels.append(sp)
        speaker_map = store.suggested_map(raw_labels)
    except Exception:
        speaker_map = {}

    meta = {
        "id": eid,
        "created_at": created_at,
        "audio_path": audio_str,
        "backend": backend,
        "device": device,
        "speaker_map": speaker_map,
    }

    transcript_path = diary_dir / f"transcript_{eid}.json"
    transcript_doc: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "meta": meta,
        "transcript": t_json,
    }

    analysis_path = None
    # Preserve raw model text / warnings on transcript payload
    if hasattr(transcript, "raw_text") and transcript.raw_text:
        transcript_doc["raw_text"] = transcript.raw_text
        meta["raw_text"] = transcript.raw_text
    if hasattr(transcript, "warnings") and transcript.warnings:
        transcript_doc["warnings"] = list(transcript.warnings)
        meta["warnings"] = list(transcript.warnings)
    transcript_doc["meta"] = meta
    _write_json(transcript_path, transcript_doc)

    if kp_json is not None:
        analysis_path = diary_dir / f"analysis_{eid}.json"
        _write_json(
            analysis_path,
            {"schema_version": SCHEMA_VERSION, "meta": meta, "key_points": kp_json},
        )

    entry_path = entries_dir / f"{eid}.json"
    # Preserve existing tags/notes/star if re-saving same id
    prev_tags: list[str] = []
    prev_notes = ""
    prev_starred = False
    prev_archived = False
    if entry_path.exists():
        prev = _load_json(entry_path)
        prev_tags = list(prev.get("tags") or [])
        prev_notes = prev.get("notes") or ""
        prev_starred = bool(prev.get("starred"))
        prev_archived = bool(prev.get("archived"))

    preview, speakers, nseg, dur = _transcript_preview(transcript_doc)
    if not preview and hasattr(transcript, "raw_text") and transcript.raw_text:
        preview = str(transcript.raw_text)[:160]
    # Prefer display names when we have a map
    if speaker_map:
        try:
            from .speakers import resolve_display_map
            dmap = resolve_display_map(speakers, entry_map=speaker_map)
            speakers = [dmap.get(s, s) for s in speakers]
        except Exception:
            pass
    audio_size = 0.0
    if audio_str and Path(audio_str).exists():
        audio_size = Path(audio_str).stat().st_size / (1024 * 1024)
        if dur <= 0:
            dur = _wav_duration(Path(audio_str))

    title = preview[:60] + ("…" if len(preview) > 60 else "") if preview else f"Entry {eid}"
    entry = DiaryEntry(
        id=eid,
        created_at=created_at,
        created_ts=now.timestamp(),
        audio_path=audio_str,
        transcript_path=str(transcript_path),
        analysis_path=str(analysis_path) if analysis_path else None,
        preview=preview,
        speakers=speakers,
        segment_count=nseg,
        duration_s=round(dur, 1),
        audio_size_mb=round(audio_size, 2),
        backend=backend,
        title=title or f"Entry {eid}",
        speaker_map=speaker_map,
        tags=prev_tags,
        notes=prev_notes,
        starred=prev_starred,
        archived=prev_archived,
        schema_version=SCHEMA_VERSION,
    )
    _write_json(entry_path, entry.to_dict())
    invalidate_index_cache()
    try:
        from .index_db import upsert_entry

        body = preview or ""
        if kp_json:
            body += "\n" + " ".join(
                str(x)
                for x in (
                    [kp_json.get("summary") or ""]
                    + list(kp_json.get("key_points") or [])
                    + list(kp_json.get("topics") or [])
                    + list(kp_json.get("action_items") or [])
                    + list(kp_json.get("decisions") or [])
                )
                if x
            )
        segs = t_json.get("segments") if isinstance(t_json, dict) else None
        if isinstance(segs, list):
            body += "\n" + " ".join(
                str(s.get("text") or "") for s in segs if isinstance(s, dict)
            )
        upsert_entry(diary_dir, entry, body=body, archived=prev_archived)
    except Exception as e:
        log.debug("index upsert skipped: %s", e)
    return entry


def _scan_legacy_files(root: Path | None = None) -> list[DiaryEntry]:
    """Build entries from loose recording/transcript/analysis files (pre-history)."""
    by_id: dict[str, DiaryEntry] = {}

    def ensure(eid: str, dt: datetime | None, mtime: float) -> DiaryEntry:
        if eid not in by_id:
            created = dt.isoformat(timespec="seconds") if dt else datetime.fromtimestamp(mtime).isoformat(timespec="seconds")
            by_id[eid] = DiaryEntry(
                id=eid,
                created_at=created,
                created_ts=dt.timestamp() if dt else mtime,
                title=f"Entry {eid}",
            )
        return by_id[eid]

    for d in diary_dirs(root):
        for path in d.iterdir():
            if not path.is_file():
                continue
            name = path.name
            mtime = path.stat().st_mtime
            dt = _parse_ts_from_name(name)

            if name.startswith("recording_") and name.lower().endswith((".wav", ".mp3", ".flac", ".m4a", ".ogg")):
                eid = _entry_id_from_dt(dt, "") if dt else f"audio_{int(mtime)}"
                # normalize id without dashes
                if dt:
                    eid = dt.strftime("%Y%m%d_%H%M%S")
                e = ensure(eid, dt, mtime)
                e.audio_path = str(path.resolve())
                e.audio_size_mb = round(path.stat().st_size / (1024 * 1024), 2)
                if e.duration_s <= 0:
                    e.duration_s = round(_wav_duration(path), 1)
                if not e.title or e.title.startswith("Entry "):
                    e.title = path.stem

            elif name.startswith("transcript_") and name.endswith(".json"):
                eid = dt.strftime("%Y%m%d_%H%M%S") if dt else f"tx_{int(mtime)}"
                e = ensure(eid, dt, mtime)
                e.transcript_path = str(path.resolve())
                data = _load_json(path)
                meta = _meta_from_payload(data)
                if meta.get("audio_path") and not e.audio_path:
                    ap = Path(meta["audio_path"])
                    if ap.exists():
                        e.audio_path = str(ap.resolve())
                if meta.get("backend"):
                    e.backend = meta["backend"]
                preview, speakers, nseg, dur = _transcript_preview(data)
                e.preview = preview or e.preview
                e.speakers = speakers or e.speakers
                e.segment_count = nseg or e.segment_count
                if dur:
                    e.duration_s = round(dur, 1)
                if preview:
                    e.title = preview[:60] + ("…" if len(preview) > 60 else "")

            elif name.startswith("analysis_") and name.endswith(".json"):
                eid = dt.strftime("%Y%m%d_%H%M%S") if dt else f"an_{int(mtime)}"
                e = ensure(eid, dt, mtime)
                e.analysis_path = str(path.resolve())

    return list(by_id.values())


def _entry_from_dict(data: dict, fallback_id: str = "", mtime: float = 0.0) -> DiaryEntry:
    """Build DiaryEntry from a JSON dict, filling defaults for missing keys."""
    fields = {name: data.get(name) for name in DiaryEntry.__dataclass_fields__}
    fields["id"] = fields.get("id") or fallback_id or "unknown"
    fields["created_at"] = fields.get("created_at") or ""
    fields["created_ts"] = float(fields.get("created_ts") or mtime or 0.0)
    fields["preview"] = fields.get("preview") or ""
    fields["speakers"] = fields.get("speakers") or []
    fields["segment_count"] = int(fields.get("segment_count") or 0)
    fields["duration_s"] = float(fields.get("duration_s") or 0.0)
    fields["audio_size_mb"] = float(fields.get("audio_size_mb") or 0.0)
    fields["title"] = fields.get("title") or fields["id"]
    fields["audio_path"] = fields.get("audio_path")
    fields["transcript_path"] = fields.get("transcript_path")
    fields["analysis_path"] = fields.get("analysis_path")
    fields["backend"] = fields.get("backend")
    fields["speaker_map"] = fields.get("speaker_map") or {}
    fields["tags"] = list(fields.get("tags") or [])
    fields["notes"] = fields.get("notes") or ""
    fields["starred"] = bool(fields.get("starred"))
    fields["archived"] = bool(fields.get("archived"))
    fields["schema_version"] = int(fields.get("schema_version") or SCHEMA_VERSION)
    return DiaryEntry(**fields)


def _load_canonical_entries(root: Path | None = None) -> list[DiaryEntry]:
    root = Path(root) if root else DEFAULT_DIARY_DIR
    entries_dir = root / "entries"
    if not entries_dir.exists():
        return []
    out: list[DiaryEntry] = []
    for path in entries_dir.glob("*.json"):
        data = _load_json(path)
        out.append(_entry_from_dict(data, fallback_id=path.stem, mtime=path.stat().st_mtime))
    return out


def list_entries(
    root: Path | None = None,
    *,
    limit: int | None = None,
    require_transcript: bool = False,
    require_audio: bool = False,
    use_cache: bool = True,
    include_archived: bool = False,
    force_scan: bool = False,
) -> list[DiaryEntry]:
    """
    List history newest-first.

    Hot path: when SQLite index is fresh (tree fingerprint matches), read only
    from index.sqlite — no directory walk. On miss/stale index, full-scan
    filesystem only (read-only). Run `diary_app reindex` to rebuild SQLite.

    force_scan=True always walks the filesystem (used by rebuild_index).
    """
    root = Path(root) if root else _default_diary_dir()
    fp = _index_fingerprint(root)

    # In-process cache (same process, unchanged tree)
    if (
        use_cache
        and not force_scan
        and _index_cache.get("key") == fp
        and _index_cache.get("entries") is not None
    ):
        entries = list(_index_cache["entries"])
    else:
        entries = None
        # SQLite-first hot path
        if not force_scan:
            try:
                from .index_db import is_index_fresh, list_entries_from_db

                if is_index_fresh(root, fp):
                    rows = list_entries_from_db(
                        root, include_archived=True, limit=None
                    )
                    if rows is not None:
                        entries = [
                            _entry_from_dict(r, fallback_id=r.get("id") or "")
                            for r in rows
                        ]
                        log.debug("list_entries: SQLite hit (%d rows)", len(entries))
            except Exception as e:
                log.debug("list_entries SQLite path failed: %s", e)
                entries = None

        if entries is None:
            by_id: dict[str, DiaryEntry] = {}

            for e in _load_canonical_entries(root):
                by_id[e.id] = e

            for e in _scan_legacy_files(root):
                if e.id in by_id:
                    cur = by_id[e.id]
                    if not cur.audio_path and e.audio_path:
                        cur.audio_path = e.audio_path
                    if not cur.transcript_path and e.transcript_path:
                        cur.transcript_path = e.transcript_path
                    if not cur.analysis_path and e.analysis_path:
                        cur.analysis_path = e.analysis_path
                    if not cur.preview and e.preview:
                        cur.preview = e.preview
                    if not cur.speakers and e.speakers:
                        cur.speakers = e.speakers
                    if not cur.segment_count and e.segment_count:
                        cur.segment_count = e.segment_count
                    if cur.duration_s <= 0 and e.duration_s:
                        cur.duration_s = e.duration_s
                    if not cur.title or cur.title.startswith("Entry "):
                        cur.title = e.title or cur.title
                    if not cur.tags and e.tags:
                        cur.tags = list(e.tags)
                    if not cur.notes and e.notes:
                        cur.notes = e.notes
                    if e.starred:
                        cur.starred = True
                else:
                    by_id[e.id] = e

            entries = list(by_id.values())
            entries.sort(key=lambda e: e.created_ts, reverse=True)
            log.debug(
                "list_entries: filesystem scan (%d rows) — run `diary_app reindex` for SQLite hot path",
                len(entries),
            )
            # Intentionally do NOT rewrite the whole SQLite index here.
            # List must stay read-only; use rebuild_index / save_entry_bundle for writes.

        if use_cache:
            _index_cache["key"] = fp
            _index_cache["entries"] = list(entries)
            import time as _time

            _index_cache["built_at"] = _time.time()

    if not include_archived:
        entries = [e for e in entries if not getattr(e, "archived", False)]
    if require_transcript:
        entries = [e for e in entries if e.has_transcript]
    if require_audio:
        entries = [e for e in entries if e.has_audio]

    if limit is not None:
        entries = entries[:limit]
    return entries


def archive_entry(
    entry_id: str,
    *,
    diary_dir: Path | None = None,
    unarchive: bool = False,
) -> DiaryEntry:
    """Mark entry archived (hidden from default lists) or restore it."""
    root = Path(diary_dir) if diary_dir else DEFAULT_DIARY_DIR
    entry = get_entry(entry_id, root)
    if not entry:
        raise ValueError(f"Entry not found: {entry_id}")
    path = root / "entries" / f"{entry.id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    data = _load_json(path) if path.exists() else entry.to_dict()
    for k, v in entry.to_dict().items():
        data.setdefault(k, v)
    data["archived"] = not unarchive
    data["id"] = entry.id
    _write_json(path, data)
    invalidate_index_cache()
    updated = _entry_from_dict(data, fallback_id=entry.id)
    try:
        from .index_db import upsert_entry

        # Pass archived explicitly so unarchive is not blocked by stale SQLite row
        upsert_entry(root, updated, archived=bool(data["archived"]))
    except Exception as e:
        log.debug("index update on archive failed: %s", e)
    return updated


def delete_entry(
    entry_id: str,
    *,
    diary_dir: Path | None = None,
    delete_audio: bool = False,
) -> dict[str, Any]:
    """
    Permanently delete entry index + linked transcript/analysis.
    Optionally delete audio file if it lives under the diary dir.
    """
    root = Path(diary_dir) if diary_dir else DEFAULT_DIARY_DIR
    entry = get_entry(entry_id, root)
    if not entry:
        raise ValueError(f"Entry not found: {entry_id}")

    removed: list[str] = []
    for p in (
        root / "entries" / f"{entry.id}.json",
        Path(entry.transcript_path) if entry.transcript_path else None,
        Path(entry.analysis_path) if entry.analysis_path else None,
    ):
        if p and p.exists():
            p.unlink()
            removed.append(str(p))

    # Loose files with matching id prefix
    for pattern in (f"transcript_{entry.id}*.json", f"analysis_{entry.id}*.json"):
        for p in root.glob(pattern):
            if p.exists():
                p.unlink()
                removed.append(str(p))

    if delete_audio and entry.audio_path:
        ap = Path(entry.audio_path)
        try:
            if ap.exists() and root.resolve() in ap.resolve().parents:
                ap.unlink()
                removed.append(str(ap))
        except OSError as e:
            log.warning("Could not delete audio %s: %s", ap, e)

    invalidate_index_cache()
    try:
        from .index_db import remove_entry

        remove_entry(root, entry.id)
    except Exception as e:
        log.debug("index remove failed: %s", e)

    return {"id": entry.id, "removed": removed}


def get_entries_by_ids(
    entry_ids: list[str],
    root: Path | None = None,
) -> dict[str, DiaryEntry]:
    """
    Load specific entries by id (batch). Prefers SQLite rows; falls back to get_entry.
    """
    root = Path(root) if root else get_diary_dir()
    if not entry_ids:
        return {}
    out: dict[str, DiaryEntry] = {}
    try:
        from .index_db import get_rows_by_ids, db_path

        if db_path(root).exists():
            rows = get_rows_by_ids(root, entry_ids)
            for r in rows:
                eid = r.get("id") or ""
                if eid:
                    out[eid] = _entry_from_dict(r, fallback_id=eid)
    except Exception as e:
        log.debug("get_entries_by_ids sqlite failed: %s", e)

    missing = [i for i in entry_ids if i not in out]
    for eid in missing:
        e = get_entry(eid, root)
        if e:
            out[e.id] = e
    return out


def get_entry(entry_id: str, root: Path | None = None) -> DiaryEntry | None:
    root = Path(root) if root else get_diary_dir()
    # Fast path: single-row SQLite lookup
    try:
        from .index_db import get_rows_by_ids, db_path

        if db_path(root).exists():
            rows = get_rows_by_ids(root, [entry_id])
            if rows:
                return _entry_from_dict(rows[0], fallback_id=entry_id)
            # prefix match still needs scan
            if len(entry_id) >= 8:
                # try exact only above; prefix below
                pass
    except Exception:
        pass

    # include archived so open/delete/unarchive still work
    all_entries = list_entries(root, include_archived=True)
    for e in all_entries:
        if e.id == entry_id:
            return e
    matches = [e for e in all_entries if e.id.startswith(entry_id)]
    if len(matches) == 1:
        return matches[0]
    return matches[0] if matches else None


def load_transcript_data(entry: DiaryEntry) -> dict:
    if not entry.transcript_path or not Path(entry.transcript_path).exists():
        return {}
    return _load_json(Path(entry.transcript_path))


def load_analysis_data(entry: DiaryEntry) -> dict:
    if not entry.analysis_path or not Path(entry.analysis_path).exists():
        return {}
    return _load_json(Path(entry.analysis_path))


def format_transcript_text(
    data: dict,
    speaker_map: dict | None = None,
    *,
    apply_names: bool = True,
) -> str:
    """Format transcript; by default apply entry/global speaker names."""
    if apply_names:
        try:
            from .speakers import format_transcript_with_names, SpeakerStore

            entry_map = speaker_map
            if entry_map is None:
                meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
                entry_map = meta.get("speaker_map") if isinstance(meta, dict) else None
            return format_transcript_with_names(
                data,
                entry_map=entry_map or {},
                store=SpeakerStore.load(),
            )
        except Exception:
            pass

    if "transcript" in data and isinstance(data["transcript"], dict):
        segs = data["transcript"].get("segments", [])
    else:
        segs = data.get("segments", [])
    lines = []
    for seg in segs or []:
        if not isinstance(seg, dict):
            continue
        sp = seg.get("speaker", "?")
        start = seg.get("start", seg.get("start_time", 0))
        end = seg.get("end", seg.get("end_time", 0))
        text = seg.get("text", "")
        try:
            lines.append(f"[{sp}] ({float(start):.1f}s - {float(end):.1f}s): {text}")
        except (TypeError, ValueError):
            lines.append(f"[{sp}]: {text}")
    return "\n".join(lines)


def format_entry_summary(entry: DiaryEntry) -> str:
    bits = [
        entry.created_at,
        f"{entry.duration_s:.0f}s" if entry.duration_s else None,
        f"{entry.segment_count} segs" if entry.segment_count else None,
        f"{len(entry.speakers)} spk" if entry.speakers else None,
        "audio" if entry.has_audio else "no-audio",
        "tx" if entry.has_transcript else "no-tx",
    ]
    return " · ".join(b for b in bits if b)


def entries_for_api(
    root: Path | None = None,
    limit: int = 100,
    person: str | None = None,
) -> list[dict]:
    """JSON-serializable list for Gradio/Tauri (includes has_audio / has_transcript)."""
    root = Path(root) if root else DEFAULT_DIARY_DIR
    if person:
        try:
            from .speakers import filter_entries_by_person, display_speakers_for_entry

            entries = filter_entries_by_person(person, diary_dir=root, limit=limit)
        except Exception:
            entries = list_entries(root, limit=limit)
    else:
        entries = list_entries(root, limit=limit)

    out = []
    try:
        from .speakers import display_speakers_for_entry, get_entry_speaker_map
        use_names = True
    except Exception:
        use_names = False

    for e in entries:
        d = e.to_dict()
        d["has_audio"] = e.has_audio
        d["has_transcript"] = e.has_transcript
        d["tags"] = list(e.tags or [])
        d["notes"] = e.notes or ""
        d["starred"] = bool(e.starred)
        if use_names:
            d["display_speakers"] = display_speakers_for_entry(e, diary_dir=root)
            d["speaker_map"] = get_entry_speaker_map(e, root) or d.get("speaker_map") or {}
        else:
            d["display_speakers"] = e.speakers
        out.append(d)
    return out
