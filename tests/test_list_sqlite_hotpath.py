"""SQLite-first list_entries hot path."""
from pathlib import Path

import pytest

from diary_app.config import AppConfig, set_config, reset_config
from diary_app.core.history import list_entries, save_entry_bundle, invalidate_index_cache
from diary_app.core.index_db import (
    is_index_fresh,
    list_entries_from_db,
    rebuild_index,
    entry_count,
)
from diary_app.domain.models import SpeakerSegment, Transcript
from diary_app.core.analyzer import HeuristicAnalyzer


@pytest.fixture
def diary_root(tmp_path, monkeypatch):
    root = tmp_path / "diary"
    root.mkdir()
    reset_config()
    set_config(AppConfig(diary_dir=root))
    monkeypatch.setenv("DIARY_DIR", str(root))
    yield root
    reset_config()
    invalidate_index_cache()


def test_list_hits_sqlite_after_save(diary_root):
    tx = Transcript(segments=[SpeakerSegment("Speaker 1", 0, 1, "budget plan")])
    kp = HeuristicAnalyzer().analyze(tx)
    entry = save_entry_bundle(tx, kp, diary_dir=diary_root, backend="test")
    invalidate_index_cache()

    # Fingerprint should match after upsert touch
    from diary_app.core.history import _index_fingerprint
    from diary_app.core.index_db import is_index_fresh

    fp = _index_fingerprint(diary_root)
    assert is_index_fresh(diary_root, fp)
    rows = list_entries_from_db(diary_root)
    assert rows is not None
    assert any(r["id"] == entry.id for r in rows)

    listed = list_entries(diary_root, limit=10)
    assert any(e.id == entry.id for e in listed)


def test_rebuild_then_list(diary_root):
    tx = Transcript(segments=[SpeakerSegment("Speaker 1", 0, 1, "hello world")])
    save_entry_bundle(tx, HeuristicAnalyzer().analyze(tx), diary_dir=diary_root)
    n = rebuild_index(diary_root)
    assert n >= 1
    assert entry_count(diary_root) >= 1
    listed = list_entries(diary_root)
    assert len(listed) >= 1
