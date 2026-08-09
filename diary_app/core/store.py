"""EntryStore — SQLite-primary history with file-backed transcript/analysis.

This is the product storage API. Files under diary_dir remain the document
store; SQLite (index.sqlite) is the authoritative index for list/search.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from diary_app.config import get_config
from diary_app.core import history as history_mod
from diary_app.core.index_db import rebuild_index, search_ids
from diary_app.core.logutil import get_logger

log = get_logger("store")


class EntryStore:
    """Facade over history + SQLite index."""

    def __init__(self, diary_dir: Path | None = None):
        cfg = get_config()
        self.root = Path(diary_dir) if diary_dir else Path(cfg.diary_dir)
        self.root.mkdir(parents=True, exist_ok=True)

    # ── write path ──────────────────────────────────────────────────────────

    def save_bundle(
        self,
        transcript: Any,
        key_points: Any | None = None,
        *,
        audio_path: Path | str | None = None,
        backend: str | None = None,
        device: str | None = None,
        entry_id: str | None = None,
    ) -> history_mod.DiaryEntry:
        entry = history_mod.save_entry_bundle(
            transcript,
            key_points,
            audio_path=audio_path,
            diary_dir=self.root,
            backend=backend,
            device=device,
            entry_id=entry_id,
        )
        return entry

    def archive_entry(self, entry_id: str, *, unarchive: bool = False) -> history_mod.DiaryEntry:
        return history_mod.archive_entry(entry_id, diary_dir=self.root, unarchive=unarchive)

    def delete_entry(self, entry_id: str, *, delete_audio: bool = False) -> dict:
        return history_mod.delete_entry(
            entry_id, diary_dir=self.root, delete_audio=delete_audio
        )

    # ── read path ───────────────────────────────────────────────────────────

    def list_entries(
        self,
        *,
        limit: int | None = None,
        include_archived: bool = False,
        require_transcript: bool = False,
        require_audio: bool = False,
    ) -> list[history_mod.DiaryEntry]:
        return history_mod.list_entries(
            self.root,
            limit=limit,
            include_archived=include_archived,
            require_transcript=require_transcript,
            require_audio=require_audio,
        )

    def get_entry(self, entry_id: str) -> history_mod.DiaryEntry | None:
        return history_mod.get_entry(entry_id, self.root)

    def load_transcript(self, entry: history_mod.DiaryEntry) -> dict:
        return history_mod.load_transcript_data(entry)

    def load_analysis(self, entry: history_mod.DiaryEntry) -> dict:
        return history_mod.load_analysis_data(entry)

    def search_ids(self, query: str, *, limit: int = 100) -> list[str]:
        return search_ids(self.root, query, limit=limit)

    def rebuild_index(self) -> int:
        return rebuild_index(self.root)

    def entries_for_api(
        self,
        *,
        limit: int = 100,
        person: str | None = None,
    ) -> list[dict]:
        return history_mod.entries_for_api(root=self.root, limit=limit, person=person)


def get_store(diary_dir: Path | None = None) -> EntryStore:
    return EntryStore(diary_dir=diary_dir)
