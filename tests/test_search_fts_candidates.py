"""Search loads only FTS candidates (no full library scan when index present)."""
from pathlib import Path

import pytest

from diary_app.config import AppConfig, set_config, reset_config
from diary_app.core.history import save_entry_bundle, invalidate_index_cache, list_entries
from diary_app.core.index_db import rebuild_index
from diary_app.core.search import search_diary
from diary_app.domain.models import SpeakerSegment, Transcript
from diary_app.core.analyzer import HeuristicAnalyzer


@pytest.fixture
def diary(tmp_path):
    root = tmp_path / "diary"
    root.mkdir()
    reset_config()
    set_config(AppConfig(diary_dir=root))
    yield root
    reset_config()
    invalidate_index_cache()


def _entry(root: Path, text: str, backend: str = "test"):
    tx = Transcript(segments=[SpeakerSegment("Speaker 1", 0, 2, text)])
    return save_entry_bundle(tx, HeuristicAnalyzer().analyze(tx), diary_dir=root, backend=backend)


def test_search_fts_candidates_only(diary, monkeypatch):
    _entry(diary, "We discussed the quarterly budget plan in detail.")
    _entry(diary, "Completely unrelated gardening tips for tomatoes.")
    rebuild_index(diary)
    invalidate_index_cache()

    # If search falls back to full list_entries without limit, this spy will see limit=None often
    calls = []
    import diary_app.core.search as search_mod
    import diary_app.core.history as history_mod

    real_list = history_mod.list_entries

    def spy_list(*args, **kwargs):
        calls.append(kwargs)
        return real_list(*args, **kwargs)

    monkeypatch.setattr(history_mod, "list_entries", spy_list)
    monkeypatch.setattr(search_mod, "list_entries", spy_list)

    hits = search_diary("budget", diary_dir=diary, limit=10)
    assert len(hits) >= 1
    assert any("budget" in (h.title + h.preview).lower() or h.segments for h in hits)
    # FTS path should not need full list_entries
    assert calls == [], f"expected no list_entries fallback, got {calls}"


def test_search_empty_fts_returns_empty(diary):
    _entry(diary, "alpha beta gamma")
    rebuild_index(diary)
    hits = search_diary("zzzznotfoundzzz", diary_dir=diary)
    assert hits == []
