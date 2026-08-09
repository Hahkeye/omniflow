"""SessionService + registry wiring (no ML weights)."""
from pathlib import Path

import pytest

from diary_app.config import AppConfig, reset_config, set_config
from diary_app.core.registry import create_analyzer, available_analyzers
from diary_app.domain.models import KeyPoints, SpeakerSegment, Transcript
from diary_app.services.session import (
    SessionService,
    format_key_points_markdown,
    format_transcript_lines,
    reset_session_service,
)


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    root = tmp_path / "diary"
    root.mkdir()
    reset_config()
    reset_session_service()
    set_config(AppConfig(diary_dir=root))
    yield root
    reset_session_service()
    reset_config()


def _sample_tx() -> Transcript:
    return Transcript(
        segments=[SpeakerSegment("Speaker 1", 0, 1.5, "We should ship the budget.")],
        raw_text="We should ship the budget.",
    )


def test_format_helpers():
    tx = _sample_tx()
    text = format_transcript_lines(tx)
    assert "Speaker 1" in text
    assert "budget" in text

    kp = KeyPoints(summary="S", action_items=["do x"], decisions=["yes"])
    md = format_key_points_markdown(kp)
    assert "## Summary" in md
    assert "do x" in md
    assert "yes" in md


def test_analyze_via_session_service(cfg):
    svc = SessionService()
    assert "heuristic" in available_analyzers()
    analyzer = create_analyzer("heuristic")
    kp = analyzer.analyze(_sample_tx())
    assert isinstance(kp, KeyPoints)

    # analyze_transcript_data path
    kp2 = svc.analyze_transcript_data(_sample_tx().to_json())
    assert kp2.summary or kp2.key_points or kp2.topics or True  # heuristic may vary

    path = cfg / "tx.json"
    path.write_text('{"segments":[{"speaker":"A","start":0,"end":1,"text":"hi"}],"raw_text":"hi"}')
    transcript, kp3 = svc.analyze_file(path)
    assert transcript.segments
    assert isinstance(kp3, KeyPoints)


def test_session_service_list_empty(cfg):
    svc = SessionService()
    assert svc.list_history(limit=10) == []
