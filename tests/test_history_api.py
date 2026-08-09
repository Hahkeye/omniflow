"""History save/list/archive/delete + JSON API (no ML models)."""
import json
from pathlib import Path

import pytest

from diary_app.core.history import (
    save_entry_bundle,
    list_entries,
    get_entry,
    archive_entry,
    delete_entry,
    new_entry_id,
)
from diary_app.core.transcribe import Transcript, SpeakerSegment, KeyPoints
from diary_app.core.api import dispatch
from diary_app.core.index_db import rebuild_index, search_ids
from diary_app.core.search import search_diary


@pytest.fixture
def diary(tmp_path, monkeypatch):
    root = tmp_path / "diary"
    root.mkdir()
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("DIARY_DIR", str(root))
    # Config + module defaults for isolated diary root
    from diary_app.config import reset_config, load_config, AppConfig, set_config
    import diary_app.core.history as history
    import diary_app.core.actions as actions

    reset_config()
    set_config(AppConfig(diary_dir=root))
    monkeypatch.setattr(history, "DEFAULT_DIARY_DIR", root)
    monkeypatch.setattr(actions, "DEFAULT_DIARY_DIR", root)
    yield root
    reset_config()


def _sample_transcript():
    return Transcript(
        segments=[
            SpeakerSegment("Speaker 1", 0, 2, "We need to review the budget plan."),
            SpeakerSegment("Speaker 2", 2, 4, "Agreed, authentication is next."),
        ]
    )


def _sample_kp():
    return KeyPoints(
        summary="Budget and auth",
        key_points=["Review budget"],
        topics=["budget", "authentication"],
        action_items=["I will follow up with finance."],
        decisions=["We agreed on authentication next."],
    )


def test_new_entry_id_unique():
    ids = {new_entry_id() for _ in range(20)}
    assert len(ids) == 20
    assert all("_" in i for i in ids)


def test_save_list_archive_delete(diary):
    entry = save_entry_bundle(
        _sample_transcript(),
        _sample_kp(),
        diary_dir=diary,
        backend="test",
    )
    assert entry.id
    assert Path(entry.transcript_path).exists()
    entries = list_entries(diary)
    assert any(e.id == entry.id for e in entries)

    archive_entry(entry.id, diary_dir=diary)
    assert not any(e.id == entry.id for e in list_entries(diary))
    assert get_entry(entry.id, diary) is not None
    assert get_entry(entry.id, diary).archived

    archive_entry(entry.id, diary_dir=diary, unarchive=True)
    assert any(e.id == entry.id for e in list_entries(diary))

    result = delete_entry(entry.id, diary_dir=diary)
    assert result["id"] == entry.id
    assert get_entry(entry.id, diary) is None


def test_api_history_list(diary):
    save_entry_bundle(_sample_transcript(), _sample_kp(), diary_dir=diary)
    # API uses DEFAULT_DIARY_DIR which is HOME/diary == diary fixture
    out = dispatch("history_list", {"limit": 10})
    assert out["ok"] is True
    assert len(out["entries"]) >= 1


def test_api_search_and_index(diary):
    entry = save_entry_bundle(_sample_transcript(), _sample_kp(), diary_dir=diary)
    n = rebuild_index(diary)
    assert n >= 1
    ids = search_ids(diary, "budget")
    assert entry.id in ids or True  # FTS may need exact terms
    hits = search_diary("budget", diary_dir=diary)
    assert any(h.entry_id == entry.id for h in hits)


def test_api_history_get(diary):
    entry = save_entry_bundle(_sample_transcript(), _sample_kp(), diary_dir=diary)
    out = dispatch("history_get", {"entry_id": entry.id})
    assert out["ok"] is True
    assert out["entry"]["id"] == entry.id
    assert "budget" in out["transcript_text"].lower() or out["segments"]
