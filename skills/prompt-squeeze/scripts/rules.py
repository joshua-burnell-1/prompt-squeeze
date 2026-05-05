# ABOUTME: Compression rule registry — Rule dataclass, hit tracking, registry application helpers.
# ABOUTME: Each rule is a self-contained pattern + replacement (string or callable) + optional context gate.

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
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
    confidence: float = 1.0
    description: str = ""

    def apply(self, text: str) -> tuple[str, list[Hit]]:
        """Apply this rule to text. Returns (modified_text, list_of_hits)."""
        compiled = re.compile(self.pattern, self.flags)
        hits: list[Hit] = []

        def _sub(match: re.Match[str]) -> str:
            if self.context_gate is not None and not self.context_gate(match, text):
                return match.group(0)
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


# ---------------------------------------------------------------------------
# v0.3 carryover rules. Each gets a stable id so /sq explain (Plan C) can attribute hits.
# Order matches the v0.3 _FILLER_PHRASES / _VERBOSE_SWAPS lists exactly so behavior is preserved.
# ---------------------------------------------------------------------------

# Greeting at start-of-text or right after sentence-ending punctuation. The boundary char
# is captured so the substitution can preserve it (we don't want to swallow the previous
# sentence's period). Mid-prose "hi" (e.g., "she said hi to him") is left alone.
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
    description="Hi/Hello/Hey at sentence boundary -> drop, preserve boundary punctuation",
)


V03_FILLER_RULES: list[Rule] = [
    Rule(id="FILLER_WONDERING_COULD", pattern=r"\bi was wondering if you could\b", replacement="",
         description="'I was wondering if you could' -> drop"),
    Rule(id="FILLER_WONDERING_IF", pattern=r"\bi was wondering if\b", replacement="",
         description="'I was wondering if' -> drop"),
    Rule(id="FILLER_WONDERING", pattern=r"\bi was wondering\b", replacement="",
         description="'I was wondering' -> drop"),
    Rule(id="FILLER_GREAT_IF", pattern=r"\bi think it would be great if\b", replacement="",
         description="'I think it would be great if' -> drop"),
    Rule(id="FILLER_DONT_MIND", pattern=r"\bif you don'?t mind\b", replacement="",
         description="'if you don't mind' -> drop"),
    Rule(id="FILLER_THANKS_ADV_FOR", pattern=r"\bthanks in advance(?:\s+for[^.!?]*)?[!]*", replacement="",
         description="'thanks in advance for X!' -> drop"),
    Rule(id="FILLER_THANK_YOU_VERY_MUCH",
         pattern=r"\bthank you (?:so much|very much)(?:\s+in advance)?(?:\s+for[^.!?]*)?[!]*",
         replacement="",
         description="'thank you so/very much (in advance) for X!' -> drop"),
    Rule(id="FILLER_THANK_YOU",
         pattern=r"\bthank you(?:\s+in advance)?(?:\s+for[^.!?]*)?[!]*",
         replacement="",
         description="'thank you (in advance) for X!' -> drop"),
    Rule(id="FILLER_THANKS", pattern=r"\bthanks(?:\s+for[^.!?]*)?[!]*", replacement="",
         description="'thanks for X!' -> drop"),
    Rule(id="FILLER_APPRECIATE", pattern=r"\bi really appreciate it[!.?]*", replacement="",
         description="'I really appreciate it!' -> drop"),
    Rule(id="FILLER_PLEASE", pattern=r"\bplease\b", replacement="",
         description="'please' -> drop"),
    Rule(id="FILLER_COULD_YOU_PLEASE", pattern=r"\bcould you please\b", replacement="",
         description="'could you please' -> drop"),
    Rule(id="FILLER_COULD_YOU", pattern=r"\bcould you\b", replacement="",
         description="'could you' -> drop"),
    Rule(id="FILLER_WOULD_YOU_MIND", pattern=r"\bwould you mind\b", replacement="",
         description="'would you mind' -> drop"),
    Rule(id="FILLER_WOULD_YOU", pattern=r"\bwould you\b", replacement="",
         description="'would you' -> drop"),
    Rule(id="FILLER_CAN_YOU_PLEASE", pattern=r"\bcan you please\b", replacement="",
         description="'can you please' -> drop"),
    Rule(id="FILLER_CAN_YOU", pattern=r"\bcan you\b", replacement="",
         description="'can you' -> drop"),
]


