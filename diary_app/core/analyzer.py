"""Analyze transcripts to extract key points, takeaways, and topics."""
import re
from dataclasses import dataclass, field
from collections import Counter

from .transcribe import Transcript, KeyPoints

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
    # filler words
    "um", "uh", "like", "you", "know", "right", "yeah", "yep", "erm",
})

# Important parts-of-speech tags for keyword extraction
NOUN_PRONOUN_TAGS = frozenset({"NN", "NNS", "NNP", "NNPS", "PRP", "PRP$"})
VERB_TAGS = frozenset({"VB", "VBD", "VBG", "VBN", "VBP", "VBZ"})

# Question words that indicate topics of interest
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

@dataclass
class TopicSummary:
    """A single topic found in the transcript."""
    topic: str
    mentions: int
    key_phrases: list[str] = field(default_factory=list)

class TranscriptAnalyzer:
    """Analyzes a transcript to extract key points, takeaways, and topics."""

    def __init__(self, min_sentence_length: int = 5, max_sentences: int = 10):
        self.min_sentence_length = min_sentence_length
        self.max_sentences = max_sentences

    def analyze(self, transcript: Transcript) -> KeyPoints:
        """Run full analysis on a transcript."""
        speaker_stats = self._compute_speaker_stats(transcript)
        topics = self._extract_topics(transcript)
        key_points = self._extract_key_points(transcript)
        takeaways = self._generate_takeaways(transcript, topics)
        summary = self._generate_summary(transcript, topics)

        return KeyPoints(
            summary=summary,
            key_points=key_points,
            takeaways=takeaways,
            topics=[t.topic for t in topics],
            speaker_stats=speaker_stats,
        )

    # ─── Speaker statistics ─────────────────────────────────────────────────

    def _compute_speaker_stats(self, transcript: Transcript) -> dict:
        """Compute per-speaker statistics."""
        by_speaker = transcript.by_speaker()
        stats = {}
        for speaker, segments in by_speaker.items():
            text = " ".join(s.text for s in segments)
            words = len(text.split())
            duration = sum(s.end_time - s.start_time for s in segments)
            stats[speaker] = {
                "word_count": words,
                "duration_s": round(duration, 1),
                "segments": len(segments),
                "percentage": round(
                    100 * words / max(1, sum(len(s.text.split()) for segs in by_speaker.values() for s in segs)), 1
                ),
            }
        return stats

    # ─── Topic extraction ─────────────────────────────────────────────────────

    def _extract_topics(self, transcript: Transcript) -> list[TopicSummary]:
        """Extract main topics using TF-IDF-like scoring on noun phrases."""
        # Tokenize all text and count noun phrases
        words = self._tokenize(transcript.full_text)
        nouns = [w for w, tag in words if tag in NOUN_PRONOUN_TAGS and len(w) > 2 and w.lower() not in STOP_WORDS]

        # Bigrams for noun phrases
        bigrams = Counter()
        for i in range(len(nouns) - 1):
            if nouns[i].lower() not in STOP_WORDS and nouns[i+1].lower() not in STOP_WORDS:
                bigrams[(nouns[i], nouns[i+1])] += 1

        # Score unigrams + bigrams
        scores = Counter()
        for word in nouns:
            scores[word] += 1
        for bigram, count in bigrams.items():
            scores[bigram] += count * 2  # bigrams weighted more

        # Get top topics
        topic_count = max(3, min(len(scores), 8))
        topics = scores.most_common(topic_count)

        result = []
        for topic, count in topics:
            if isinstance(topic, tuple):
                topic_str = f"{topic[0]} {topic[1]}"
            else:
                topic_str = topic
            result.append(TopicSummary(
                topic=topic_str,
                mentions=count,
                key_phrases=self._find_phrases_for_topic(transcript, topic),
            ))

        return result

    def _find_phrases_for_topic(self, transcript: Transcript, topic) -> list[str]:
        """Find relevant phrases in the transcript for a topic."""
        if isinstance(topic, tuple):
            topic_str = f"{topic[0]} {topic[1]}"
            search_words = [topic[0], topic[1]]
        else:
            topic_str = topic
            search_words = [topic]

        phrases = []
        for speaker, segments in transcript.by_speaker().items():
            for seg in segments:
                text = seg.text
                if any(w.lower() in text.lower() for w in search_words):
                    # Extract a window around the keyword
                    for word in search_words:
                        idx = text.lower().find(word.lower())
                        if idx >= 0:
                            start = max(0, idx - 20)
                            end = min(len(text), idx + len(word) + 30)
                            phrase = text[start:end].strip()
                            if len(phrase) > 15 and len(phrase) < 120:
                                phrases.append(phrase)
                                break

        return phrases[:3]  # Limit phrases per topic

    # ─── Key point extraction ─────────────────────────────────────────────────

    def _extract_key_points(self, transcript: Transcript) -> list[str]:
        """Extract the most important sentences from the transcript."""
        # Score sentences
        sentences = self._split_sentences(transcript.full_text)
        scored = []

        for i, sent in enumerate(sentences):
            if len(sent.strip()) < self.min_sentence_length:
                continue
            score = self._score_sentence(sent, i, sentences)
            scored.append((score, sent))

        # Sort by score and take top N
        scored.sort(reverse=True)
        top = scored[:self.max_sentences]
        # Re-sort by position to maintain chronological order
        top.sort(key=lambda x: transcript.full_text.find(x[1]))
        return [text for score, text in top]

    def _score_sentence(self, sent: str, index: int, all_sentences: list[str]) -> float:
        """Score a sentence by its importance."""
        score = 0.0

        # Length: longer sentences tend to be more informative
        words = sent.split()
        if 8 <= len(words) <= 25:
            score += 1.0
        elif len(words) > 25:
            score += 2.0

        # Position: first and last sentences of the transcript
        if index == 0:
            score += 2.0
        if index == len(all_sentences) - 1:
            score += 1.0

        # Presence of question words (often indicate important topics)
        for qw, _ in QUESTION_WORDS.items():
            if sent.lower().startswith(qw + " "):
                score += 1.5

        # Presence of dates, numbers, names
        if re.search(r'\d{4}', sent):
            score += 1.0
        if re.search(r'[A-Z][a-z]+(?:\s[A-Z][a-z]+)+', sent):
            score += 0.5

        # Presence of strong/modifying words
        strong_words = {"important", "crucial", "key", "significant", "must",
                        "should", "need", "really", "definitely", "actually",
                        "first", "last", "only", "best", "worst", "most", "least"}
        word_set = set(w.lower() for w in words)
        score += min(2.0, len(word_set & strong_words))

        # Presence of speaker tags (indicates spoken content)
        if "[Speaker" in sent:
            score += 0.5

        return score

    # ─── Takeaways generation ─────────────────────────────────────────────────

    def _generate_takeaways(self, transcript: Transcript, topics: list[TopicSummary]) -> list[str]:
        """Generate takeaways from the transcript based on key points and topics."""
        key_points = self._extract_key_points(transcript)
        takeaways = []

        # Takeaway 1: Summary sentence
        if key_points:
            takeaways.append(f"The discussion focused on: {topics[0].topic if topics else 'general'}")

        # Takeaway 2: Key decisions/points
        for kp in key_points[:3]:
            if len(kp) < 80:
                takeaways.append(f"→ {kp}")

        # Takeaway 3: Topics discussed
        if topics:
            topic_list = ", ".join(f"{t.topic} ({t.mentions})" for t in topics[:4])
            takeaways.append(f"Topics discussed: {topic_list}")

        # Takeaway 4: Speaker participation
        if transcript.speakers:
            total_words = sum(len(s.text.split()) for s in transcript.segments)
            for speaker in transcript.speakers:
                speaker_words = sum(len(s.text.split()) for s in transcript.by_speaker().get(speaker, []))
                pct = 100 * speaker_words / max(1, total_words)
                takeaways.append(f"{speaker}: {pct:.0f}% of the discussion")

        return takeaways[:6]

    # ─── Summary generation ───────────────────────────────────────────────────

    def _generate_summary(self, transcript: Transcript, topics: list[TopicSummary]) -> str:
        """Generate a brief summary of the discussion."""
        key_points = self._extract_key_points(transcript)
        parts = []

        # Opening
        if topics:
            parts.append(f"A conversation among {len(transcript.speakers)} speakers discussing {topics[0].topic}")

        # Key points
        for kp in key_points[:3]:
            parts.append(kp)

        # Closing
        if transcript.duration:
            parts.append(f"(Duration: {transcript.duration:.0f}s, {len(transcript.segments)} segments)")

        return " ".join(parts)

    # ─── Text processing utilities ────────────────────────────────────────────

    def _tokenize(self, text: str) -> list[tuple[str, str]]:
        """Simple tokenization with POS tags (basic version)."""
        # Basic tokenization — for production, use nltk
        tokens = re.findall(r"\b\w+\b|[^\w\s]", text.lower())
        # Simple heuristic POS tagging
        tags = []
        prev_is_noun = False
        for token in tokens:
            if token in STOP_WORDS or len(token) < 2:
                tags.append((token, ""))
                continue
            # Heuristic: words starting with lowercase and ending with 'tion', 'ment', 'ness', etc.
            if token.endswith(("tion", "ment", "ness", "ship", "ing", "ment", "er", "or", "ance", "ence", "ity", "ty")):
                tag = "NN"
            elif token.endswith("ly"):
                tag = "RB"
            elif token.endswith(("ed", "en")) and not token.endswith("ed") and len(token) > 3:
                tag = "VBD"
            elif token.endswith("s") and token not in ("us", "is", "as"):
                tag = "NNS"
            elif token.startswith("r"):
                tag = "RB"
            elif token in ("is", "are", "was", "were", "have", "has", "had", "do", "does", "did",
                          "will", "would", "should", "could", "can", "may", "might", "must"):
                tag = "VB"
            else:
                tag = "NN" if not prev_is_noun else ""
            if tag:
                prev_is_noun = tag in NOUN_PRONOUN_TAGS
            tags.append((token, tag))
        return tags

    def _split_sentences(self, text: str) -> list[str]:
        """Split text into sentences."""
        # Split on sentence-ending punctuation
        sentences = re.split(r'(?<=[.!?])\s+', text)
        return [s.strip() for s in sentences if s.strip()]
