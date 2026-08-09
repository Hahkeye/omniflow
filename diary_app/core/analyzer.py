"""Analyze transcripts to extract key points, takeaways, and topics."""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from diary_app.domain.models import KeyPoints, Transcript

# Common words to exclude from keyword extraction
STOP_WORDS = frozenset({
    "i", "me", "my", "myself", "we", "our", "ours", "ourselves", "you",
    "your", "yours", "yourself", "yourselves", "he", "him", "his", "himself",
    "she", "her", "hers", "herself", "it", "its", "itself", "they", "them",
    "their", "theirs", "themselves", "what", "which", "who", "whom",
    "this", "that", "these", "those", "am", "is", "are", "was", "were",
    "be", "been", "being", "have", "has", "had", "having", "do", "does",
    "did", "doing", "a", "an", "the", "and", "but", "if", "or", "because",
    "as", "until", "while", "of", "at", "by", "for", "with", "about",
    "against", "between", "through", "during", "before", "after", "above",
    "below", "to", "from", "up", "down", "in", "out", "on", "off",
    "over", "under", "again", "further", "then", "once", "here", "there",
    "when", "where", "why", "how", "all", "both", "each", "few", "more",
    "most", "other", "some", "such", "no", "nor", "not", "only", "own",
    "same", "so", "than", "too", "very", "s", "t", "can", "will", "just",
    "don", "should", "now", "d", "ll", "m", "o", "re", "ve", "y",
    "ain", "aren", "couldn", "didn", "doesn", "hadn", "hasn", "haven",
    "isn", "ma", "mightn", "mustn", "needn", "shan", "shouldn", "wasn",
    "weren", "won", "wouldn",
    # filler / discourse
    "um", "uh", "like", "know", "right", "yeah", "yep", "erm", "okay", "ok",
    "well", "really", "actually", "basically", "literally", "stuff", "thing",
    "things", "something", "anything", "everything", "nothing", "lot", "bit",
    "kind", "sort", "gonna", "wanna", "gotta", "yeah", "yes", "nope",
    "let", "lets", "us", "get", "got", "go", "going", "went", "come", "came",
    "make", "made", "take", "took", "say", "said", "said", "think", "thought",
    "see", "saw", "look", "want", "need", "good", "great", "bad", "nice",
    "sounds", "sound", "feel", "feels", "people", "time", "way", "day",
})

# Tokens that are almost never useful as "topics" alone
TOPIC_BLOCKLIST = frozenset({
    "speaker", "speakers", "segment", "transcript", "meeting", "discussion",
    "conversation", "talk", "talking", "today", "tomorrow", "yesterday",
    "friday", "monday", "tuesday", "wednesday", "thursday", "saturday", "sunday",
    "week", "month", "year", "minute", "minutes", "second", "seconds",
    "plan", "plans", "ship", "call", "send", "email", "follow", "next",
    "step", "steps", "item", "items", "point", "points",
})

QUESTION_WORDS = {
    "what": "topic",
    "why": "reason",
    "how": "method",
    "when": "time",
    "where": "location",
    "who": "person",
    "which": "selection",
    "whose": "ownership",
    "whether": "choice",
}

STRONG_WORDS = frozenset({
    "important", "crucial", "key", "significant", "must",
    "should", "need", "really", "definitely", "actually",
    "first", "last", "only", "best", "worst", "most", "least",
    "decide", "decision", "action", "next", "plan", "goal",
})

