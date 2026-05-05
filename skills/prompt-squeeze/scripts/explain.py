# ABOUTME: Explain renderers for /sq explain — produce inline-diff, side-by-side, or by-rule output.
# ABOUTME: Pure function: takes a per-squeeze artifact dict, returns a formatted string.

from __future__ import annotations

from collections import defaultdict


def render(artifact: dict, mode: str = "inline") -> str:
    """Render an explain artifact in one of three modes: inline, side, by-rule.

    Unknown modes fall back to inline. Empty rules_fired yields a 'no compression' message."""
    if not artifact.get("rules_fired"):
        return _render_no_rules(artifact)
    if mode == "side":
        return _render_side(artifact)
    if mode == "by-rule":
        return _render_by_rule(artifact)
    return _render_inline(artifact)


def _header(artifact: dict) -> str:
    o = artifact.get("tokens_original", 0)
    c = artifact.get("tokens_squeezed", 0)
    pct = (o - c) / o if o else 0.0
    seq = artifact.get("seq", "?")
    ts = artifact.get("ts", "")
    return f"prompt-squeeze explain (seq #{seq}, {ts}): {o} -> {c} tok (-{pct:.0%})"


def _render_no_rules(artifact: dict) -> str:
    return (
        _header(artifact)
        + "\n\nno rules fired - prompt was already minimal under current rule set."
    )


def _render_inline(artifact: dict) -> str:
    """Original text annotated with numbered footnote markers; rule attribution below."""
    rules = artifact.get("rules_fired", [])
    lines = [_header(artifact), ""]
    lines.append("ORIGINAL (with removed spans marked):")
    original = artifact.get("original_text", "")

    sorted_rules = sorted(
        enumerate(rules, start=1),
        key=lambda pair: pair[1].get("span", [0, 0])[0],
    )

    annotated = ""
    cursor = 0
    for idx, hit in sorted_rules:
        start, end = hit.get("span", [0, 0])
        if start > len(original):
            continue
        annotated += original[cursor:start]
        annotated += f"[{hit.get('removed', '')}]^{idx}"
        cursor = end
    annotated += original[cursor:]
    lines.append(annotated)
    lines.append("")
    lines.append("ATTRIBUTION:")
    for idx, hit in sorted_rules:
        rid = hit.get("rule_id", "?")
        removed = hit.get("removed", "")
        saved = hit.get("tokens_saved")
        suffix = f" (-{saved} tok)" if saved else ""
        lines.append(f"  ^{idx} {rid}: dropped {removed!r}{suffix}")
    lines.append("")
    lines.append(f"COMPRESSED: {artifact.get('squeezed_text', '')}")
    return "\n".join(lines)


def _render_side(artifact: dict) -> str:
    """Side-by-side ORIGINAL | COMPRESSED with rule annotations below."""
    width = 36
    original = artifact.get("original_text", "")
    squeezed = artifact.get("squeezed_text", "")
    rules = artifact.get("rules_fired", [])
    lines = [_header(artifact), ""]
    sep = "-" * width + "-+-" + "-" * width
    lines.append(f"{'ORIGINAL':<{width}} | COMPRESSED")
    lines.append(sep)
    o_lines = _wrap(original, width)
    s_lines = _wrap(squeezed, width)
    rows = max(len(o_lines), len(s_lines))
    o_lines += [""] * (rows - len(o_lines))
    s_lines += [""] * (rows - len(s_lines))
    for o, s in zip(o_lines, s_lines):
        lines.append(f"{o:<{width}} | {s}")
    lines.append("")
    lines.append("RULES FIRED:")
    for idx, hit in enumerate(rules, 1):
        rid = hit.get("rule_id", "?")
        removed = hit.get("removed", "")
        lines.append(f"  {idx}. {rid}: {removed!r}")
    return "\n".join(lines)


def _render_by_rule(artifact: dict) -> str:
    """Group hits by rule_id; show count and removed spans per rule."""
    rules = artifact.get("rules_fired", [])
    grouped: dict = defaultdict(list)
    for hit in rules:
        grouped[hit.get("rule_id", "?")].append(hit)
    lines = [_header(artifact), ""]
    lines.append("BY RULE:")
    for rid in sorted(grouped.keys(), key=lambda r: (-len(grouped[r]), r)):
        hits = grouped[rid]
        total_saved = sum(h.get("tokens_saved", 0) or 0 for h in hits)
        suffix = f", -{total_saved} tok" if total_saved else ""
        lines.append(f"  {rid} ({len(hits)} hit{'s' if len(hits) != 1 else ''}{suffix})")
        for h in hits:
            removed = h.get("removed", "")
            lines.append(f"    - {removed!r}")
    return "\n".join(lines)


def _wrap(text: str, width: int) -> list:
    if not text:
        return [""]
    out: list = []
    for paragraph in text.splitlines() or [""]:
        if not paragraph:
            out.append("")
            continue
        line = ""
        for word in paragraph.split(" "):
            if line and len(line) + 1 + len(word) > width:
                out.append(line)
                line = word
            else:
                line = (line + " " + word) if line else word
            while len(line) > width:
                out.append(line[:width])
                line = line[width:]
        if line:
            out.append(line)
    return out
