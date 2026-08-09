"""Transcript / KeyPoints JSON round-trip."""
from diary_app.core.transcribe import Transcript, SpeakerSegment, KeyPoints


def test_segment_dual_keys():
    s = SpeakerSegment("Speaker 1", 1.5, 3.0, "hello")
    d = s.to_dict()
    assert d["start"] == 1.5
    assert d["start_time"] == 1.5
    assert d["end"] == 3.0
    s2 = SpeakerSegment.from_dict({"speaker": "S", "start": 2, "end": 4, "text": "x"})
    assert s2.start_time == 2.0
    assert s2.end_time == 4.0


def test_transcript_roundtrip():
    t = Transcript(
        segments=[SpeakerSegment("Speaker 1", 0, 1, "hi")],
        raw_text="hi",
        warnings=["note"],
    )
    j = t.to_json()
    t2 = Transcript.from_json(j)
    assert len(t2.segments) == 1
    assert t2.raw_text == "hi"
    assert t2.warnings == ["note"]


def test_transcript_nested_json():
    t = Transcript.from_json(
        {"transcript": {"segments": [{"speaker": "A", "start_time": 0, "end_time": 1, "text": "ok"}]}}
    )
    assert t.segments[0].text == "ok"


def test_keypoints_roundtrip():
    kp = KeyPoints(
        summary="s",
        key_points=["a"],
        takeaways=["b"],
        topics=["c"],
        action_items=["do x"],
        decisions=["chose y"],
    )
    j = kp.to_json()
    kp2 = KeyPoints.from_json(j)
    assert kp2.action_items == ["do x"]
    assert kp2.decisions == ["chose y"]