# High-precision action cues (avoid bare verb matches like "ship the product")
_ACTION_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\b(i|we|you|they|let'?s)\s+(need to|have to|should|must|will|gonna|going to)\s+\w+",
        r"\b(todo|to-do|action item|follow[- ]?up)\b",
        r"\b(please|remember to|make sure|don'?t forget)\s+\w+",
        r"\b(i'?ll|we'?ll|you'?ll)\s+(send|email|call|ship|deploy|fix|merge|review|finish|complete|schedule|assign|write|check|update|follow)\b",
        r"\b(next step|next steps)\b.+\b",
        r"\bby (monday|tuesday|wednesday|thursday|friday|eod|eow|tomorrow|next week)\b",
        r"\b(assign|schedule)\s+\w+",
    )
]
_DECISION_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\b(we|i|they)\s+(decided|agree|agreed|chose|picked|will go with|going with)\b",
        r"\b(decision|consensus|final call|settled on|approved)\b",
        r"\b(let'?s go with|let'?s do|we'?re doing)\b",
        r"\b(yes[,.]?\s+we should|sounds good[,.]?\s+let'?s)\b",
    )
]

# Content words that look like nouns (suffix heuristics) — still conservative
_NOUN_SUFFIXES = (
    "tion", "sion", "ment", "ness", "ship", "ance", "ence", "ity", "ty",
    "ism", "ure", "age", "ology", "ography",
)
_VERBISH = frozenset({
    "is", "are", "was", "were", "have", "has", "had", "do", "does", "did",
    "will", "would", "should", "could", "can", "may", "might", "must",
    "decided", "agreed", "shipped", "called", "sent", "going", "doing",
    "sounds", "covered", "discussed", "talked", "follow", "followed",
})


@dataclass
class TopicSummary:
    """A single topic found in the transcript."""
    topic: str
    mentions: int
    key_phrases: list[str] = field(default_factory=list)