V03_VERBOSE_RULES: list[Rule] = [
    Rule(id="VERBOSE_IN_ORDER_TO", pattern=r"\bin order to\b", replacement="to"),
    Rule(id="VERBOSE_AT_THIS_POINT", pattern=r"\bat this point in time\b", replacement="now"),
    Rule(id="VERBOSE_DUE_TO_FACT", pattern=r"\bdue to the fact that\b", replacement="because"),
    # NOTE: VERBOSE_FOR_PURPOSE_OF is intentionally absent here — Task 5 reclassifies it as
    # context-gated via VERBOSE_FOR_PURPOSE_OF_GATED to fix the v0.3 0.72 fidelity outlier.
    Rule(id="VERBOSE_IN_THE_EVENT", pattern=r"\bin the event that\b", replacement="if"),
    Rule(id="VERBOSE_WITH_REGARD_TO", pattern=r"\bwith regard to\b", replacement="about"),
    Rule(id="VERBOSE_WITH_REGARDS_TO", pattern=r"\bwith regards to\b", replacement="about"),
    Rule(id="VERBOSE_MAKE_DECISION", pattern=r"\bmake a decision\b", replacement="decide"),
    Rule(id="VERBOSE_GIVE_CONSIDERATION", pattern=r"\bgive consideration to\b", replacement="consider"),
]


# ---------------------------------------------------------------------------
# v0.4 Bug fix #1: 'for the purpose of' is context-gated. It fires only when followed
# by a gerund (verb-ing), in which case 'for the purpose of testing' becomes
# 'to test'. When followed by a bare noun ('for the purpose of compatibility')
# the phrase carries the meaning and is left intact.
# ---------------------------------------------------------------------------


def _purpose_of_replacement(match: re.Match[str]) -> str:
    verb_ing = match.group(1)
    base = verb_ing[:-3]  # 'testing' -> 'test'
    # Restore final 'e' for verbs that drop it before -ing: 'validating' -> 'validate',
    # 'creating' -> 'create', 'storing' -> 'store'. Heuristic — covers most common forms.
    if re.search(
        r"[bcdfghjklmnpqrstvwxz](?:at|iz|ic|os|ur|in|ess|ag|ut|ad|or|ov|ak|ar)$",
        base,
    ):
        base = base + "e"
    return f"to {base}"


VERBOSE_FOR_PURPOSE_OF_GATED = Rule(
    id="VERBOSE_FOR_PURPOSE_OF_GATED",
    pattern=r"\bfor the purpose of\s+(\w+ing)\b",
    replacement=_purpose_of_replacement,
    description="'for the purpose of <verb-ing>' -> 'to <verb>' (only when verb-ing form follows)",
)


# ---------------------------------------------------------------------------
# v0.4 aggressive politeness rules. Each must keep eval median fidelity >= 0.95.
# ---------------------------------------------------------------------------

V04_POLITENESS_RULES: list[Rule] = [
    Rule(id="POLITENESS_NOT_TOO_MUCH_TROUBLE",
         pattern=r"\bif it'?s not too much trouble[,\s]*", replacement="",
         description="'if it's not too much trouble' -> drop"),
    Rule(id="POLITENESS_HAVE_A_MOMENT",
         pattern=r"\bif you have a (?:moment|second|minute|sec|chance)[,\s]*", replacement="",
         description="'if you have a moment/second/minute/chance' -> drop"),
    Rule(id="POLITENESS_WHEN_YOU_GET_CHANCE",
         pattern=r"\bwhen you (?:get a chance|have a moment|have time)[,\s]*", replacement="",
         description="'when you get a chance/have a moment/have time' -> drop"),
    Rule(id="POLITENESS_SORRY_TO_BOTHER",
         pattern=r"\bsorry to (?:bother|trouble) you[,\s]*(?:but\s+)?", replacement="",
         description="'sorry to bother/trouble you (but)' -> drop"),
    Rule(id="POLITENESS_HOPE_NOT_BOTHER",
         pattern=r"\bi hope (?:this is|i'?m) not bothering you[,.\s]*", replacement="",
         description="'I hope this isn't bothering you' -> drop"),
]


# Default registry — order matters. Greeting first so it sees clean sentence boundaries,
# then filler phrases, then verbose swaps, then v0.4 aggressive rules. Plan A tasks 7-10 append.
DEFAULT_REGISTRY: list[Rule] = (
    [GREETING_RULE]
    + V03_FILLER_RULES
    + V03_VERBOSE_RULES
    + [VERBOSE_FOR_PURPOSE_OF_GATED]
    + V04_POLITENESS_RULES
)
