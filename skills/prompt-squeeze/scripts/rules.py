# ABOUTME: Compression rule registry — Rule dataclass, hit tracking, registry application helpers.
# ABOUTME: Each rule is a self-contained pattern + replacement (string or callable) + optional context gate.

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass


@dataclass
class Hit:
    """One firing of a rule. Spans index into the text the rule received as input."""
    rule_id: str
    span: tuple[int, int]
    removed: str
    replacement: str


Replacement = "str | Callable[[re.Match[str]], str]"
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
    # 'could you please not X' MUST run before generic 'could you please' so 'not'
    # gets recast to 'do not' instead of becoming a stranded "Not X" fragment.
    Rule(id="FILLER_COULD_YOU_PLEASE_NOT",
         pattern=r"\b(?:could|can|would) you please not\b", replacement="do not",
         description="'could/can/would you please not <verb>' -> 'do not <verb>'"),
    Rule(id="FILLER_COULD_YOU_NOT",
         pattern=r"\b(?:could|can|would) you not\b", replacement="do not",
         description="'could/can/would you not <verb>' -> 'do not <verb>'"),
    # Wondering/great-if patterns extended to consume the trailing 'you might/could/would (be able to)'
    # so the next sentence head is a real verb, not a weakened 'You might'.
    Rule(id="FILLER_WONDERING_IF_YOU_HELPER",
         pattern=r"\bi was wondering if you (?:might|could|would|can)(?:\s+be able to)?\b",
         replacement="",
         description="'I was wondering if you might/could/would (be able to)' -> drop with helper tail"),
    Rule(id="FILLER_WONDERING_COULD", pattern=r"\bi was wondering if you could\b", replacement="",
         description="'I was wondering if you could' -> drop"),
    Rule(id="FILLER_WONDERING_IF", pattern=r"\bi was wondering if\b", replacement="",
         description="'I was wondering if' -> drop"),
    Rule(id="FILLER_WONDERING", pattern=r"\bi was wondering\b", replacement="",
         description="'I was wondering' -> drop"),
    Rule(id="FILLER_GREAT_IF_YOU_HELPER",
         pattern=r"\bi think it would be great if you (?:could|would|might)\b",
         replacement="",
         description="'I think it would be great if you could/would/might' -> drop with helper tail"),
    Rule(id="FILLER_GREAT_IF_YOU",
         pattern=r"\bi think it would be great if you\b",
         replacement="",
         description="'I think it would be great if you <verb>' -> drop trailing 'you' too"),
    Rule(id="FILLER_GREAT_IF", pattern=r"\bi think it would be great if\b", replacement="",
         description="'I think it would be great if' -> drop"),
    Rule(id="FILLER_DONT_MIND", pattern=r"\bif you don'?t mind\b", replacement="",
         description="'if you don't mind' -> drop"),
    Rule(id="FILLER_THANKS_ADV_FOR", pattern=r"\bthanks in advance(?:\s+for[^.!?]*)?[!]*", replacement="",
         description="'thanks in advance for X!' -> drop"),
    Rule(id="FILLER_THANKS_VERY_MUCH",
         pattern=r"\bthanks (?:so much|very much)(?:\s+in advance)?(?:\s+for[^.!?]*)?[!]*",
         replacement="",
         description="'thanks so/very much (in advance) (for X)!' -> drop"),
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


# ---------------------------------------------------------------------------
# v0.4 aggressive connector rules — verbose phrases that rarely add LLM-relevant meaning.
# ---------------------------------------------------------------------------

V04_CONNECTOR_RULES: list[Rule] = [
    Rule(id="CONNECTOR_WITH_RESPECT_TO", pattern=r"\bwith respect to\b", replacement="about"),
    Rule(id="CONNECTOR_IN_TERMS_OF", pattern=r"\bin terms of\b", replacement=""),
    Rule(id="CONNECTOR_WITH_REFERENCE_TO", pattern=r"\bwith reference to\b", replacement="about"),
    Rule(id="CONNECTOR_IN_RELATION_TO", pattern=r"\bin relation to\b", replacement="about"),
    Rule(id="CONNECTOR_AS_MATTER_OF_FACT",
         pattern=r"\bas a matter of fact[,\s]*", replacement="",
         description="'as a matter of fact' -> drop"),
    Rule(id="CONNECTOR_AT_END_OF_DAY",
         pattern=r"\bat the end of the day[,\s]*", replacement="",
         description="'at the end of the day' -> drop"),
    Rule(id="CONNECTOR_THE_FACT_OF_MATTER",
         pattern=r"\bthe fact of the matter is(?:\s+that)?[,\s]*", replacement="",
         description="'the fact of the matter is (that)' -> drop"),
    Rule(id="CONNECTOR_NEEDLESS_TO_SAY",
         pattern=r"\bneedless to say[,\s]*", replacement="",
         description="'needless to say' -> drop"),
]


# ---------------------------------------------------------------------------
# v0.4 aggressive qualifier rules — words like 'very', 'really', 'basically'
# add no LLM-relevant meaning before adjectives or verbs.
# ---------------------------------------------------------------------------

