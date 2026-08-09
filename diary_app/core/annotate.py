"""Tags, notes, and star flags on diary entries."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from .history import (
    DEFAULT_DIARY_DIR,
    DiaryEntry,
    get_entry,
    list_entries,
    invalidate_index_cache,
)


def _entry_path(entry_id: str, diary_dir: Path) -> Path:
    return diary_dir / "entries" / f"{entry_id}.json"


def _normalize_tags(tags: list[str] | None) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for t in tags or []:
        t = str(t).strip().lstrip("#").lower().replace(" ", "-")
        if not t or t in seen:
            continue
        seen.add(t)
        out.append(t)
    return out


def update_entry_annotation(
    entry_id: str,
    *,
    diary_dir: Path | None = None,
    add_tags: list[str] | None = None,
    remove_tags: list[str] | None = None,
    set_tags: list[str] | None = None,
    notes: str | None = None,
    append_note: str | None = None,
    starred: bool | None = None,
) -> DiaryEntry:
    """
    Update tags/notes/star on an entry index file.

    Creates entries/<id>.json if missing (from scanned history).
    """
    root = Path(diary_dir) if diary_dir else DEFAULT_DIARY_DIR
    entry = get_entry(entry_id, root)
    if not entry:
        raise ValueError(f"Entry not found: {entry_id}")

    path = _entry_path(entry.id, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            data = entry.to_dict()
    else:
        data = entry.to_dict()

    tags = _normalize_tags(data.get("tags") or entry.tags or [])
    if set_tags is not None:
        tags = _normalize_tags(set_tags)
    else:
        for t in _normalize_tags(add_tags):
            if t not in tags:
                tags.append(t)
        remove = set(_normalize_tags(remove_tags))
        tags = [t for t in tags if t not in remove]

    current_notes = data.get("notes") if data.get("notes") is not None else (entry.notes or "")
    if notes is not None:
        current_notes = notes
    if append_note:
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        line = f"[{stamp}] {append_note.strip()}"
        current_notes = (current_notes.rstrip() + "\n" + line).strip() if current_notes else line

    if starred is not None:
        data["starred"] = bool(starred)
    elif "starred" not in data:
        data["starred"] = bool(entry.starred)

    data["tags"] = tags
    data["notes"] = current_notes
    data["id"] = entry.id
    # keep other fields from entry if missing
    for k, v in entry.to_dict().items():
        data.setdefault(k, v)

    from .history import _write_json

    _write_json(path, data)
    invalidate_index_cache()

    updated = get_entry(entry.id, root)
    if not updated:
        # build from data
        from .history import _entry_from_dict
        updated = _entry_from_dict(data, fallback_id=entry.id)
    try:
        from .index_db import upsert_entry

        upsert_entry(root, updated, archived=bool(updated.archived))
    except Exception:
        pass
    return updated


def list_all_tags(diary_dir: Path | None = None) -> list[dict[str, Any]]:
    """Return tags with usage counts."""
    root = Path(diary_dir) if diary_dir else DEFAULT_DIARY_DIR
    counts: dict[str, int] = {}
    for e in list_entries(root, limit=None):
        for t in e.tags or []:
            t = str(t).lower()
            counts[t] = counts.get(t, 0) + 1
    return [
        {"tag": t, "count": c}
        for t, c in sorted(counts.items(), key=lambda x: (-x[1], x[0]))
    ]


def filter_entries(
    *,
    diary_dir: Path | None = None,
    tag: str | None = None,
    starred: bool | None = None,
    limit: int | None = 100,
) -> list[DiaryEntry]:
    root = Path(diary_dir) if diary_dir else DEFAULT_DIARY_DIR
    tag_n = tag.strip().lstrip("#").lower() if tag else None
    out = []
    for e in list_entries(root, limit=None):
        if tag_n and tag_n not in [str(t).lower() for t in (e.tags or [])]:
            continue
        if starred is True and not e.starred:
            continue
        if starred is False and e.starred:
            continue
        out.append(e)
    if limit is not None:
        out = out[:limit]
    return out
