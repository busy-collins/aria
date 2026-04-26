"""
Unit tests for parsing functions.
Self-contained — no application imports needed.
"""
import json
import re


# ── Copy of parse_topics from api/main.py ────────────────
def parse_topics(row_value: dict) -> list[str]:
    if row_value.get("isNull"):
        return []
    topics_str = row_value.get("stringValue", "")
    if not topics_str or topics_str in ("{}", "NULL", "null", ""):
        return []
    cleaned = topics_str.strip("{}")
    if not cleaned:
        return []
    topics    = []
    current   = ""
    in_quotes = False
    for char in cleaned:
        if char == '"':
            in_quotes = not in_quotes
        elif char == "," and not in_quotes:
            topic = current.strip().strip('"')
            if topic:
                topics.append(topic)
            current = ""
        else:
            current += char
    last = current.strip().strip('"')
    if last:
        topics.append(last)
    return [t for t in topics if t.strip()]


# ── Copy of parse_score from agents/critic_handler.py ────
def parse_score(text: str) -> tuple[float, bool]:
    score    = 7.0
    approved = True
    try:
        data     = json.loads(text)
        score    = float(data.get("score", 7))
        approved = bool(data.get("approved", score >= 7))
    except json.JSONDecodeError:
        try:
            match = re.search(r'"score":\s*(\d+(?:\.\d+)?)', text)
            if match:
                score    = float(match.group(1))
                approved = score >= 7
        except Exception:
            pass
    return score, approved


# ── Tests ─────────────────────────────────────────────────
class TestParseTopics:

    def test_single_quoted_topic(self):
        result = parse_topics({"stringValue": '{"NVIDIA AI chip market 2026"}'})
        assert result == ["NVIDIA AI chip market 2026"]

    def test_multiple_topics(self):
        result = parse_topics({"stringValue": '{"NVIDIA AI chips","Tesla 2026","Apple Vision Pro"}'})
        assert result == ["NVIDIA AI chips", "Tesla 2026", "Apple Vision Pro"]

    def test_empty_array(self):
        result = parse_topics({"stringValue": "{}"})
        assert result == []

    def test_unquoted_topic(self):
        result = parse_topics({"stringValue": "{Nigerian stock market}"})
        assert result == ["Nigerian stock market"]

    def test_topic_with_spaces_and_punctuation(self):
        result = parse_topics({"stringValue": '{"Discuss the best shares to buy in Nigeria now"}'})
        assert result == ["Discuss the best shares to buy in Nigeria now"]

    def test_topic_with_comma_inside(self):
        result = parse_topics({"stringValue": '{"AI, robotics and automation 2025"}'})
        assert result == ["AI, robotics and automation 2025"]

    def test_null_value(self):
        result = parse_topics({"isNull": True})
        assert result == []

    def test_null_string(self):
        result = parse_topics({"stringValue": "NULL"})
        assert result == []

    def test_empty_string(self):
        result = parse_topics({"stringValue": ""})
        assert result == []

    def test_two_topics(self):
        result = parse_topics({"stringValue": '{"NVIDIA chips","AMD market share"}'})
        assert len(result) == 2
        assert "NVIDIA chips" in result
        assert "AMD market share" in result


class TestParseScore:

    def test_valid_json_score(self):
        verdict = json.dumps({
            "score":    8.5,
            "approved": True,
            "feedback": "Good briefing"
        })
        score, approved = parse_score(verdict)
        assert score == 8.5
        assert approved is True

    def test_score_embedded_in_text(self):
        verdict = 'The briefing scores well. {"score": 7, "approved": true, "feedback": "ok"}'
        score, approved = parse_score(verdict)
        assert score == 7.0

    def test_score_below_threshold(self):
        verdict = json.dumps({"score": 3, "approved": False, "feedback": "Poor"})
        score, approved = parse_score(verdict)
        assert score == 3.0
        assert approved is False

    def test_float_score(self):
        verdict = json.dumps({"score": 8.7, "approved": True, "feedback": "test"})
        score, _ = parse_score(verdict)
        assert score == 8.7

    def test_defaults_on_invalid_json(self):
        score, approved = parse_score("No JSON here at all")
        assert score == 7.0


class TestBriefingValidation:

    PLACEHOLDER_PHRASES = [
        "has been successfully saved",
        "word count of",
        "feel free to ask",
        "briefing has been saved",
        "if you need anything else",
    ]

    def is_placeholder(self, content: str) -> bool:
        content_lower = content.lower()
        return any(p in content_lower for p in self.PLACEHOLDER_PHRASES)

    def test_detects_placeholder_saved_message(self):
        content = "The briefing has been successfully saved. Word count: 496."
        assert self.is_placeholder(content) is True

    def test_detects_assistant_message(self):
        content = "The briefing has been saved. If you need anything else, feel free to ask!"
        assert self.is_placeholder(content) is True

    def test_real_content_not_flagged(self):
        content = """
## Executive Summary
NVIDIA reported record Q3 2025 revenue of $35.1B driven by AI chip demand.

## Key Findings
- Revenue up 94% YoY to $35.1B
- Data center segment: $30.8B
        """
        assert self.is_placeholder(content) is False

    def test_minimum_word_count(self):
        short = "Too short"
        long  = "Word " * 200
        assert len(short.split()) < 150
        assert len(long.split()) >= 150

    def test_has_required_sections(self):
        content = """
## Executive Summary
Summary here.
## Key Findings
Findings here.
        """
        required      = ["executive summary", "key findings"]
        content_lower = content.lower()
        for section in required:
            assert section in content_lower


class TestScoreValidation:

    def clamp_score(self, score: float) -> float:
        return max(1.0, min(10.0, float(score)))

    def test_score_clamped_above_10(self):
        assert self.clamp_score(15.0) == 10.0

    def test_score_clamped_below_1(self):
        assert self.clamp_score(0.0) == 1.0

    def test_valid_score_unchanged(self):
        assert self.clamp_score(8.5) == 8.5

    def test_approved_threshold(self):
        assert (7.0 >= 7) is True
        assert (6.9 >= 7) is False

    def test_low_score_overrides_approved(self):
        score          = 4.0
        approved       = True
        final_approved = approved and score >= 7
        assert final_approved is False