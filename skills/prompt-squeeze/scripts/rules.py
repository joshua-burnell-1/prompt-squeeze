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
