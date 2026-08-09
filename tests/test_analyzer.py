"""Analyzer quality smoke tests."""
from diary_app.core.analyzer import TranscriptAnalyzer
from diary_app.core.transcribe import Transcript, SpeakerSegment


def _tx(*texts: str) -> Transcript:
    segs = []
    t = 0.0
    for i, text in enumerate(texts):
        segs.append(SpeakerSegment(f"Speaker {(i % 2) + 1}", t, t + 5, text))
        t += 5
    return Transcript(segments=segs)


def test_decisions_and_actions_separated():
    t = _tx(
        "We decided to ship the budget plan by Friday.",
        "I will follow up with design next week.",
        "Sounds good, let's go with the blue theme.",
        "The meeting covered product and marketing budgets.",
    )
    kp = TranscriptAnalyzer().analyze(t)
    # Decision language should land in decisions
    assert any("decided" in d.lower() for d in kp.decisions)
    # "ship the budget" alone should not be an action solely due to verb "ship"
    assert not any(
        a.lower().startswith("we decided to ship") for a in kp.action_items
    )
    # Explicit commitment is an action
    assert any("follow up" in a.lower() or "i will" in a.lower() for a in kp.action_items)


def test_topics_not_junk_discourse():
    t = _tx(
        "We reviewed the budget plan and marketing calendar.",
        "The product roadmap includes authentication improvements.",
    )
    kp = TranscriptAnalyzer().analyze(t)
    joined = " ".join(kp.topics).lower()
    assert "sounds good" not in joined
    assert "good let" not in joined
    # should surface contentful terms
    assert any(
        w in joined for w in ("budget", "marketing", "product", "roadmap", "authentication")
    )


def test_speaker_stats():
    t = _tx("hello world one two", "short")
    kp = TranscriptAnalyzer().analyze(t)
    assert "Speaker 1" in kp.speaker_stats
    assert kp.speaker_stats["Speaker 1"]["word_count"] == 4