V04_QUALIFIER_RULES: list[Rule] = [
    Rule(id="QUALIFIER_VERY", pattern=r"\bvery\b\s+", replacement="",
         description="'very <X>' -> '<X>'"),
    Rule(id="QUALIFIER_REALLY", pattern=r"\breally\b\s+", replacement="",
         description="'really <X>' -> '<X>'"),
    Rule(id="QUALIFIER_ACTUALLY", pattern=r"\bactually\b\s*[,]?\s*", replacement="",
         description="'actually' -> drop"),
    Rule(id="QUALIFIER_BASICALLY", pattern=r"\bbasically\b\s*[,]?\s*", replacement="",
         description="'basically' -> drop"),
    Rule(id="QUALIFIER_ESSENTIALLY", pattern=r"\bessentially\b\s*[,]?\s*", replacement="",
         description="'essentially' -> drop"),
    Rule(id="QUALIFIER_QUITE", pattern=r"\bquite\b\s+", replacement="",
         description="'quite <X>' -> '<X>'"),
    Rule(id="QUALIFIER_KIND_OF", pattern=r"\bkind of\b\s+", replacement="",
         description="'kind of <X>' -> '<X>'"),
    Rule(id="QUALIFIER_SORT_OF", pattern=r"\bsort of\b\s+", replacement="",
         description="'sort of <X>' -> '<X>'"),
]


# ---------------------------------------------------------------------------
# v0.4 imperative-collapse rules — 'I would like you to <verb>' -> '<verb>'.
# The bare imperative carries the same meaning to an LLM.
# ---------------------------------------------------------------------------

V04_IMPERATIVE_RULES: list[Rule] = [
    Rule(id="IMPERATIVE_I_WOULD_LIKE_YOU_TO",
         pattern=r"\bi(?:'d| would) like (?:you )?to\b\s*", replacement="",
         description="'I'd/I would like (you) to <verb>' -> '<verb>'"),
    Rule(id="IMPERATIVE_I_WANT_YOU_TO",
         pattern=r"\bi want (?:you )?to\b\s*", replacement="",
         description="'I want (you) to <verb>' -> '<verb>'"),
    Rule(id="IMPERATIVE_I_NEED_YOU_TO",
         pattern=r"\bi need (?:you )?to\b\s*", replacement="",
         description="'I need (you) to <verb>' -> '<verb>'"),
    Rule(id="IMPERATIVE_APPRECIATE_IF",
         pattern=r"\bi(?:'d| would) appreciate it if (?:you )?(?:could|would|might)\b\s*",
         replacement="",
         description="'I'd appreciate it if you could <verb>' -> '<verb>'"),
    Rule(id="IMPERATIVE_WHAT_ID_LIKE",
         pattern=r"\bwhat i(?:'d| would) like is (?:for you )?to\b\s*", replacement="",
         description="'What I'd like is (for you) to <verb>' -> '<verb>'"),
    Rule(id="IMPERATIVE_LET_ME_KNOW_IF",
         pattern=r"\blet me know if (?:you )?(?:can|could)\b\s*", replacement="",
         description="'let me know if you can <verb>' -> '<verb>'"),
]


# ---------------------------------------------------------------------------
# v0.4 article dropping — narrowest possible scope. Only drops 'The' / 'A' / 'An'
# at the very start of a sentence (after start-of-text or sentence terminator)
# AND when followed by a lowercase common noun (no underscores, no camelCase, no digits).
# This category is the most fidelity-risky; keep tight gates.
# ---------------------------------------------------------------------------

_ARTICLE_AT_START_PATTERN = r"(^|(?<=[.!?])\s+)(?:[Tt]he|[Aa]n?)\s+(?=[a-z])"


def _article_replacement(match: re.Match[str]) -> str:
    return match.group(1) or ""


def _article_gate(match: re.Match[str], full_text: str) -> bool:
    """Skip if the next word looks like a code identifier (snake_case or camelCase)."""
    end = match.end()
    rest = full_text[end : end + 40]
    next_word = re.match(r"(\w+)", rest)
    if not next_word:
        return False
    word = next_word.group(1)
    if "_" in word:
        return False
    if any(c.isupper() for c in word[1:]):  # camelCase like 'iOS', 'iPhone'
        return False
    if any(c.isdigit() for c in word):
        return False
    return True


ARTICLE_DROP_RULE = Rule(
    id="ARTICLE_DROP_AT_SENTENCE_START",
    pattern=_ARTICLE_AT_START_PATTERN,
    replacement=_article_replacement,
    context_gate=_article_gate,
    description="Drop 'The/A/An' at sentence start before a lowercase common noun",
)


# Default registry — order matters. Greeting first so it sees clean sentence boundaries,
# then filler phrases, then verbose swaps, then v0.4 aggressive rules.
DEFAULT_REGISTRY: list[Rule] = (
    [GREETING_RULE]
    + V03_FILLER_RULES
    + V03_VERBOSE_RULES
    + [VERBOSE_FOR_PURPOSE_OF_GATED]
    + V04_POLITENESS_RULES
    + V04_CONNECTOR_RULES
    + V04_QUALIFIER_RULES
    + V04_IMPERATIVE_RULES
    + [ARTICLE_DROP_RULE]
)
