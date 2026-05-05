# ABOUTME: Redaction pass for explain artifacts — strip secrets before storing prompts on disk.
# ABOUTME: Patterns: sk-..., ghp_..., AWS access keys, JWT-shaped strings, RFC-5321 emails.

from __future__ import annotations

import re

_PLACEHOLDER = "<REDACTED:secret>"

_PATTERNS = [
    # OpenAI-style secret keys (sk-... 32+ alphanumeric chars)
    re.compile(r"\bsk-[a-zA-Z0-9_-]{20,}\b"),
    # GitHub personal access tokens (ghp_... or ghs_... or ghu_... or gho_... 36+ chars)
    re.compile(r"\bgh[psuo]_[a-zA-Z0-9]{30,}\b"),
    # AWS access key IDs (AKIA + 16 uppercase alphanumeric)
    re.compile(r"\bAKIA[A-Z0-9]{16}\b"),
    # JWT-shaped strings: three base64url segments separated by dots, payload typically 30+ chars
    re.compile(r"\beyJ[a-zA-Z0-9_-]{8,}\.eyJ[a-zA-Z0-9_-]{8,}\.[a-zA-Z0-9_-]{20,}\b"),
    # RFC-5321 emails (loose match — local-part@domain with TLD)
    re.compile(r"\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b"),
]


def redact(text: str) -> str:
    """Replace secret-shaped substrings with <REDACTED:secret>. Idempotent."""
    if not text:
        return text
    out = text
    for pattern in _PATTERNS:
        out = pattern.sub(_PLACEHOLDER, out)
    return out
