# ABOUTME: Unit tests for the compression rule registry — Rule dataclass behavior, registry iteration.
# ABOUTME: Integration-level tests of rules-in-pipeline live in test_compress.py.

import re

import rules  # noqa: E402 (added to sys.path by conftest)


class TestRule:
    def test_rule_with_string_replacement(self):
        rule = rules.Rule(
            id="TEST_VERBOSE",
            pattern=r"\bin order to\b",
            replacement="to",
        )
        out, hits = rule.apply("I refactored in order to improve perf")
        assert out == "I refactored to improve perf"
        assert len(hits) == 1
        assert hits[0].rule_id == "TEST_VERBOSE"

    def test_rule_with_callable_replacement(self):
        rule = rules.Rule(
            id="TEST_CALLABLE",
            pattern=r"\bfor the purpose of (\w+ing)\b",
            replacement=lambda m: f"to {m.group(1)[:-3]}",
        )
        out, hits = rule.apply("Wrote it for the purpose of testing the API")
        assert out == "Wrote it to test the API"
        assert len(hits) == 1

    def test_rule_with_context_gate_blocks(self):
        rule = rules.Rule(
            id="TEST_GATED",
            pattern=r"\bplease\b",
            replacement="",
            context_gate=lambda m, full_text: False,
        )
        out, hits = rule.apply("Please help me please")
        assert out == "Please help me please"
        assert hits == []

    def test_rule_with_context_gate_allows(self):
        rule = rules.Rule(
            id="TEST_GATED",
            pattern=r"\bplease\b",
            replacement="",
            context_gate=lambda m, full_text: True,
        )
        out, hits = rule.apply("Please help me please")
        assert out.lower().count("please") == 0
        assert len(hits) == 2

    def test_rule_records_span_and_removed(self):
        rule = rules.Rule(
            id="TEST_FILLER",
            pattern=r"\bplease\b",
            replacement="",
        )
        _out, hits = rule.apply("please fix this")
        assert hits[0].span == (0, 6)
        assert hits[0].removed.lower() == "please"


class TestRegistry:
    def test_apply_all_runs_rules_in_order(self):
        r1 = rules.Rule(id="R1", pattern=r"\bfoo\b", replacement="bar")
        r2 = rules.Rule(id="R2", pattern=r"\bbar\b", replacement="baz")
        registry = [r1, r2]
        out, all_hits = rules.apply_all(registry, "foo")
        assert out == "baz"
        assert [h.rule_id for h in all_hits] == ["R1", "R2"]

    def test_apply_all_collects_hits_across_rules(self):
        r1 = rules.Rule(id="R1", pattern=r"\bplease\b", replacement="", flags=re.IGNORECASE)
        r2 = rules.Rule(id="R2", pattern=r"\bin order to\b", replacement="to", flags=re.IGNORECASE)
        registry = [r1, r2]
        out, hits = rules.apply_all(registry, "Please refactor in order to improve")
        assert "please" not in out.lower()
        assert "in order to" not in out.lower()
        rule_ids = {h.rule_id for h in hits}
        assert rule_ids == {"R1", "R2"}

    def test_apply_all_no_match_no_hits(self):
        r1 = rules.Rule(id="R1", pattern=r"\bnonsense\b", replacement="x")
        out, hits = rules.apply_all([r1], "this text has no matches")
        assert out == "this text has no matches"
        assert hits == []
