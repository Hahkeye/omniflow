"""SQLite index for diary history listing and full-text search."""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Any, Iterable

from .logutil import get_logger

log = get_logger("index_db")

DB_NAME = "index.sqlite"
SCHEMA_VERSION = 1


def db_path(diary_dir: Path) -> Path:
    return Path(diary_dir) / DB_NAME


def connect(diary_dir: Path) -> sqlite3.Connection:
    path = db_path(diary_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    _ensure_schema(conn)
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT
        );
        CREATE TABLE IF NOT EXISTS entries (
            id TEXT PRIMARY KEY,
            created_at TEXT,
            created_ts REAL,
            title TEXT,
            preview TEXT,
            speakers TEXT,
            tags TEXT,
            notes TEXT,
            starred INTEGER DEFAULT 0,
            archived INTEGER DEFAULT 0,
            audio_path TEXT,
            transcript_path TEXT,
            analysis_path TEXT,
            duration_s REAL DEFAULT 0,
            segment_count INTEGER DEFAULT 0,
            backend TEXT,
            updated_at REAL
        );
        CREATE INDEX IF NOT EXISTS idx_entries_ts ON entries(created_ts DESC);
        CREATE INDEX IF NOT EXISTS idx_entries_archived ON entries(archived);

        CREATE VIRTUAL TABLE IF NOT EXISTS entries_fts USING fts5(
            id UNINDEXED,
            title,
            preview,
            speakers,
            tags,
            notes,
            body,
            tokenize='porter unicode61'
        );
        """
    )
    row = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
    if not row:
        conn.execute(
            "INSERT INTO meta(key, value) VALUES('schema_version', ?)",
            (str(SCHEMA_VERSION),),
        )
        conn.commit()


def _join_list(values: Iterable[str] | None) -> str:
    return " ".join(str(v) for v in (values or []) if v)


def set_meta(diary_dir: Path, key: str, value: str) -> None:
    try:
        conn = connect(diary_dir)
        conn.execute(
            "INSERT INTO meta(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        log.debug("set_meta failed: %s", e)


def get_meta(diary_dir: Path, key: str) -> str | None:
    path = db_path(diary_dir)
    if not path.exists():
        return None
    try:
        conn = connect(diary_dir)
        row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        conn.close()
        return row["value"] if row else None
    except Exception:
        return None


def entry_count(diary_dir: Path) -> int:
    path = db_path(diary_dir)
    if not path.exists():
        return 0
    try:
        conn = connect(diary_dir)
        n = conn.execute("SELECT COUNT(*) AS n FROM entries").fetchone()["n"]
        conn.close()
        return int(n or 0)
    except Exception:
        return 0


def touch_tree_fingerprint(diary_dir: Path, fingerprint: str | None = None) -> None:
    """Record diary tree fingerprint so list_entries can trust SQLite."""
    if fingerprint is None:
        try:
            from .history import _index_fingerprint

            fingerprint = _index_fingerprint(Path(diary_dir))
        except Exception:
            fingerprint = str(time.time())
    set_meta(diary_dir, "tree_fp", fingerprint)


def is_index_fresh(diary_dir: Path, fingerprint: str | None = None) -> bool:
    """True when SQLite exists, has rows, and tree_fp matches the diary tree."""
    root = Path(diary_dir)
    if not db_path(root).exists():
        return False
    if entry_count(root) <= 0:
        return False
    stored = get_meta(root, "tree_fp")
    if not stored:
        return False
    if fingerprint is None:
        try:
            from .history import _index_fingerprint

            fingerprint = _index_fingerprint(root)
        except Exception:
            return False
    return stored == fingerprint


def _row_to_dict(r: sqlite3.Row) -> dict[str, Any]:
    import json

    speakers: list[str]
    raw_sp = r["speakers"] or ""
    if raw_sp.startswith("["):
        try:
            speakers = list(json.loads(raw_sp))
        except Exception:
            speakers = [s for s in raw_sp.split() if s]
    else:
        speakers = [s for s in raw_sp.split() if s]

    raw_tags = r["tags"] or ""
    if raw_tags.startswith("["):
        try:
            tags = list(json.loads(raw_tags))
        except Exception:
            tags = [t for t in raw_tags.split() if t]
    else:
        tags = [t for t in raw_tags.split() if t]

    return {
        "id": r["id"],
        "created_at": r["created_at"] or "",
        "created_ts": float(r["created_ts"] or 0),
        "title": r["title"] or r["id"],
        "preview": r["preview"] or "",
        "speakers": speakers,
        "tags": tags,
        "notes": r["notes"] or "",
        "starred": bool(r["starred"]),
        "archived": bool(r["archived"]),
        "audio_path": r["audio_path"],
        "transcript_path": r["transcript_path"],
        "analysis_path": r["analysis_path"],
        "duration_s": float(r["duration_s"] or 0),
        "segment_count": int(r["segment_count"] or 0),
        "backend": r["backend"],
        "audio_size_mb": 0.0,
        "speaker_map": {},
    }


def get_rows_by_ids(diary_dir: Path, entry_ids: list[str]) -> list[dict[str, Any]]:
    """Fetch specific entry rows by primary key (order follows entry_ids)."""
    root = Path(diary_dir)
    if not entry_ids or not db_path(root).exists():
        return []
    try:
        conn = connect(root)
        placeholders = ",".join("?" for _ in entry_ids)
        rows = conn.execute(
            f"SELECT * FROM entries WHERE id IN ({placeholders})",
            list(entry_ids),
        ).fetchall()
        conn.close()
        by_id = {r["id"]: _row_to_dict(r) for r in rows}
        return [by_id[i] for i in entry_ids if i in by_id]
    except Exception as e:
        log.debug("get_rows_by_ids failed: %s", e)
        return []


def list_entries_from_db(
    diary_dir: Path,
    *,
    include_archived: bool = False,
    limit: int | None = None,
) -> list[dict[str, Any]] | None:
    """
    Load entry rows from SQLite newest-first.

    Returns None if the index is missing/unusable (caller should full-scan).
    Returns a list of dicts suitable for DiaryEntry construction (may be empty).
    """
    root = Path(diary_dir)
    if not db_path(root).exists():
        return None
    try:
        conn = connect(root)
        if include_archived:
            sql = "SELECT * FROM entries ORDER BY created_ts DESC"
            params: tuple = ()
        else:
            sql = "SELECT * FROM entries WHERE archived = 0 ORDER BY created_ts DESC"
            params = ()
        if limit is not None:
            sql += " LIMIT ?"
            params = params + (int(limit),)
        rows = conn.execute(sql, params).fetchall()
        conn.close()
    except Exception as e:
        log.debug("list_entries_from_db failed: %s", e)
        return None

    return [_row_to_dict(r) for r in rows]


def upsert_entry(
    diary_dir: Path,
    entry: Any,
    *,
    body: str = "",
    archived: bool | None = None,
    update_fingerprint: bool = True,
) -> None:
    """Insert or update one entry and its FTS row.

    archived: if None, use entry.archived; if bool, that value wins (needed for unarchive).
    """
    try:
        conn = connect(diary_dir)
    except Exception as e:
        log.warning("SQLite unavailable: %s", e)
        return
    try:
        eid = entry.id
        # Prefer JSON for speakers/tags to preserve multi-word names
        import json

        speakers_list = list(getattr(entry, "speakers", None) or [])
        tags_list = list(getattr(entry, "tags", None) or [])
        speakers = json.dumps(speakers_list, ensure_ascii=False)
        tags = json.dumps(tags_list, ensure_ascii=False)
        notes = getattr(entry, "notes", "") or ""
        title = getattr(entry, "title", "") or ""
        preview = getattr(entry, "preview", "") or ""
        now = time.time()
        if archived is None:
            arch_flag = 1 if getattr(entry, "archived", False) else 0
        else:
            arch_flag = 1 if archived else 0
        conn.execute(
            """
            INSERT INTO entries(
                id, created_at, created_ts, title, preview, speakers, tags, notes,
                starred, archived, audio_path, transcript_path, analysis_path,
                duration_s, segment_count, backend, updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET
                created_at=excluded.created_at,
                created_ts=excluded.created_ts,
                title=excluded.title,
                preview=excluded.preview,
                speakers=excluded.speakers,
                tags=excluded.tags,
                notes=excluded.notes,
                starred=excluded.starred,
                archived=excluded.archived,
                audio_path=excluded.audio_path,
                transcript_path=excluded.transcript_path,
                analysis_path=excluded.analysis_path,
                duration_s=excluded.duration_s,
                segment_count=excluded.segment_count,
                backend=excluded.backend,
                updated_at=excluded.updated_at
            """,
            (
                eid,
                getattr(entry, "created_at", "") or "",
                float(getattr(entry, "created_ts", 0) or 0),
                title,
                preview,
                speakers,
                tags,
                notes,
                1 if getattr(entry, "starred", False) else 0,
                arch_flag,
                getattr(entry, "audio_path", None),
                getattr(entry, "transcript_path", None),
                getattr(entry, "analysis_path", None),
                float(getattr(entry, "duration_s", 0) or 0),
                int(getattr(entry, "segment_count", 0) or 0),
                getattr(entry, "backend", None),
                now,
            ),
        )
        speakers_fts = _join_list(speakers_list)
        tags_fts = _join_list(tags_list)
        conn.execute("DELETE FROM entries_fts WHERE id = ?", (eid,))
        conn.execute(
            """
            INSERT INTO entries_fts(id, title, preview, speakers, tags, notes, body)
            VALUES (?,?,?,?,?,?,?)
            """,
            (eid, title, preview, speakers_fts, tags_fts, notes, body or ""),
        )
        conn.commit()
    except Exception as e:
        log.warning("upsert_entry failed for %s: %s", getattr(entry, "id", "?"), e)
    finally:
        conn.close()
    if update_fingerprint:
        touch_tree_fingerprint(diary_dir)


def remove_entry(diary_dir: Path, entry_id: str) -> None:
    try:
        conn = connect(diary_dir)
        conn.execute("DELETE FROM entries WHERE id = ?", (entry_id,))
        conn.execute("DELETE FROM entries_fts WHERE id = ?", (entry_id,))
        conn.commit()
        conn.close()
    except Exception as e:
        log.warning("remove_entry failed: %s", e)


def search_ids(
    diary_dir: Path,
    query: str,
    *,
    limit: int = 100,
    include_archived: bool = False,
) -> list[str]:
    """Return entry ids ranked by FTS relevance. Empty if index missing or query empty."""
    q = (query or "").strip()
    if not q:
        return []
    path = db_path(diary_dir)
    if not path.exists():
        return []
    # FTS5: quote terms; simple AND for multi-word
    terms = [t for t in q.replace('"', " ").split() if t]
    if not terms:
        return []
    fts_q = " ".join(f'"{t}"' for t in terms)
    try:
        conn = connect(diary_dir)
        if include_archived:
            rows = conn.execute(
                """
                SELECT e.id FROM entries_fts f
                JOIN entries e ON e.id = f.id
                WHERE entries_fts MATCH ?
                ORDER BY bm25(entries_fts), e.created_ts DESC
                LIMIT ?
                """,
                (fts_q, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT e.id FROM entries_fts f
                JOIN entries e ON e.id = f.id
                WHERE entries_fts MATCH ? AND e.archived = 0
                ORDER BY bm25(entries_fts), e.created_ts DESC
                LIMIT ?
                """,
                (fts_q, limit),
            ).fetchall()
        conn.close()
        return [r["id"] for r in rows]
    except Exception as e:
        log.debug("FTS search failed (falling back): %s", e)
        return []


