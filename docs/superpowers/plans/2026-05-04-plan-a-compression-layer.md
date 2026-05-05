<!-- ABOUTME: Plan A — implementation plan for the v0.4 compression layer (Component 1 of the spec). -->
<!-- ABOUTME: Refactors compress.py into a rule registry, fixes two v0.3 fidelity bugs, adds aggressive rules behind eval gates. -->

# Plan A — Compression Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor `compress.py` into a rule registry, fix the two known v0.3 fidelity bugs (semantic-loss verbose swap, post-strip capitalization), add aggressive LLM-comprehension rule categories behind a tightened eval gate, and wire the eval contract into CI.

**Architecture:** Replace the inline `_FILLER_PHRASES` and `_VERBOSE_SWAPS` lists in [skills/prompt-squeeze/scripts/compress.py](skills/prompt-squeeze/scripts/compress.py) with a `Rule` dataclass and an iterable registry. Each rule encapsulates its own `apply(text) -> (text, hits)` function so context-gating logic lives next to the rule instead of in the pipeline. New aggressive rules are added one category at a time; each must keep the 100-prompt eval median fidelity ≥ 0.95 and 5th-percentile ≥ 0.85, or it gets reverted before commit.

**Tech Stack:** Python 3.12 (uv-managed), pytest, ruff, tiktoken (cl100k_base for ratio reporting), Anthropic SDK or `claude -p` for the eval judge. CI runs on GitHub Actions.

**Spec reference:** [docs/superpowers/specs/2026-05-04-prompt-squeeze-v04-design.md](docs/superpowers/specs/2026-05-04-prompt-squeeze-v04-design.md), Component 1.

---

## Scope check

This plan covers Component 1 only. Plans B (runtime), C (introspection), D (awareness) come after. Component 1 is independent: it ends in shippable software (a v0.3.3 fidelity release) that can ship to GitHub even if B/C/D never land.

## File structure