class HeuristicAnalyzer:
    """Default heuristic analyzer (no API key). Registered as ``heuristic``."""

    name = "heuristic"

    def __init__(self, min_sentence_length: int = 5, max_sentences: int = 10):
        self.min_sentence_length = min_sentence_length
        self.max_sentences = max_sentences

    def analyze(self, transcript: Transcript) -> KeyPoints:
        """Run full analysis on a transcript (key points computed once)."""
        speaker_stats = self._compute_speaker_stats(transcript)
        topics = self._extract_topics(transcript)
        key_points = self._extract_key_points(transcript)
        action_items = self._extract_action_items(transcript)
        decisions = self._extract_decisions(transcript)
        # Drop action items that are pure decisions (already captured)
        dec_norm = {d.lower().rstrip(".!?") for d in decisions}
        action_items = [
            a for a in action_items if a.lower().rstrip(".!?") not in dec_norm
        ]
        takeaways = self._generate_takeaways(
            transcript, topics, key_points, action_items, decisions
        )
        summary = self._generate_summary(transcript, topics, key_points)

        return KeyPoints(
            summary=summary,
            key_points=key_points,
            takeaways=takeaways,
            topics=[t.topic for t in topics],
            speaker_stats=speaker_stats,
            action_items=action_items,
            decisions=decisions,
        )

    def _compute_speaker_stats(self, transcript: Transcript) -> dict:
        by_speaker = transcript.by_speaker()
        total_words = max(
            1,
            sum(len(s.text.split()) for segs in by_speaker.values() for s in segs),
        )
        stats = {}
        for speaker, segments in by_speaker.items():
            text = " ".join(s.text for s in segments)
            words = len(text.split())
            duration = sum(max(0.0, s.end_time - s.start_time) for s in segments)
            stats[speaker] = {
                "word_count": words,
                "duration_s": round(duration, 1),
                "segments": len(segments),
                "percentage": round(100 * words / total_words, 1),
            }
        return stats

    def _content_tokens(self, text: str) -> list[str]:
        """Lowercased tokens that can participate in topics."""
        tokens = re.findall(r"\b[a-zA-Z][a-zA-Z0-9'-]{1,}\b", text.lower())
        out = []
        for t in tokens:
            t = t.strip("'")
            if len(t) < 3:
                continue
            if t in STOP_WORDS or t in TOPIC_BLOCKLIST or t in _VERBISH:
                continue
            if t.isdigit():
                continue
            out.append(t)
        return out

    def _looks_like_noun(self, token: str) -> bool:
        if token.endswith(_NOUN_SUFFIXES):
            return True
        if token.endswith("ing") and len(token) > 5:
            return False  # gerunds are weak topics
        if token.endswith(("ed", "en")) and len(token) > 4:
            return False
        if token.endswith("ly"):
            return False
        return True

    def _extract_topics(self, transcript: Transcript) -> list[TopicSummary]:
        tokens = self._content_tokens(transcript.full_text)
        nouns = [t for t in tokens if self._looks_like_noun(t)]

        unigrams: Counter = Counter()
        for w in nouns:
            unigrams[w] += 1

        bigrams: Counter = Counter()
        for i in range(len(nouns) - 1):
            a, b = nouns[i], nouns[i + 1]
            if a == b:
                continue
            # skip weak pairs
            if a in TOPIC_BLOCKLIST or b in TOPIC_BLOCKLIST:
                continue
            bigrams[(a, b)] += 1

        scores: Counter = Counter()
        for word, c in unigrams.items():
            if c >= 2 or len(word) >= 6:
                scores[word] += c
        for bigram, count in bigrams.items():
            if count >= 1:
                scores[bigram] += count * 3  # prefer multi-word topics

        # Prefer bigrams; keep top unigrams that aren't subsumed
        ranked = scores.most_common(16)
        result: list[TopicSummary] = []
        seen_words: set[str] = set()
        for topic, count in ranked:
            if isinstance(topic, tuple):
                topic_str = f"{topic[0]} {topic[1]}"
                words = set(topic)
            else:
                topic_str = topic
                words = {topic}
            if words & seen_words and isinstance(topic, str):
                continue
            if count < 1:
                continue
            result.append(
                TopicSummary(
                    topic=topic_str,
                    mentions=count,
                    key_phrases=self._find_phrases_for_topic(transcript, topic),
                )
            )
            seen_words |= words
            if len(result) >= 6:
                break
        return result

    def _find_phrases_for_topic(self, transcript: Transcript, topic) -> list[str]:
        if isinstance(topic, tuple):
            search_words = [topic[0], topic[1]]
        else:
            search_words = [topic]

        phrases: list[str] = []
        for _speaker, segments in transcript.by_speaker().items():
            for seg in segments:
                text = seg.text
                if any(w.lower() in text.lower() for w in search_words):
                    for word in search_words:
                        idx = text.lower().find(word.lower())
                        if idx >= 0:
                            start = max(0, idx - 20)
                            end = min(len(text), idx + len(word) + 30)
                            phrase = text[start:end].strip()
                            if 15 < len(phrase) < 120:
                                phrases.append(phrase)
                                break
        return phrases[:3]

    def _extract_key_points(self, transcript: Transcript) -> list[str]:
        sentences = self._split_sentences(transcript.full_text)
        scored: list[tuple[float, str, int]] = []

        for i, sent in enumerate(sentences):
            if len(sent.strip()) < self.min_sentence_length:
                continue
            score = self._score_sentence(sent, i, sentences)
            scored.append((score, sent, i))

        scored.sort(key=lambda x: x[0], reverse=True)
        top = scored[: self.max_sentences]
        top.sort(key=lambda x: x[2])  # chronological
        return [text for _score, text, _i in top]

    def _score_sentence(self, sent: str, index: int, all_sentences: list[str]) -> float:
        score = 0.0
        words = sent.split()

        if 8 <= len(words) <= 25:
            score += 1.0
        elif len(words) > 25:
            score += 2.0

        if index == 0:
            score += 2.0
        if index == len(all_sentences) - 1:
            score += 1.0

        lower = sent.lower()
        for qw in QUESTION_WORDS:
            if lower.startswith(qw + " "):
                score += 1.5

        if re.search(r"\d{4}", sent):
            score += 1.0
        if re.search(r"[A-Z][a-z]+(?:\s[A-Z][a-z]+)+", sent):
            score += 0.5

        word_set = {w.lower().strip(".,!?;:") for w in words}
        score += min(2.0, float(len(word_set & STRONG_WORDS)))

        if "[Speaker" in sent or "Speaker " in sent:
            score += 0.5

        return score

    def _extract_action_items(self, transcript: Transcript) -> list[str]:
        """Heuristic extraction of follow-ups / todos from sentences."""
        items: list[str] = []
        seen: set[str] = set()
        for sent in self._split_sentences(transcript.full_text):
            s = sent.strip()
            if len(s) < 12 or len(s) > 220:
                continue
            if not any(p.search(s) for p in _ACTION_PATTERNS):
                continue
            # skip pure decision phrasing
            if any(p.search(s) for p in _DECISION_PATTERNS) and not re.search(
                r"\b(i'?ll|we'?ll|need to|have to|follow[- ]?up|todo)\b", s, re.I
            ):
                continue
            key = s.lower()
            if key in seen:
                continue
            seen.add(key)
            items.append(s if s.endswith((".", "!", "?")) else s + ".")
            if len(items) >= 12:
                break
        return items

    def _extract_decisions(self, transcript: Transcript) -> list[str]:
        """Heuristic extraction of decisions / agreements."""
        items: list[str] = []
        seen: set[str] = set()
        for sent in self._split_sentences(transcript.full_text):
            s = sent.strip()
            if len(s) < 8 or len(s) > 220:
                continue
            if not any(p.search(s) for p in _DECISION_PATTERNS):
                continue
            key = s.lower()
            if key in seen:
                continue
            seen.add(key)
            items.append(s if s.endswith((".", "!", "?")) else s + ".")
            if len(items) >= 10:
                break
        return items

    def _generate_takeaways(
        self,
        transcript: Transcript,
        topics: list[TopicSummary],
        key_points: list[str],
        action_items: list[str] | None = None,
        decisions: list[str] | None = None,
    ) -> list[str]:
        takeaways: list[str] = []
        action_items = action_items or []
        decisions = decisions or []

        if topics:
            takeaways.append(f"The discussion focused on: {topics[0].topic}")
        elif key_points:
            takeaways.append("The discussion covered several points of interest.")

        if decisions:
            takeaways.append(f"Decisions: {len(decisions)} noted")
            for d in decisions[:2]:
                takeaways.append(f"✓ {d[:100]}")

        if action_items:
            takeaways.append(f"Action items: {len(action_items)} noted")
            for a in action_items[:2]:
                takeaways.append(f"☐ {a[:100]}")

        for kp in key_points[:2]:
            if len(kp) < 80:
                takeaways.append(f"→ {kp}")

        if topics:
            topic_list = ", ".join(f"{t.topic} ({t.mentions})" for t in topics[:4])
            takeaways.append(f"Topics discussed: {topic_list}")

        if transcript.speakers:
            total_words = max(1, sum(len(s.text.split()) for s in transcript.segments))
            for speaker in transcript.speakers:
                speaker_words = sum(
                    len(s.text.split()) for s in transcript.by_speaker().get(speaker, [])
                )
                pct = 100 * speaker_words / total_words
                takeaways.append(f"{speaker}: {pct:.0f}% of the discussion")

        return takeaways[:10]

    def _generate_summary(
        self,
        transcript: Transcript,
        topics: list[TopicSummary],
        key_points: list[str],
    ) -> str:
        parts: list[str] = []

        if topics:
            parts.append(
                f"A conversation among {len(transcript.speakers)} speakers "
                f"discussing {topics[0].topic}."
            )
        elif transcript.speakers:
            parts.append(f"A conversation among {len(transcript.speakers)} speakers.")

        for kp in key_points[:3]:
            parts.append(kp)

        if transcript.duration:
            parts.append(
                f"(Duration: {transcript.duration:.0f}s, {len(transcript.segments)} segments)"
            )

        return " ".join(parts)

    def _split_sentences(self, text: str) -> list[str]:
        sentences = re.split(r"(?<=[.!?])\s+", text)
        return [s.strip() for s in sentences if s.strip()]


# Back-compat alias (prefer HeuristicAnalyzer)
TranscriptAnalyzer = HeuristicAnalyzer
