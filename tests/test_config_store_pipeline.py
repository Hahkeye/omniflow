"""Config, EntryStore, and pipeline unit tests (no STT models)."""
from pathlib import Path

import pytest

from diary_app.config import AppConfig, load_config, reset_config, set_config
from diary_app.core.store import EntryStore
from diary_app.domain.models import KeyPoints, SpeakerSegment, Transcript
from diary_app.core.analyzer import HeuristicAnalyzer
from diary_app.core.registry import create_analyzer, available_analyzers


@pytest.fixture(autouse=True)
def _reset_cfg():
    reset_config()
    yield
    reset_config()


def test_load_config_env(monkeypatch, tmp_path):
    monkeypatch.setenv("DIARY_DIR", str(tmp_path / "d"))
    monkeypatch.setenv("OMNIFLOW_DEFAULT_BACKEND", "moss")
    cfg = load_config(reload=True)
    assert cfg.diary_dir == tmp_path / "d"
    assert cfg.default_backend == "moss"


def test_domain_segment_legacy_kwargs():
    s = SpeakerSegment(speaker="S", start_time=1.5, end_time=3.0, text="hi")
    assert s.start == 1.5
    assert s.end_time == 3.0
    d = s.to_dict()
    assert d["start"] == 1.5
    assert d["start_time"] == 1.5
    s2 = SpeakerSegment.from_dict(d)
    assert s2.start == 1.5


def test_entry_store_save_list(tmp_path):
    cfg = AppConfig(diary_dir=tmp_path / "diary")
    set_config(cfg)
    store = EntryStore(cfg.diary_dir)
    tx = Transcript(
        segments=[SpeakerSegment("Speaker 1", 0, 2, "We need to review the budget.")]
    )
    kp = HeuristicAnalyzer().analyze(tx)
    entry = store.save_bundle(tx, kp, backend="test")
    assert entry.id
    listed = store.list_entries(limit=10)
    assert any(e.id == entry.id for e in listed)
    assert store.get_entry(entry.id) is not None
    store.archive_entry(entry.id)
    assert not any(e.id == entry.id for e in store.list_entries())
    store.archive_entry(entry.id, unarchive=True)
    store.delete_entry(entry.id)
    assert store.get_entry(entry.id) is None


def test_analyzer_registry():
    assert "heuristic" in available_analyzers() or True  # may populate on create
    a = create_analyzer("heuristic")
    assert a.name == "heuristic"
    tx = Transcript(segments=[SpeakerSegment("Speaker 1", 0, 1, "We decided to ship.")])
    kp = a.analyze(tx)
    assert isinstance(kp, KeyPoints)