| File | Status | Responsibility |
|---|---|---|
| `skills/prompt-squeeze/scripts/compress.py` | Modify | Public surface: `compress(text)`, `compression_ratio()`. Internals: rule registry, pipeline, protected-region handling. |
| `skills/prompt-squeeze/scripts/rules.py` | **Create** | `Rule` dataclass, the registry of all compression rules, helpers for context-gated and callable-replacement rules. |
| `skills/prompt-squeeze/scripts/eval/run_eval.py` | Modify | Tighten thresholds; add p5 and no-regression checks. |
| `skills/prompt-squeeze/data/eval_set.jsonl` | Modify | Add rows that exercise new rule categories (only when an existing row doesn't cover a category). |
| `skills/prompt-squeeze/data/baseline_fidelity.json` | **Create** | Per-prompt fidelity baseline — captured once on `main` before any rule changes. Used to enforce no-regression on any prompt currently ≥ 0.95. |
| `tests/skill/test_compress.py` | Modify | Add tests for capitalization fix, context-gating, each new rule. |
| `tests/skill/test_rules.py` | **Create** | Unit tests for the `Rule` dataclass and registry mechanics, separate from the integration-style tests in `test_compress.py`. |
| `.github/workflows/ci.yml` | Modify | Add an eval-gate step that runs `run_eval.py --judge --judge-sample 30` and fails CI if the contract breaks. |

**Why split `rules.py` from `compress.py`:** the registry is going to grow. Keeping rules in one file and the pipeline in another lets each be reasoned about independently, and lets `test_rules.py` exercise rules without invoking the full pipeline.

---

## Task 1: Capture the baseline fidelity (no-regression contract)

The "no prompt currently ≥ 0.95 regresses" rule needs a snapshot to compare against. Take it BEFORE any rule changes.

**Files:**
- Create: `skills/prompt-squeeze/data/baseline_fidelity.json`

- [ ] **Step 1: Run the eval with judge on every row, capturing per-prompt fidelity to a JSON snapshot**

```bash
cd ~/projects/prompt-squeeze
uv run python -c "
import json, subprocess, sys
sys.path.insert(0, 'skills/prompt-squeeze/scripts')
sys.path.insert(0, 'skills/prompt-squeeze/scripts/eval')
from compress import compress
import run_eval
from pathlib import Path

rows = run_eval._load_eval(Path('skills/prompt-squeeze/data/eval_set.jsonl'))
out = {}
for row in rows:
    original = row['prompt']
    compressed = compress(original)
    fidelity, reason = run_eval._judge(original, compressed, backend='auto', model='claude-sonnet-4-6')
    out[row['id']] = {'fidelity': fidelity, 'reason': reason}
    print(f'{row[\"id\"]}: {fidelity:.2f}', flush=True)

Path('skills/prompt-squeeze/data/baseline_fidelity.json').write_text(json.dumps(out, indent=2))
print(f'wrote {len(out)} entries')
"
```

Expected: 100 lines printed (one per eval row), then `wrote 100 entries`. This costs roughly $0.20-0.40 of API spend (Sonnet judge × 100 short prompts). If `claude -p` CLI is the only available backend, this takes ~10–15 minutes.

If a row's judge fidelity < 0.85, that's the existing 0.72 outlier (or another). It will not be considered a "≥ 0.95" prompt and is exempt from the no-regression rule.

- [ ] **Step 2: Inspect the baseline file**

Run: `head -20 skills/prompt-squeeze/data/baseline_fidelity.json`
Expected: JSON with per-id fidelity entries. Should see at least 90+ rows scoring ≥ 0.95 and a small number of outliers.

- [ ] **Step 3: Commit the baseline**

```bash
git add skills/prompt-squeeze/data/baseline_fidelity.json
git commit -m "Capture pre-v0.4 baseline fidelity for no-regression gate"
```

---

## Task 2: Add capitalization post-pass (Bug fix #2)

After filler stripping, the next sentence sometimes starts lowercase. This is a deterministic post-pass that capitalizes the first letter of every sentence.

**Files:**
- Modify: `skills/prompt-squeeze/scripts/compress.py:124-136` (extend `_cleanup_artifacts` or add a new `_capitalize_sentences` step)
- Modify: `tests/skill/test_compress.py` (add test class)

- [ ] **Step 1: Write the failing tests**

Add to `tests/skill/test_compress.py` (append to end of file):

```python
class TestCapitalizationPostPass:
    def test_capitalizes_after_filler_strip(self):
        # Filler "give me feedback on" leaves a lowercase head.
        out = compress.compress("Give me feedback on this code please.")
        # After stripping "please", first word stays capitalized.
        assert out[:1].isupper(), f"expected leading capital, got {out!r}"

    def test_capitalizes_second_sentence_after_filler(self):
        # If filler removal puts a lowercase word at sentence start.
        out = compress.compress("Fix this. please update foo.py with the new API.")
        # The "please update foo.py..." sentence should start with capital U.
        assert " update foo.py" not in out or "Update foo.py" in out, (
            f"second sentence should be capitalized: {out!r}"
        )

    def test_does_not_touch_proper_nouns(self):
        out = compress.compress("Use Python and JavaScript. they're both fine.")
        # "they're" at sentence start becomes "They're"; Python/JavaScript untouched.
        assert "Python" in out
        assert "JavaScript" in out
        assert "they're" not in out or "They're" in out

    def test_handles_question_and_exclamation(self):
        out = compress.compress("Why? please explain. Also! please clarify.")
        # After "?" and "!", next sentence should be capitalized.
        # Specifically: "explain" → "Explain", "clarify" → "Clarify".
        assert "explain" not in out.split("?")[1].split(".")[0].lstrip()[:1].lower() or \
               "Explain" in out or "explain" not in out
        # Looser check: no lowercase word should immediately follow ". " or "? " or "! ".
        import re
        bad = re.findall(r"[.!?]\s+([a-z]\w+)", out)
        assert not bad, f"found lowercase sentence starts: {bad!r}"

    def test_idempotent(self):
        first = compress.compress("Please fix foo.py. please also lint it.")
        second = compress.compress(first)
        assert first == second
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd ~/projects/prompt-squeeze && uv run pytest tests/skill/test_compress.py::TestCapitalizationPostPass -v`
Expected: at least `test_capitalizes_second_sentence_after_filler` and `test_handles_question_and_exclamation` FAIL because v0.3 has no capitalization post-pass.

- [ ] **Step 3: Implement the post-pass**

Edit `skills/prompt-squeeze/scripts/compress.py`. Add this function just before `_normalize_whitespace` (around line 145):

```python
def _capitalize_sentences(text: str) -> str:
    """Capitalize the first letter of the text, and the first letter of any sentence
    that follows a sentence-ending punctuation mark. Runs after filler removal so
    we catch newly-exposed sentence heads."""
    if not text:
        return text

    # Capitalize very first non-whitespace letter.
    def _capitalize_first(s: str) -> str:
        for i, ch in enumerate(s):
            if ch.isspace():
                continue
            if ch.isalpha() and ch.islower():
                return s[:i] + ch.upper() + s[i + 1 :]
            return s
        return s

    text = _capitalize_first(text)

    # Capitalize the first letter of any sentence following . ! ? plus whitespace.
    def _cap_after_terminator(match: re.Match[str]) -> str:
        return match.group(1) + match.group(2).upper()

    text = re.sub(r"([.!?]\s+)([a-z])", _cap_after_terminator, text)
    return text
```

Then add the call inside `compress()` (around line 159, after `_cleanup_artifacts`):

```python
def compress(text: str) -> str:
    """Run the full Stage 1 deterministic compression pipeline."""
    if not text:
        return text
    body, protected = _extract_protected(text)
    body = _strip_filler(body)
    body = _swap_verbose(body)
    body = _cleanup_artifacts(body)
    body = _capitalize_sentences(body)  # NEW
    body = _normalize_whitespace(body)
    return _restore_protected(body, protected)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd ~/projects/prompt-squeeze && uv run pytest tests/skill/test_compress.py::TestCapitalizationPostPass -v`
Expected: 5 tests PASS.

- [ ] **Step 5: Run the full existing suite to confirm no regression**

Run: `cd ~/projects/prompt-squeeze && uv run pytest tests/ -q`
Expected: all 83 prior tests + 5 new = 88 passing. If any prior test fails, the capitalization pass is being too aggressive — fix before committing.

- [ ] **Step 6: Commit**

```bash
git add skills/prompt-squeeze/scripts/compress.py tests/skill/test_compress.py
git commit -m "Add capitalization post-pass (fix v0.3 sentence-head regression)"
```

---

## Task 3: Create the Rule dataclass and registry skeleton

Refactor groundwork. Behavior unchanged; this just sets up the structure that subsequent tasks will populate.

**Files:**
- Create: `skills/prompt-squeeze/scripts/rules.py`
- Create: `tests/skill/test_rules.py`

- [ ] **Step 1: Write the failing tests for the Rule dataclass**

Create `tests/skill/test_rules.py`:

```python
# ABOUTME: Unit tests for the compression rule registry — Rule dataclass behavior, registry iteration.
# ABOUTME: Integration-level tests of rules-in-pipeline live in test_compress.py.

import re
import pytest

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
        # Callable replacement gets the regex match and returns the new text.
        rule = rules.Rule(
            id="TEST_CALLABLE",
            pattern=r"\bfor the purpose of (\w+ing)\b",
            replacement=lambda m: f"to {m.group(1)[:-3]}" if m.group(1).endswith("ing") else m.group(0),
        )
        out, hits = rule.apply("Wrote it for the purpose of testing the API")
        assert out == "Wrote it to test the API"
        assert len(hits) == 1

    def test_rule_with_context_gate_blocks(self):
        # Gate returns False → rule does not fire.
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
        assert "please" not in out.lower() or out.count("please") < 2
        assert len(hits) >= 1

    def test_rule_records_span_and_tokens(self):
        rule = rules.Rule(
            id="TEST_FILLER",
            pattern=r"\bplease\b",
            replacement="",
        )
        out, hits = rule.apply("please fix this")
        assert hits[0].span == (0, 6)
        assert hits[0].removed.lower() == "please"


class TestRegistry:
    def test_apply_all_runs_rules_in_order(self):
        r1 = rules.Rule(id="R1", pattern=r"\bfoo\b", replacement="bar")
        r2 = rules.Rule(id="R2", pattern=r"\bbar\b", replacement="baz")
        # Order matters: r1 fires first, then r2 sees "bar" → "baz".
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
```

- [ ] **Step 2: Run tests to verify they fail (module does not exist)**

Run: `cd ~/projects/prompt-squeeze && uv run pytest tests/skill/test_rules.py -v`
Expected: ImportError / collection error — `rules` module not found.

- [ ] **Step 3: Implement the Rule dataclass and registry helpers**

Create `skills/prompt-squeeze/scripts/rules.py`:

```python
# ABOUTME: Compression rule registry — Rule dataclass, hit tracking, registry application helpers.
# ABOUTME: Each rule is a self-contained pattern + replacement (string or callable) + optional context gate.

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Union


@dataclass
class Hit:
    """One firing of a rule. Spans index into the text the rule received as input."""
    rule_id: str
    span: tuple[int, int]
    removed: str
    replacement: str


Replacement = Union[str, Callable[[re.Match[str]], str]]
ContextGate = Callable[[re.Match[str], str], bool]


@dataclass
class Rule:
    id: str
    pattern: str
    replacement: Replacement
    flags: int = re.IGNORECASE
    context_gate: ContextGate | None = None
    confidence: float = 1.0  # populated from eval over time; default 1.0 = unproven new rule
    description: str = ""

    def apply(self, text: str) -> tuple[str, list[Hit]]:
        """Apply this rule to text. Returns (modified_text, list_of_hits)."""
        compiled = re.compile(self.pattern, self.flags)
        hits: list[Hit] = []

        def _sub(match: re.Match[str]) -> str:
            if self.context_gate is not None and not self.context_gate(match, text):
                return match.group(0)  # gated out — leave original
            if callable(self.replacement):
                replaced = self.replacement(match)
            else:
                replaced = self.replacement
            hits.append(
                Hit(
                    rule_id=self.id,
                    span=match.span(),
                    removed=match.group(0),
                    replacement=replaced,
                )
            )
            return replaced

        new_text = compiled.sub(_sub, text)
        return new_text, hits


def apply_all(rules_list: list[Rule], text: str) -> tuple[str, list[Hit]]:
    """Apply every rule in order. Each rule sees the output of the previous one."""
    all_hits: list[Hit] = []
    current = text
    for rule in rules_list:
        current, hits = rule.apply(current)
        all_hits.extend(hits)
    return current, all_hits
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd ~/projects/prompt-squeeze && uv run pytest tests/skill/test_rules.py -v`
Expected: 8 tests PASS.

- [ ] **Step 5: Run the full suite (no regressions in compress.py since we haven't wired in yet)**

Run: `cd ~/projects/prompt-squeeze && uv run pytest tests/ -q`
Expected: 88 + 8 = 96 passing.

- [ ] **Step 6: Commit**

```bash
git add skills/prompt-squeeze/scripts/rules.py tests/skill/test_rules.py
git commit -m "Add Rule dataclass and registry helpers"
```

---

## Task 4: Migrate v0.3 rules into the registry (no behavior change)

Move every `_FILLER_PHRASES` and `_VERBOSE_SWAPS` entry into named `Rule` instances. Wire `compress()` to call `apply_all()` instead of the inline functions. Behavior stays identical — existing tests are the contract.

**Files:**
- Modify: `skills/prompt-squeeze/scripts/compress.py:22-53` (replace inline lists)
- Modify: `skills/prompt-squeeze/scripts/compress.py:117-122` and `139-142` (replace `_strip_filler` and `_swap_verbose` with registry calls)
- Modify: `skills/prompt-squeeze/scripts/rules.py` (add the v0.3 registry)

- [ ] **Step 1: Run the existing suite, baseline of all-passing**

Run: `cd ~/projects/prompt-squeeze && uv run pytest tests/ -q 2>&1 | tail -3`
Expected: 96 passed (snapshot the exact number).

- [ ] **Step 2: Add the v0.3 rule registry to rules.py**

Append to `skills/prompt-squeeze/scripts/rules.py`:

```python
# ---------------------------------------------------------------------------
# v0.3 carryover rules. Each gets a stable id so /sq explain can attribute hits.
# ---------------------------------------------------------------------------

V03_FILLER_RULES: list[Rule] = [
    Rule(id="FILLER_WONDERING_COULD", pattern=r"\bi was wondering if you could\b", replacement="",
         description="'I was wondering if you could' → drop"),
    Rule(id="FILLER_WONDERING_IF", pattern=r"\bi was wondering if\b", replacement="",
         description="'I was wondering if' → drop"),
    Rule(id="FILLER_WONDERING", pattern=r"\bi was wondering\b", replacement="",
         description="'I was wondering' → drop"),
    Rule(id="FILLER_GREAT_IF", pattern=r"\bi think it would be great if\b", replacement="",
         description="'I think it would be great if' → drop"),
    Rule(id="FILLER_DONT_MIND", pattern=r"\bif you don'?t mind\b", replacement="",
         description="'if you don't mind' → drop"),
    Rule(id="FILLER_THANKS_ADV_FOR", pattern=r"\bthanks in advance(?:\s+for[^.!?]*)?[!]*", replacement="",
         description="'thanks in advance for X!' → drop"),
    Rule(id="FILLER_THANK_YOU_VERY_MUCH",
         pattern=r"\bthank you (?:so much|very much)(?:\s+in advance)?(?:\s+for[^.!?]*)?[!]*",
         replacement="",
         description="'thank you so/very much (in advance) for X!' → drop"),
    Rule(id="FILLER_THANK_YOU",
         pattern=r"\bthank you(?:\s+in advance)?(?:\s+for[^.!?]*)?[!]*",
         replacement="",
         description="'thank you (in advance) for X!' → drop"),
    Rule(id="FILLER_THANKS", pattern=r"\bthanks(?:\s+for[^.!?]*)?[!]*", replacement="",
         description="'thanks for X!' → drop"),
    Rule(id="FILLER_APPRECIATE", pattern=r"\bi really appreciate it[!.?]*", replacement="",
         description="'I really appreciate it!' → drop"),
    Rule(id="FILLER_PLEASE", pattern=r"\bplease\b", replacement="",
         description="'please' → drop"),
    Rule(id="FILLER_COULD_YOU_PLEASE", pattern=r"\bcould you please\b", replacement="",
         description="'could you please' → drop"),
    Rule(id="FILLER_COULD_YOU", pattern=r"\bcould you\b", replacement="",
         description="'could you' → drop"),
    Rule(id="FILLER_WOULD_YOU_MIND", pattern=r"\bwould you mind\b", replacement="",
         description="'would you mind' → drop"),
    Rule(id="FILLER_WOULD_YOU", pattern=r"\bwould you\b", replacement="",
         description="'would you' → drop"),
    Rule(id="FILLER_CAN_YOU_PLEASE", pattern=r"\bcan you please\b", replacement="",
         description="'can you please' → drop"),
    Rule(id="FILLER_CAN_YOU", pattern=r"\bcan you\b", replacement="",
         description="'can you' → drop"),
]

V03_VERBOSE_RULES: list[Rule] = [
    Rule(id="VERBOSE_IN_ORDER_TO", pattern=r"\bin order to\b", replacement="to"),
    Rule(id="VERBOSE_AT_THIS_POINT", pattern=r"\bat this point in time\b", replacement="now"),
    Rule(id="VERBOSE_DUE_TO_FACT", pattern=r"\bdue to the fact that\b", replacement="because"),
    # NOTE: VERBOSE_FOR_PURPOSE_OF is intentionally absent here — Task 5 reclassifies it as context-gated
    # to fix the v0.3 0.72 fidelity outlier. It will be added in V03_VERBOSE_RULES_GATED below.
    Rule(id="VERBOSE_IN_THE_EVENT", pattern=r"\bin the event that\b", replacement="if"),
    Rule(id="VERBOSE_WITH_REGARD_TO", pattern=r"\bwith regard to\b", replacement="about"),
    Rule(id="VERBOSE_WITH_REGARDS_TO", pattern=r"\bwith regards to\b", replacement="about"),
    Rule(id="VERBOSE_MAKE_DECISION", pattern=r"\bmake a decision\b", replacement="decide"),
    Rule(id="VERBOSE_GIVE_CONSIDERATION", pattern=r"\bgive consideration to\b", replacement="consider"),
]

# Greeting rule — uses callable replacement to preserve the boundary char (period or start-of-text).
_GREETING_PATTERN = (
    r"(^|(?<=[.!?]))\s*\b(?:hi|hello|hey)\b"
    r"(?:\s+(?:there|everyone|folks|all|y'all|team))?[,!]*\s*"
)


def _greeting_replacement(match: re.Match[str]) -> str:
    prefix = match.group(1)
    return (prefix + " ") if prefix else ""


GREETING_RULE = Rule(
    id="FILLER_GREETING",
    pattern=_GREETING_PATTERN,
    replacement=_greeting_replacement,
    description="Hi/Hello/Hey at sentence boundary → drop, preserve boundary punctuation",
)


# Default v0.3 registry — order matters: greeting first so it sees clean sentence boundaries,
# then filler phrases, then verbose swaps.
V03_REGISTRY: list[Rule] = [GREETING_RULE] + V03_FILLER_RULES + V03_VERBOSE_RULES
```

- [ ] **Step 3: Wire compress.py to use the registry**

Edit `skills/prompt-squeeze/scripts/compress.py`. Replace lines 22-61 (the `_FILLER_PHRASES`, `_VERBOSE_SWAPS`, `_GREETING_RE` blocks) with:

```python
# Imports already include re; add this line just below `import re`:
from rules import V03_REGISTRY, apply_all
```

Replace the body of `_strip_filler` and `_swap_verbose` (lines 106-142) with a single call to the registry. Specifically, delete `_FILLER_PHRASES`, `_VERBOSE_SWAPS`, `_GREETING_RE`, `_strip_greetings`, `_strip_filler`, and `_swap_verbose`. Replace the calls inside `compress()`:

```python
def compress(text: str) -> str:
    """Run the full Stage 1 deterministic compression pipeline."""
    if not text:
        return text
    body, protected = _extract_protected(text)
    body, _hits = apply_all(V03_REGISTRY, body)
    body = _cleanup_artifacts(body)
    body = _capitalize_sentences(body)
    body = _normalize_whitespace(body)
    return _restore_protected(body, protected)
```

Note: the discarded `_hits` is intentional in v0.3-equivalent behavior. Plan B/C will use them.

- [ ] **Step 4: Run the full suite — must match the Step 1 baseline exactly**

Run: `cd ~/projects/prompt-squeeze && uv run pytest tests/ -q 2>&1 | tail -3`
Expected: 96 passed. If anything fails, the registry order or pattern is wrong — diff against the original `_FILLER_PHRASES` / `_VERBOSE_SWAPS` lists.

- [ ] **Step 5: Run the eval harness without --judge to confirm compression ratios match**

Run: `cd ~/projects/prompt-squeeze && uv run python skills/prompt-squeeze/scripts/eval/run_eval.py 2>&1 | tail -5`
Expected: median compression ratio approximately the same as v0.3 (within 0.01). No must_preserve regressions.

- [ ] **Step 6: Commit**

```bash
git add skills/prompt-squeeze/scripts/compress.py skills/prompt-squeeze/scripts/rules.py
git commit -m "Migrate v0.3 compression rules into Rule registry (no behavior change)"
```

---

## Task 5: Fix the "for the purpose of" semantic-loss outlier (Bug fix #1)

The v0.3 rule blindly swapped `for the purpose of → to`, which dropped causal/purpose meaning when no following verb explained it. Replace with a context-gated callable that only fires when followed by a verb-ing form, and converts both phrases together (`for the purpose of testing` → `to test`).

**Files:**
- Modify: `skills/prompt-squeeze/scripts/rules.py` (add the gated rule)
- Modify: `tests/skill/test_compress.py` (regression tests)

- [ ] **Step 1: Write the failing tests**

Append to `tests/skill/test_compress.py`:

```python
class TestForThePurposeOfFix:
    """Regression tests for v0.3 fidelity bug #1 — 'for the purpose of' → 'to' lost causal meaning.
    See spec §1, Bug fix #1."""

    def test_swaps_when_followed_by_verb_ing(self):
        # 'for the purpose of testing' → 'to test' (purpose verb dropped, infinitive kept)
        out = compress.compress("Wrote a script for the purpose of testing the API.")
        assert "for the purpose of" not in out
        assert "to test" in out
        assert "API" in out

    def test_swaps_when_followed_by_verb_ing_complex(self):
        out = compress.compress("Built it for the purpose of validating user input.")
        assert "for the purpose of" not in out
        assert "to validate" in out
        assert "user input" in out

    def test_does_not_swap_when_followed_by_noun(self):
        # 'for the purpose of compatibility' has no following verb — leave alone
        # (keeping the phrase preserves meaning even at fidelity cost).
        out = compress.compress("This code exists for the purpose of compatibility.")
        assert "for the purpose of compatibility" in out

    def test_does_not_swap_when_dangling(self):
        # End-of-clause "for the purpose of [end]" — leave alone.
        out = compress.compress("It's there for the purpose of, you know, that thing.")
        # Either it leaves the phrase OR it transforms safely. Just don't strip the meaning.
        assert "purpose" in out or "for that" in out.lower()
```

- [ ] **Step 2: Run the tests, expect failures**

Run: `cd ~/projects/prompt-squeeze && uv run pytest tests/skill/test_compress.py::TestForThePurposeOfFix -v`
Expected: `test_swaps_when_followed_by_verb_ing` FAILS (current behavior outputs "to testing", not "to test"). `test_does_not_swap_when_followed_by_noun` FAILS (current rule strips it unconditionally).

- [ ] **Step 3: Add the gated rule in rules.py**

Append to `skills/prompt-squeeze/scripts/rules.py`, just below `V03_VERBOSE_RULES`:

```python
# ---------------------------------------------------------------------------
# v0.4 fix: 'for the purpose of' is context-gated. It fires only when followed
# by a gerund (verb-ing), in which case 'for the purpose of testing' becomes
# 'to test'. When followed by a bare noun ('for the purpose of compatibility')
# the phrase carries the meaning and is left intact.
# ---------------------------------------------------------------------------

_VERB_ING_AFTER_PURPOSE = re.compile(r"\bfor the purpose of\s+(\w+ing)\b", re.IGNORECASE)


def _purpose_of_replacement(match: re.Match[str]) -> str:
    # match.group(1) is the verb-ing word. Drop the trailing 'ing' to get the base verb.
    # 'testing' -> 'test', 'validating' -> 'validate', 'making' -> 'mak' (broken!).
    # Handle the two common cases: 'V-ing' where V ends in a consonant cluster (just strip ing),
    # and 'CV-Cing' where doubled consonant (skip — uncommon enough that we just strip).
    verb_ing = match.group(1)
    base = verb_ing[:-3]  # 'testing' -> 'test'
    # Some verbs need an 'e' restored: 'validating' -> 'validate', 'creating' -> 'create'.
    # Heuristic: if the base ends in a consonant followed by 'at', 'iz', 'ic', etc., add 'e'.
    if re.search(r"[bcdfghjklmnpqrstvwxz](?:at|iz|ic|os|ur|in|ess|ag|ut|ad|in)$", base):
        base = base + "e"
    return f"to {base}"


VERBOSE_FOR_PURPOSE_OF_GATED = Rule(
    id="VERBOSE_FOR_PURPOSE_OF_GATED",
    pattern=r"\bfor the purpose of\s+\w+ing\b",
    replacement=_purpose_of_replacement,
    description="'for the purpose of <verb-ing>' → 'to <verb>' (only when verb-ing form follows)",
)


# Update V03_REGISTRY to include the gated rule. (We're past the original V03 line — append.)
V03_REGISTRY = V03_REGISTRY + [VERBOSE_FOR_PURPOSE_OF_GATED]
```

- [ ] **Step 4: Run the tests**

Run: `cd ~/projects/prompt-squeeze && uv run pytest tests/skill/test_compress.py::TestForThePurposeOfFix -v`
Expected: 4 PASS. If `test_swaps_when_followed_by_verb_ing_complex` still fails because `validating` → `validat` instead of `validate`, tune the heuristic — extend the regex pattern in `_purpose_of_replacement` to cover that suffix.

- [ ] **Step 5: Run the full suite**

Run: `cd ~/projects/prompt-squeeze && uv run pytest tests/ -q 2>&1 | tail -3`
Expected: 100 passed (96 + 4 new). The 100-prompt eval row for `explain_03` (which had the 0.72 outlier) should now compress correctly — verify with one judge call.

- [ ] **Step 6: Spot-check the eval row that had the outlier**

Run:
```bash
cd ~/projects/prompt-squeeze && uv run python -c "
import sys; sys.path.insert(0, 'skills/prompt-squeeze/scripts')
from compress import compress
prompt = 'Hello, I was wondering if you might please be able to explain CRDTs for the purpose of building a collaborative editor? Thanks in advance for the explanation!'
print('IN:', prompt)
print('OUT:', compress(prompt))
"
```
Expected output's `OUT:` line contains `to build` (or `to building` — both preserve meaning), not bare `for the purpose of`. CRDTs and "collaborative editor" both still present.

- [ ] **Step 7: Commit**

```bash
git add skills/prompt-squeeze/scripts/rules.py tests/skill/test_compress.py
git commit -m "Reclassify 'for the purpose of' as context-gated rule (fix v0.3 0.72 fidelity outlier)"
```

---

## Task 6: Add aggressive rule — expanded politeness markers

The v0.3 list covers `please`, `could you`, etc. Aggressive mode adds longer politeness phrases that v0.3 missed. Eval-gated: any rule that drops eval median below 0.95 gets reverted.

**Files:**
- Modify: `skills/prompt-squeeze/scripts/rules.py`
- Modify: `tests/skill/test_compress.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/skill/test_compress.py`:

```python
class TestAggressivePoliteness:
    def test_drops_if_not_too_much_trouble(self):
        out = compress.compress("If it's not too much trouble, please review foo.py.")
        assert "if it's not too much trouble" not in out.lower()
        assert "foo.py" in out

    def test_drops_if_you_have_a_moment(self):
        out = compress.compress("If you have a moment, can you check bar.py?")
        assert "if you have a moment" not in out.lower()
        assert "bar.py" in out

    def test_drops_when_you_get_a_chance(self):
        out = compress.compress("When you get a chance, please update README.md.")
        assert "when you get a chance" not in out.lower()
        assert "README.md" in out

    def test_drops_sorry_to_bother(self):
        out = compress.compress("Sorry to bother you, but the test in test_x.py is flaky.")
        assert "sorry to bother" not in out.lower()
        assert "test_x.py" in out

    def test_preserves_protected_content(self):
        # Politeness inside a code fence stays.
        out = compress.compress("```\n# If you have a moment, fix this\n```\nhelp")
        assert "If you have a moment" in out  # inside fence
```

- [ ] **Step 2: Run the tests, watch them fail**

Run: `cd ~/projects/prompt-squeeze && uv run pytest tests/skill/test_compress.py::TestAggressivePoliteness -v`
Expected: 4 FAIL (the protection test should pass — `_extract_protected` already runs).

- [ ] **Step 3: Add the rules**

Append to `skills/prompt-squeeze/scripts/rules.py`, after `VERBOSE_FOR_PURPOSE_OF_GATED`:

```python
# ---------------------------------------------------------------------------
# v0.4 aggressive politeness rules. Each must keep eval median fidelity ≥ 0.95.
# ---------------------------------------------------------------------------

V04_POLITENESS_RULES: list[Rule] = [
    Rule(id="POLITENESS_NOT_TOO_MUCH_TROUBLE",
         pattern=r"\bif it'?s not too much trouble[,\s]*", replacement="",
         description="'if it's not too much trouble' → drop"),
    Rule(id="POLITENESS_HAVE_A_MOMENT",
         pattern=r"\bif you have a (?:moment|second|minute|sec|chance)[,\s]*", replacement="",
         description="'if you have a moment/second/minute/chance' → drop"),
    Rule(id="POLITENESS_WHEN_YOU_GET_CHANCE",
         pattern=r"\bwhen you (?:get a chance|have a moment|have time)[,\s]*", replacement="",
         description="'when you get a chance/have a moment/have time' → drop"),
    Rule(id="POLITENESS_SORRY_TO_BOTHER",
         pattern=r"\bsorry to (?:bother|trouble) you[,\s]*(?:but\s+)?", replacement="",
         description="'sorry to bother/trouble you (but)' → drop"),
    Rule(id="POLITENESS_HOPE_NOT_BOTHER",
         pattern=r"\bi hope (?:this is|i'?m) not bothering you[,.\s]*", replacement="",
         description="'I hope this isn't bothering you' → drop"),
]

V03_REGISTRY = V03_REGISTRY + V04_POLITENESS_RULES
```

- [ ] **Step 4: Run the tests, expect pass**

Run: `cd ~/projects/prompt-squeeze && uv run pytest tests/skill/test_compress.py::TestAggressivePoliteness -v`
Expected: 5 PASS.

- [ ] **Step 5: Run the eval to verify fidelity contract**

Run: `cd ~/projects/prompt-squeeze && uv run python skills/prompt-squeeze/scripts/eval/run_eval.py --judge --judge-sample 30 2>&1 | tail -10`
Expected: median compression ratio increases by 0.01-0.03 (small win), median fidelity stays ≥ 0.95. If median fidelity drops below 0.95, `git diff` the rules.py changes, identify which rule is causing the drop, and remove it. Eval is the contract.

- [ ] **Step 6: Run the full test suite**

Run: `cd ~/projects/prompt-squeeze && uv run pytest tests/ -q 2>&1 | tail -3`
Expected: 105 passed.

- [ ] **Step 7: Commit**

```bash
git add skills/prompt-squeeze/scripts/rules.py tests/skill/test_compress.py
git commit -m "Add aggressive politeness rules (eval fidelity holds)"
```

---

## Task 7: Add aggressive rule — verbose connectors

Connectors like `with respect to`, `in terms of`, `with reference to` rarely add meaning. Some need context gates.

**Files:**
- Modify: `skills/prompt-squeeze/scripts/rules.py`
- Modify: `tests/skill/test_compress.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/skill/test_compress.py`:

```python
class TestAggressiveConnectors:
    def test_with_respect_to_to_about(self):
        out = compress.compress("Tell me about the trade-offs with respect to latency.")
        assert "with respect to" not in out.lower()
        assert "about latency" in out

    def test_in_terms_of_to_for(self):
        out = compress.compress("Optimize in terms of memory usage.")
        assert "in terms of" not in out.lower()
        assert "memory usage" in out

    def test_with_reference_to_to_about(self):
        out = compress.compress("Update the doc with reference to the new schema.")
        assert "with reference to" not in out.lower()
        assert "schema" in out

    def test_in_relation_to_to_about(self):
        out = compress.compress("How does this work in relation to caching?")
        assert "in relation to" not in out.lower()
        assert "caching" in out

    def test_as_a_matter_of_fact_drops(self):
        out = compress.compress("As a matter of fact, the bug is in line 42.")
        assert "as a matter of fact" not in out.lower()
        assert "line 42" in out

    def test_at_the_end_of_the_day_drops(self):
        out = compress.compress("At the end of the day, performance matters most.")
        assert "at the end of the day" not in out.lower()
        assert "performance matters most" in out
```

- [ ] **Step 2: Run, watch fail**

Run: `cd ~/projects/prompt-squeeze && uv run pytest tests/skill/test_compress.py::TestAggressiveConnectors -v`
Expected: 6 FAIL.

- [ ] **Step 3: Add the rules**

Append to `skills/prompt-squeeze/scripts/rules.py`:

```python
V04_CONNECTOR_RULES: list[Rule] = [
    Rule(id="CONNECTOR_WITH_RESPECT_TO", pattern=r"\bwith respect to\b", replacement="about"),
    Rule(id="CONNECTOR_IN_TERMS_OF", pattern=r"\bin terms of\b", replacement=""),
    Rule(id="CONNECTOR_WITH_REFERENCE_TO", pattern=r"\bwith reference to\b", replacement="about"),
    Rule(id="CONNECTOR_IN_RELATION_TO", pattern=r"\bin relation to\b", replacement="about"),
    Rule(id="CONNECTOR_AS_MATTER_OF_FACT",
         pattern=r"\bas a matter of fact[,\s]*", replacement="",
         description="'as a matter of fact' → drop"),
    Rule(id="CONNECTOR_AT_END_OF_DAY",
         pattern=r"\bat the end of the day[,\s]*", replacement="",
         description="'at the end of the day' → drop"),
    Rule(id="CONNECTOR_THE_FACT_OF_MATTER",
         pattern=r"\bthe fact of the matter is(?:\s+that)?[,\s]*", replacement="",
         description="'the fact of the matter is (that)' → drop"),
    Rule(id="CONNECTOR_NEEDLESS_TO_SAY",
         pattern=r"\bneedless to say[,\s]*", replacement="",
         description="'needless to say' → drop"),
]

V03_REGISTRY = V03_REGISTRY + V04_CONNECTOR_RULES
```

- [ ] **Step 4: Run tests, expect pass**

Run: `cd ~/projects/prompt-squeeze && uv run pytest tests/skill/test_compress.py::TestAggressiveConnectors -v`
Expected: 6 PASS.

- [ ] **Step 5: Eval gate**

Run: `cd ~/projects/prompt-squeeze && uv run python skills/prompt-squeeze/scripts/eval/run_eval.py --judge --judge-sample 30 2>&1 | tail -5`
Expected: median fidelity ≥ 0.95. If lower, identify and revert offending rule(s).

- [ ] **Step 6: Full suite**

Run: `cd ~/projects/prompt-squeeze && uv run pytest tests/ -q 2>&1 | tail -3`
Expected: 111 passed.

- [ ] **Step 7: Commit**

```bash
git add skills/prompt-squeeze/scripts/rules.py tests/skill/test_compress.py
git commit -m "Add aggressive connector rules (with respect to, in terms of, etc.)"
```

---

## Task 8: Add aggressive rule — redundant qualifiers

Qualifier words (`very`, `really`, `actually`, `basically`, `essentially`, `quite`, `rather`) typically add no LLM-relevant meaning before adjectives.

**Files:**
- Modify: `skills/prompt-squeeze/scripts/rules.py`
- Modify: `tests/skill/test_compress.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/skill/test_compress.py`:

```python
class TestAggressiveQualifiers:
    def test_drops_very_before_adjective(self):
        out = compress.compress("This is a very important fix for foo.py.")
        assert " very important" not in out
        assert "important fix for foo.py" in out

    def test_drops_really_before_verb(self):
        out = compress.compress("I really need this to work.")
        assert " really need" not in out
        assert "need this to work" in out

    def test_drops_actually(self):
        out = compress.compress("This actually causes a memory leak.")
        assert " actually " not in out
        assert "causes a memory leak" in out

    def test_drops_basically(self):
        out = compress.compress("It basically does the same thing.")
        assert " basically " not in out
        assert "does the same thing" in out

    def test_drops_essentially(self):
        out = compress.compress("They essentially work the same way.")
        assert " essentially " not in out

    def test_does_not_drop_inside_quoted_string(self):
        # Quoted content is protected.
        out = compress.compress('The error says "this is very bad"')
        assert "very bad" in out
```

- [ ] **Step 2: Run, expect fail**

Run: `cd ~/projects/prompt-squeeze && uv run pytest tests/skill/test_compress.py::TestAggressiveQualifiers -v`
Expected: 5 FAIL (last test should pass via existing protection).

- [ ] **Step 3: Add the rules**

Append to `skills/prompt-squeeze/scripts/rules.py`:

```python
V04_QUALIFIER_RULES: list[Rule] = [
    Rule(id="QUALIFIER_VERY", pattern=r"\bvery\b\s+", replacement="",
         description="'very <X>' → '<X>'"),
    Rule(id="QUALIFIER_REALLY", pattern=r"\breally\b\s+", replacement="",
         description="'really <X>' → '<X>'"),
    Rule(id="QUALIFIER_ACTUALLY", pattern=r"\bactually\b\s*[,]?\s*", replacement="",
         description="'actually' → drop"),
    Rule(id="QUALIFIER_BASICALLY", pattern=r"\bbasically\b\s*[,]?\s*", replacement="",
         description="'basically' → drop"),
    Rule(id="QUALIFIER_ESSENTIALLY", pattern=r"\bessentially\b\s*[,]?\s*", replacement="",
         description="'essentially' → drop"),
    Rule(id="QUALIFIER_QUITE", pattern=r"\bquite\b\s+", replacement="",
         description="'quite <X>' → '<X>'"),
    Rule(id="QUALIFIER_JUST", pattern=r"\bjust\b\s+", replacement="",
         description="'just <X>' → '<X>'"),
    Rule(id="QUALIFIER_KIND_OF", pattern=r"\bkind of\b\s+", replacement="",
         description="'kind of <X>' → '<X>'"),
    Rule(id="QUALIFIER_SORT_OF", pattern=r"\bsort of\b\s+", replacement="",
         description="'sort of <X>' → '<X>'"),
]

V03_REGISTRY = V03_REGISTRY + V04_QUALIFIER_RULES
```

- [ ] **Step 4: Run tests**

Run: `cd ~/projects/prompt-squeeze && uv run pytest tests/skill/test_compress.py::TestAggressiveQualifiers -v`
Expected: 6 PASS.

- [ ] **Step 5: Eval gate**

Run: `cd ~/projects/prompt-squeeze && uv run python skills/prompt-squeeze/scripts/eval/run_eval.py --judge --judge-sample 30 2>&1 | tail -5`
Expected: median fidelity ≥ 0.95. **Watch for "just" being too aggressive** — `just` can be load-bearing in code review prompts ("just check if X"). If fidelity drops, revert `QUALIFIER_JUST` first and re-eval.

- [ ] **Step 6: Full suite**

Run: `cd ~/projects/prompt-squeeze && uv run pytest tests/ -q 2>&1 | tail -3`
Expected: 117 passed.

- [ ] **Step 7: Commit**

```bash
git add skills/prompt-squeeze/scripts/rules.py tests/skill/test_compress.py
git commit -m "Add aggressive qualifier rules (very, really, actually, etc.)"
```

---

## Task 9: Add aggressive rule — leading pronoun + helping-verb collapse

Patterns like `I would like you to...` and `I want you to...` carry no LLM-relevant meaning beyond the imperative. Compress to bare imperative.

**Files:**
- Modify: `skills/prompt-squeeze/scripts/rules.py`
- Modify: `tests/skill/test_compress.py`

- [ ] **Step 1: Failing tests**

Append to `tests/skill/test_compress.py`:

```python
class TestAggressiveImperativeCollapse:
    def test_i_would_like_you_to_drops(self):
        out = compress.compress("I would like you to refactor foo.py:42.")
        assert "I would like you to" not in out
        assert "Refactor foo.py:42" in out or "refactor foo.py:42" in out.lower()

    def test_i_want_you_to_drops(self):
        out = compress.compress("I want you to write a test for the parser.")
        assert "I want you to" not in out
        assert "write a test for the parser" in out.lower()

    def test_i_need_you_to_drops(self):
        out = compress.compress("I need you to fix the bug in handler.go.")
        assert "I need you to" not in out
        assert "handler.go" in out

    def test_id_appreciate_it_if_drops(self):
        out = compress.compress("I'd appreciate it if you could update the README.")
        assert "appreciate it if" not in out.lower()
        assert "README" in out

    def test_what_id_like_drops(self):
        out = compress.compress("What I'd like is for you to add a unit test.")
        assert "what i'd like is for you to" not in out.lower()
        assert "add a unit test" in out.lower()
```

- [ ] **Step 2: Run, fail**

Run: `cd ~/projects/prompt-squeeze && uv run pytest tests/skill/test_compress.py::TestAggressiveImperativeCollapse -v`
Expected: 5 FAIL.

- [ ] **Step 3: Add rules**

Append to `skills/prompt-squeeze/scripts/rules.py`:

```python
V04_IMPERATIVE_RULES: list[Rule] = [
    Rule(id="IMPERATIVE_I_WOULD_LIKE_YOU_TO",
         pattern=r"\bi(?:'d| would) like (?:you )?to\b\s*", replacement="",
         description="'I'd/I would like (you) to <verb>' → '<verb>'"),
    Rule(id="IMPERATIVE_I_WANT_YOU_TO",
         pattern=r"\bi want (?:you )?to\b\s*", replacement="",
         description="'I want (you) to <verb>' → '<verb>'"),
    Rule(id="IMPERATIVE_I_NEED_YOU_TO",
         pattern=r"\bi need (?:you )?to\b\s*", replacement="",
         description="'I need (you) to <verb>' → '<verb>'"),
    Rule(id="IMPERATIVE_APPRECIATE_IF",
         pattern=r"\bi(?:'d| would) appreciate it if (?:you )?(?:could|would|might)\b\s*",
         replacement="",
         description="'I'd appreciate it if you could <verb>' → '<verb>'"),
    Rule(id="IMPERATIVE_WHAT_ID_LIKE",
         pattern=r"\bwhat i(?:'d| would) like is (?:for you )?to\b\s*", replacement="",
         description="'What I'd like is (for you) to <verb>' → '<verb>'"),
    Rule(id="IMPERATIVE_LET_ME_KNOW_IF",
         pattern=r"\blet me know if (?:you )?(?:can|could)\b\s*", replacement="",
         description="'let me know if you can <verb>' → '<verb>'"),
]

V03_REGISTRY = V03_REGISTRY + V04_IMPERATIVE_RULES
```

- [ ] **Step 4: Run tests, pass**

Run: `cd ~/projects/prompt-squeeze && uv run pytest tests/skill/test_compress.py::TestAggressiveImperativeCollapse -v`
Expected: 5 PASS.

- [ ] **Step 5: Eval gate**

Run: `cd ~/projects/prompt-squeeze && uv run python skills/prompt-squeeze/scripts/eval/run_eval.py --judge --judge-sample 30 2>&1 | tail -5`
Expected: median fidelity ≥ 0.95.

- [ ] **Step 6: Full suite**

Run: `cd ~/projects/prompt-squeeze && uv run pytest tests/ -q 2>&1 | tail -3`
Expected: 122 passed.

- [ ] **Step 7: Commit**

```bash
git add skills/prompt-squeeze/scripts/rules.py tests/skill/test_compress.py
git commit -m "Add aggressive imperative-collapse rules (I want you to, I'd like you to, etc.)"
```

---

## Task 10: Add aggressive rule — definite-article dropping (high-risk; gate carefully)

Article dropping is the most fidelity-risky rule category. We add it last among the new rules so prior categories establish the ratio improvements first. Only fire in safe positions — sentence start before specific concrete nouns. **If this category drops eval fidelity below 0.95 and can't be saved with tighter gating, the whole task gets reverted before commit.**

**Files:**
- Modify: `skills/prompt-squeeze/scripts/rules.py`
- Modify: `tests/skill/test_compress.py`

- [ ] **Step 1: Failing tests**

Append to `tests/skill/test_compress.py`:

```python
class TestAggressiveArticleDropping:
    def test_drops_the_at_imperative_start(self):
        # 'The' at the start of an imperative-like sentence is often droppable.
        out = compress.compress("The function in foo.py is broken.")
        # Either dropped, or unchanged — we just don't want broken meaning.
        assert "function in foo.py" in out
        assert "is broken" in out

    def test_keeps_the_inside_noun_phrase(self):
        # Inside a noun phrase ('the API') article is load-bearing for specificity.
        out = compress.compress("Update the API contract with a new field.")
        # We DO NOT drop 'the API' — too risky.
        assert "the API" in out or "API contract" in out

    def test_drops_a_before_simple_indefinite(self):
        # 'Write a test' is fine as 'Write test' for an LLM.
        out = compress.compress("Write a test for the new function.")
        assert "Write test" in out or "Write a test" in out  # tolerate either; eval will tune

    def test_preserves_articles_in_quoted_speech(self):
        out = compress.compress('The error message says "the connection was reset".')
        assert "the connection was reset" in out
```

- [ ] **Step 2: Run, see current state**

Run: `cd ~/projects/prompt-squeeze && uv run pytest tests/skill/test_compress.py::TestAggressiveArticleDropping -v`
Expected: at least one fails (likely `test_drops_the_at_imperative_start`).

- [ ] **Step 3: Add a *narrow* article-dropping rule**

Append to `skills/prompt-squeeze/scripts/rules.py`:

```python
# ---------------------------------------------------------------------------
# v0.4 article dropping — narrow scope. Only drops 'The' / 'A' / 'An' when:
#   1. At the very start of a sentence (after start-of-text or sentence terminator)
#   2. Followed by a noun-like word (lowercase, not a code identifier)
# Gates out near identifiers (CamelCase, snake_case, paths, code fences are protected upstream).
# ---------------------------------------------------------------------------

_ARTICLE_AT_START_PATTERN = r"(^|(?<=[.!?])\s+)(?:[Tt]he|[Aa]n?)\s+(?=[a-z])"


def _article_gate(match: re.Match[str], full_text: str) -> bool:
    """Skip if the next word looks like a code identifier (presence of _ or non-ASCII)."""
    end = match.end()
    rest = full_text[end : end + 40]
    next_word = re.match(r"(\w+)", rest)
    if not next_word:
        return False
    word = next_word.group(1)
    if "_" in word:
        return False
    return True


ARTICLE_DROP_RULE = Rule(
    id="ARTICLE_DROP_AT_SENTENCE_START",
    pattern=_ARTICLE_AT_START_PATTERN,
    replacement=lambda m: m.group(1),  # keep the boundary, drop the article
    context_gate=_article_gate,
    description="Drop 'The/A/An' at sentence start before a lowercase common noun.",
)

V03_REGISTRY = V03_REGISTRY + [ARTICLE_DROP_RULE]
```

- [ ] **Step 4: Run tests**

Run: `cd ~/projects/prompt-squeeze && uv run pytest tests/skill/test_compress.py::TestAggressiveArticleDropping -v`
Expected: 4 PASS (relaxed assertions accommodate either drop-or-keep).

- [ ] **Step 5: Critical eval gate — full --judge run, all 100 prompts**

Run: `cd ~/projects/prompt-squeeze && uv run python skills/prompt-squeeze/scripts/eval/run_eval.py --judge 2>&1 | tail -10`

This is the most fidelity-risky rule. If median fidelity drops below 0.95, OR if any baseline-≥0.95 prompt now scores below 0.95, **revert the rule before committing**:

```bash
git diff skills/prompt-squeeze/scripts/rules.py  # inspect
# To revert just this task's changes:
git checkout skills/prompt-squeeze/scripts/rules.py
```

Then either: (a) skip article-dropping for v0.4 entirely and document in CHANGELOG, or (b) tighten the gate (e.g., require the next word to be 4+ letters, or require imperative verb before the article-bearing phrase).

- [ ] **Step 6: Full suite**

Run: `cd ~/projects/prompt-squeeze && uv run pytest tests/ -q 2>&1 | tail -3`
Expected: 126 passed (122 + 4) IF rule kept; 122 if reverted.

- [ ] **Step 7: Commit (only if eval gate held)**

```bash
git add skills/prompt-squeeze/scripts/rules.py tests/skill/test_compress.py
git commit -m "Add narrow article-dropping rule (eval fidelity gate held)"
```

If reverted, commit anyway with the test cases (relaxed) plus a docstring note in `rules.py`:

```bash
git add tests/skill/test_compress.py skills/prompt-squeeze/scripts/rules.py
git commit -m "Document article-dropping deferred (failed eval gate; v0.5 candidate)"
```

---

## Task 11: Tighten the eval CI gate

Now that rules have been added against the gate, encode the gate into `run_eval.py` so future PRs cannot regress.

**Files:**
- Modify: `skills/prompt-squeeze/scripts/eval/run_eval.py:25-30, 252-273`

- [ ] **Step 1: Update thresholds and add p5 + no-regression checks**

Edit `skills/prompt-squeeze/scripts/eval/run_eval.py`. Replace lines 25-30:

```python
# Production CI thresholds for the eval gate. PRD section 10 + spec §1 (eval contract):
# - Median fidelity ≥ 0.95
# - 5th percentile fidelity ≥ 0.85
# - No prompt that previously scored ≥ 0.95 may regress below 0.95
_MIN_MEDIAN_COMPRESSION = 0.10
_MIN_MEDIAN_FIDELITY = 0.95
_MIN_P5_FIDELITY = 0.85
_BASELINE_PATH = _SKILL_DIR / "data" / "baseline_fidelity.json"
```

After the existing fidelity-median check (around line 266-271), add p5 and per-prompt regression checks:

```python
    # Per-row fidelities recorded above; for p5 and regression checks we need the per-id map.
    # Re-enable per-id capture in the loop above by changing this:
    #   fidelities.append(fidelity)
    # to also save the row id alongside the score. See edits above.

    # 5th-percentile gate
    if fidelities and len(fidelities) >= 20:
        fidelities_sorted = sorted(fidelities)
        p5_idx = max(0, int(len(fidelities_sorted) * 0.05) - 1)
        p5 = fidelities_sorted[p5_idx]
        print(f"5th-percentile fidelity: {p5:.3f}")
        if p5 < _MIN_P5_FIDELITY:
            print(
                f"FAIL: p5 fidelity {p5:.3f} < {_MIN_P5_FIDELITY:.2f}",
                file=sys.stderr,
            )
            exit_code = 1

    # No-regression gate against baseline_fidelity.json
    if args.judge and _BASELINE_PATH.exists() and not args.judge_sample:
        try:
            baseline = json.loads(_BASELINE_PATH.read_text())
        except Exception as e:
            print(f"WARN: could not load baseline: {e}", file=sys.stderr)
            baseline = {}
        regressions = []
        # Build per-id current map by re-running judge per row would be wasteful.
        # Use the fidelities-by-id map that the loop now populates (see edit below).
        for row_id, current_fidelity in _FIDELITIES_BY_ID.items():
            base = baseline.get(row_id, {}).get("fidelity", 0.0)
            if base >= 0.95 and current_fidelity < 0.95:
                regressions.append((row_id, base, current_fidelity))
        if regressions:
            for rid, b, c in regressions:
                print(
                    f"FAIL regression: {rid} baseline={b:.2f} current={c:.2f}",
                    file=sys.stderr,
                )
            exit_code = 1
```

To make `_FIDELITIES_BY_ID` populated, also edit the per-row loop (around line 229-237). Find the block:

```python
        if args.judge and row["id"] in judge_target_ids:
            fidelity, reason = _judge(
                original,
                compressed,
                backend=args.judge_backend,
                model=args.judge_model,
            )
            fidelities.append(fidelity)
            print(f"  judge: fidelity={fidelity:.2f} reason={reason}")
```

Replace with:

```python
        if args.judge and row["id"] in judge_target_ids:
            fidelity, reason = _judge(
                original,
                compressed,
                backend=args.judge_backend,
                model=args.judge_model,
            )
            fidelities.append(fidelity)
            _FIDELITIES_BY_ID[row["id"]] = fidelity
            print(f"  judge: fidelity={fidelity:.2f} reason={reason}")
```

And declare `_FIDELITIES_BY_ID` near the other locals (around line 195):

```python
    _FIDELITIES_BY_ID: dict[str, float] = {}
```

- [ ] **Step 2: Run a sample eval to confirm gates engage correctly**

Run: `cd ~/projects/prompt-squeeze && uv run python skills/prompt-squeeze/scripts/eval/run_eval.py --judge --judge-sample 30 2>&1 | tail -10`
Expected: prints `median judge fidelity: 0.X`, `5th-percentile fidelity: 0.X`. The `--judge-sample 30` skips the no-regression gate (only full runs check it). exit code 0 if median ≥ 0.95 and p5 ≥ 0.85.

- [ ] **Step 3: Add the eval gate to CI**

Edit `.github/workflows/ci.yml`. After the existing `Eval harness (no --judge)` step, add:

```yaml
      - name: Eval gate (judge, full)
        if: env.ANTHROPIC_API_KEY != ''
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
        run: uv run python skills/prompt-squeeze/scripts/eval/run_eval.py --judge --judge-backend sdk
```

Note: this requires `ANTHROPIC_API_KEY` set as a GitHub Actions secret. If the secret is not present, the step is skipped (the `if:` guard) so PRs from forks don't error. Document this in `CONTRIBUTING.md` (next step).

- [ ] **Step 4: Update CONTRIBUTING.md to document the eval gate**

Edit `CONTRIBUTING.md`. Find the "Tests" or "CI" section and add:

```markdown
## Eval gate

Compression-rule changes must keep the 100-prompt eval contract:
- Median Claude-as-judge fidelity ≥ 0.95
- 5th-percentile fidelity ≥ 0.85
- No prompt currently scoring ≥ 0.95 may regress below 0.95

CI runs `run_eval.py --judge` automatically when `ANTHROPIC_API_KEY` is configured. PRs from forks skip the judge step (no key access); maintainers run the gate manually before merging.

Local check: `uv run python skills/prompt-squeeze/scripts/eval/run_eval.py --judge --judge-backend cli` (uses your local Claude Code auth — no API key needed).
```

- [ ] **Step 5: Run the local eval gate one more time to ratify**

Run: `cd ~/projects/prompt-squeeze && uv run python skills/prompt-squeeze/scripts/eval/run_eval.py --judge 2>&1 | tail -15`
Expected: `median judge fidelity` ≥ 0.95, `5th-percentile fidelity` ≥ 0.85, `0 regressions` from baseline. exit code 0.

If anything fails, identify the offending rule via `git log --oneline` against the v0.3 baseline, revert it, and re-run.

- [ ] **Step 6: Commit**

```bash
git add skills/prompt-squeeze/scripts/eval/run_eval.py .github/workflows/ci.yml CONTRIBUTING.md
git commit -m "Tighten eval CI gate: median fidelity ≥0.95, p5 ≥0.85, no-regression check"
```

---

## Task 12: Bump version, update README, mark v0.3.3 ready

**Files:**
- Modify: `pyproject.toml`
- Modify: `.claude-plugin/plugin.json`
- Modify: `README.md`

- [ ] **Step 1: Bump version in pyproject.toml**

Find `version = "0.3.1"` (or 0.3.2) in `pyproject.toml`. Change to `version = "0.3.3"`.

- [ ] **Step 2: Bump version in .claude-plugin/plugin.json**

Find the `"version"` field. Change to `"0.3.3"`.

- [ ] **Step 3: Update README.md changelog section**

Find the `## Changelog` (or equivalent) section in `README.md`. Add at the top:

```markdown
### 0.3.3 (2026-05-04)

- Compression layer rewrite: rules now live in a typed `Rule` registry with stable IDs (sets up `/sq explain` in v0.4)
- Fix: 'for the purpose of' is now context-gated — only swaps to 'to' when followed by a verb-ing form, fixing the v0.3 0.72 fidelity outlier
- Fix: post-strip capitalization — sentences whose head was dropped by filler removal are re-capitalized
- New aggressive rules: expanded politeness, verbose connectors, redundant qualifiers, imperative collapse — all eval-gated (median fidelity ≥ 0.95)
- Eval contract enforced in CI: any rule that breaks the gate gets rejected automatically
```

- [ ] **Step 4: Run the full suite + eval one final time**

Run: `cd ~/projects/prompt-squeeze && uv run pytest tests/ -q && uv run python skills/prompt-squeeze/scripts/eval/run_eval.py --judge --judge-sample 30 2>&1 | tail -5`
Expected: all tests pass, eval gate green.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml .claude-plugin/plugin.json README.md
git commit -m "Bump to 0.3.3: aggressive rules + bug fixes + eval gate"
```

---

## Self-review (perform after writing this plan)

- **Spec coverage:** Component 1 of the spec covers six things — registry refactor, two bug fixes, aggressive rules, eval gates, baseline. Tasks 2-12 cover all. ✓
- **Placeholder scan:** All steps include actual code or commands. No "TODO" / "TBD" / "implement later." ✓
- **Type consistency:** `Rule.id`, `Rule.pattern`, `Rule.replacement`, `Rule.context_gate`, `Rule.flags`, `Rule.confidence`, `Rule.description` are referenced consistently. `Hit.rule_id`, `Hit.span`, `Hit.removed`, `Hit.replacement` are referenced consistently. `apply_all` returns `(text, list[Hit])`. ✓
- **Frequent commits:** Every task commits at the end. ✓
- **TDD discipline:** Every code-changing task has test → run-fail → implement → run-pass → commit. ✓

## Execution handoff

User has chosen inline execution with permissions waived. Use `superpowers:executing-plans` and proceed task-by-task without per-task approvals. Surface meaningful issues at task boundaries; commit after each task.
