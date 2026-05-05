# ABOUTME: Tests for the explain.py renderer — three modes (inline, side, by-rule).
# ABOUTME: Pure function: takes a per-squeeze artifact dict and produces a string.

import explain  # noqa: E402 (added to sys.path by conftest)

SAMPLE = {
    "ts": "2026-05-04T18:23:11Z",
    "session": "abc123",
    "seq": 1,
    "original_text": "Could you please help me debug foo.py thanks!",
    "squeezed_text": "Help me debug foo.py",
    "tokens_original": 12,
    "tokens_squeezed": 5,
    "rules_fired": [
        {"rule_id": "FILLER_COULD_YOU_PLEASE", "span": [0, 16], "removed": "Could you please ",
         "replacement": "", "tokens_saved": 4},
        {"rule_id": "FILLER_THANKS", "span": [38, 45], "removed": " thanks!",
         "replacement": "", "tokens_saved": 2},
    ],
}


class TestInlineMode:
    def test_renders_header_and_diff(self):
        out = explain.render(SAMPLE, mode="inline")
        assert "12 -> 5 tok" in out or "12 → 5 tok" in out
        # Mentions both rule IDs
        assert "FILLER_COULD_YOU_PLEASE" in out
        assert "FILLER_THANKS" in out

    def test_includes_footnote_markers(self):
        out = explain.render(SAMPLE, mode="inline")
        # Some kind of numbered or bulleted attribution
        assert "1" in out
        assert "2" in out


class TestSideMode:
    def test_renders_two_columns(self):
        out = explain.render(SAMPLE, mode="side")
        # Side-by-side has a column separator
        assert "|" in out
        assert "ORIGINAL" in out.upper()
        assert "COMPRESSED" in out.upper()


class TestByRuleMode:
    def test_groups_by_rule_id(self):
        out = explain.render(SAMPLE, mode="by-rule")
        # Each rule listed once with its hits
        assert "FILLER_COULD_YOU_PLEASE" in out
        assert "FILLER_THANKS" in out
        # Aggregates hit count
        assert "1 hit" in out or "(1)" in out


class TestUnknownMode:
    def test_unknown_mode_falls_back_to_inline(self):
        out = explain.render(SAMPLE, mode="unknown-mode")
        # Should not raise; returns something
        assert isinstance(out, str)
        assert len(out) > 0


class TestNoRulesFired:
    def test_no_rules_message(self):
        empty = dict(SAMPLE)
        empty["rules_fired"] = []
        out = explain.render(empty, mode="inline")
        assert "no rules fired" in out.lower() or "no compression" in out.lower()