def rebuild_index(diary_dir: Path) -> int:
    """Rebuild SQLite index from filesystem history. Returns entry count."""
    from .history import (
        list_entries,
        load_transcript_data,
        load_analysis_data,
        format_transcript_text,
        _index_fingerprint,
    )

    root = Path(diary_dir)
    # wipe FTS + entries for clean rebuild
    try:
        conn = connect(root)
        conn.execute("DELETE FROM entries")
        conn.execute("DELETE FROM entries_fts")
        conn.commit()
        conn.close()
    except Exception as e:
        log.warning("rebuild clear failed: %s", e)
        return 0

    count = 0
    # force_scan avoids reading the SQLite we just cleared
    for entry in list_entries(
        root, limit=None, use_cache=False, include_archived=True, force_scan=True
    ):
        body_parts: list[str] = []
        tx = load_transcript_data(entry)
        if tx:
            body_parts.append(format_transcript_text(tx, apply_names=False))
        an = load_analysis_data(entry)
        if an:
            kp = an.get("key_points", an)
            if isinstance(kp, dict):
                body_parts.append(str(kp.get("summary") or ""))
                body_parts.extend(str(x) for x in (kp.get("key_points") or []))
                body_parts.extend(str(x) for x in (kp.get("topics") or []))
                body_parts.extend(str(x) for x in (kp.get("action_items") or []))
                body_parts.extend(str(x) for x in (kp.get("decisions") or []))
        archived = bool(getattr(entry, "archived", False))
        upsert_entry(
            root, entry, body="\n".join(body_parts), archived=archived, update_fingerprint=False
        )
        count += 1
    touch_tree_fingerprint(root, _index_fingerprint(root))
    log.info("Rebuilt SQLite index: %d entries at %s", count, db_path(root))
    return count
