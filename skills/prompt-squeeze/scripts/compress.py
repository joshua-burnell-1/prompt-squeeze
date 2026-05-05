# ABOUTME: Stage 1 deterministic prompt compressor - strips filler, swaps verbose phrases, normalizes whitespace.
# ABOUTME: Preserves code fences, inline code, URLs, file paths, and quoted strings via placeholder substitution.

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from collections.abc import Callable

from rules import DEFAULT_REGISTRY, apply_all

# Token counting note: tiktoken's cl100k_base is the OpenAI BPE encoding.
# Anthropic does not publish their tokenizer; cl100k is the closest public
# approximation and is used here only for ratio reporting, not billing.
try:
    import tiktoken
    _ENC = tiktoken.get_encoding("cl100k_base")
except Exception:
    _ENC = None


_FENCED_CODE_RE = re.compile(r"```.*?```", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`[^`\n]+`")
_QUOTED_RE = re.compile(r"\"[^\"\n]+\"")
_URL_RE = re.compile(r"https?://\S+")
_PATH_RE = re.compile(r"[\w./\-]+\.[A-Za-z]{1,5}(?::\d+)?")


def _hash_prompt(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _extract_protected(text: str) -> tuple[str, list[str]]:
    """Replace protected regions with placeholders. Order matters: code > url > path > quoted."""
    protected: list[str] = []

    def _stash(match: re.Match[str]) -> str:
        protected.append(match.group(0))
        return f"\x00PS{len(protected) - 1}\x00"

    text = _FENCED_CODE_RE.sub(_stash, text)
    text = _INLINE_CODE_RE.sub(_stash, text)
    text = _URL_RE.sub(_stash, text)
    text = _PATH_RE.sub(_stash, text)
    text = _QUOTED_RE.sub(_stash, text)
    return text, protected


def _restore_protected(text: str, protected: list[str]) -> str:
    def _unstash(match: re.Match[str]) -> str:
        idx = int(match.group(1))
        return protected[idx]

    # Loop until stable — handles the case where one protected region nested another's placeholder.
    pattern = re.compile(r"\x00PS(\d+)\x00")
    for _ in range(len(protected) + 1):
        new_text = pattern.sub(_unstash, text)
        if new_text == text:
            return new_text
        text = new_text
    return text


def _cleanup_artifacts(text: str) -> str:
    """Tidy up wreckage left by phrase removal — stranded punctuation, doubled
    sentence-end markers, orphan tokens between sentences. Runs after stripping
    and before whitespace normalization."""
    # Collapse runs of sentence-end punctuation: ".!", "!.", "!!" → first only.
    text = re.sub(r"([.!?])[.!?]+", r"\1", text)
    # Strip orphan punctuation between two real chunks: ". ! Foo" → ". Foo".
    text = re.sub(r"([.!?])\s+[!?,;:]+(?=\s|$)", r"\1", text)
    # Strip orphan punctuation at line start (left over after filler removal).
    text = re.sub(r"^\s*[!?,;:]+\s*", "", text, flags=re.MULTILINE)
    # Drop empty parens left behind, e.g., "()".
    text = re.sub(r"\(\s*\)", "", text)
    return text


def _capitalize_sentences(text: str) -> str:
    """Capitalize the first letter of the text and the first letter of any sentence
    that follows a sentence-ending punctuation mark. Runs after filler removal so
    we catch newly-exposed sentence heads (the v0.3 'please update foo.py' regression).

    The lookahead guards camelCase identifiers like 'iOS' or 'iPhone' — we only
    capitalize a lowercase letter if the next character is also lowercase, whitespace,
    or sentence punctuation. A lowercase letter followed by uppercase (i+O in iOS)
    is left alone."""
    if not text:
        return text

    def _capitalize_first(s: str) -> str:
        for i, ch in enumerate(s):
            if ch.isspace():
                continue
            if ch.isalpha() and ch.islower():
                # Same camelCase guard as the sentence-boundary pass.
                if i + 1 < len(s) and s[i + 1].isalpha() and s[i + 1].isupper():
                    return s
                return s[:i] + ch.upper() + s[i + 1:]
            return s
        return s

    text = _capitalize_first(text)

    def _cap_after_terminator(match: re.Match[str]) -> str:
        return match.group(1) + match.group(2).upper()

    # Only capitalize lowercase letter if followed by lowercase/space/punct (not uppercase).
    # This preserves camelCase identifiers like 'iOS' at sentence start.
    text = re.sub(
        r"([.!?]\s+)([a-z])(?=[a-z\s.,;:'\-]|$)",
        _cap_after_terminator,
        text,
    )
    return text


def _normalize_whitespace(text: str) -> str:
    # Strip trailing whitespace per line.
    text = re.sub(r"[ \t]+\n", "\n", text)
    # Collapse runs of spaces/tabs (not newlines) to single space.
    text = re.sub(r"[ \t]{2,}", " ", text)
    # Tidy spaces before punctuation introduced by deletions.
    text = re.sub(r"\s+([,.!?;:])", r"\1", text)
    # Collapse 3+ blank lines to 1.
    text = re.sub(r"\n{3,}", "\n\n", text)
    # Remove leading whitespace on each line that came from filler removal at line start.
    text = re.sub(r"^[ \t]+", "", text, flags=re.MULTILINE)
    return text.strip() + ("\n" if text.endswith("\n") else "")


def compress(text: str) -> str:
    """Run the full Stage 1 deterministic compression pipeline."""
    return compress_with_hits(text)[0]


def compress_with_hits(text: str):
    """Compress text and return (compressed_text, hits_list).

    Each hit is a dict: {rule_id, span, removed, replacement}. Hits are surfaced
    to the prompt-squeeze hook for /sq explain rule-attribution rendering."""
    if not text:
        return text, []
    body, protected = _extract_protected(text)
    body, hits = apply_all(DEFAULT_REGISTRY, body)
    body = _cleanup_artifacts(body)
    body = _capitalize_sentences(body)
    body = _normalize_whitespace(body)
    final = _restore_protected(body, protected)
    # Convert dataclass Hit instances to plain dicts for JSON-friendly handoff.
    hit_dicts = [
        {
            "rule_id": h.rule_id,
            "span": list(h.span),
            "removed": h.removed,
            "replacement": h.replacement,
        }
        for h in hits
    ]
    return final, hit_dicts


def _count_tokens_default(text: str) -> int:
    if _ENC is None:
        # Fall back to whitespace word count if tiktoken unavailable.
        return len(text.split())
    return len(_ENC.encode(text))


def compression_ratio(
    original: str,
    compressed: str,
    *,
    count_tokens: Callable[[str], int] | None = None,
) -> float:
    """Return fraction of tokens removed: (orig - comp) / orig. 0.0 if original is empty."""
    counter = count_tokens or _count_tokens_default
    o = counter(original)
    if o == 0:
        return 0.0
    c = counter(compressed)
    return max(0.0, (o - c) / o)


_SELF_TEST_CASES: list[tuple[str, Callable[[str], bool]]] = [
    (
        "Hi, I was wondering if you could please refactor foo.py:42 in order to fix the TypeError. Thanks in advance!",
        lambda out: "foo.py:42" in out
        and "TypeError" in out
        and "in order to" not in out.lower()
        and "thanks in advance" not in out.lower()
        and "i was wondering" not in out.lower(),
    ),
    (
        "Could you please make a decision about whether to use v3.4.1 due to the fact that the release notes mention `--strict`?",
        lambda out: "v3.4.1" in out
        and "`--strict`" in out
        and "decide" in out.lower()
        and "because" in out.lower(),
    ),
    (
        "Please update the file at this point in time.\n\n\n\nThanks!",
        lambda out: "now" in out.lower() and "\n\n\n" not in out,
    ),
    (
        "Look at ```python\nplease do not touch this please\n``` but please simplify the rest.",
        lambda out: "please do not touch this please" in out
        and out.lower().count("please") == 2,
    ),
    (
        "",
        lambda out: out == "",
    ),
]


def _self_test() -> int:
    failures = 0
    for i, (src, predicate) in enumerate(_SELF_TEST_CASES):
        out = compress(src)
        ok = predicate(out)
        status = "PASS" if ok else "FAIL"
        # Logs MUST NOT print raw prompts - use hashes.
        print(f"case {i} {status} src_sha={_hash_prompt(src)} out_sha={_hash_prompt(out)}")
        if not ok:
            failures += 1
    print(f"self-test: {len(_SELF_TEST_CASES) - failures}/{len(_SELF_TEST_CASES)} passed")
    return 0 if failures == 0 else 1


def _read_input(args: argparse.Namespace) -> str:
    if args.stdin:
        return sys.stdin.read()
    if args.file:
        with open(args.file, encoding="utf-8") as f:
            return f.read()
    raise SystemExit("compress.py: must pass --stdin or --file")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Stage 1 deterministic prompt compressor.")
    src = parser.add_mutually_exclusive_group()
    src.add_argument("--stdin", action="store_true", help="Read prompt from stdin.")
    src.add_argument("--file", type=str, help="Read prompt from file path.")
    src.add_argument("--self-test", action="store_true", help="Run built-in test cases.")
    args = parser.parse_args(argv)

    if args.self_test:
        return _self_test()

    text = _read_input(args)
    sys.stdout.write(compress(text))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
