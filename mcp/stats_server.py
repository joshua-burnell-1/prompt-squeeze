#!/usr/bin/env python3
# ABOUTME: MCP server exposing aggregated prompt-squeeze stats from the local hook log.
# ABOUTME: Tools: personal_stats, team_stats, weekly_report. Reads ~/.claude/prompt-squeeze/log.jsonl.

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

DEFAULT_LOG = Path.home() / ".claude" / "prompt-squeeze" / "log.jsonl"
PRICING_SOURCE = "https://platform.claude.com/docs/en/about-claude/pricing"
ENERGY_SOURCE = "https://euromlsys.eu/pdf/euromlsys25-27.pdf"

WINDOW_RE = re.compile(r"^(\d+)([dh])$")


def _log_path() -> Path:
    override = os.environ.get("PROMPT_SQUEEZE_LOG")
    return Path(override) if override else DEFAULT_LOG


def _parse_window(window: str) -> timedelta:
    m = WINDOW_RE.match(window.strip().lower())
    if not m:
        return timedelta(days=7)
    n = int(m.group(1))
    unit = m.group(2)
    return timedelta(days=n) if unit == "d" else timedelta(hours=n)


def _read_rows(window: str) -> list[dict]:
    path = _log_path()
    if not path.is_file():
        return []
    cutoff = datetime.now(timezone.utc) - _parse_window(window)
    rows: list[dict] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except Exception:
                continue
            ts = row.get("ts")
            if not isinstance(ts, str):
                continue
            try:
                row_dt = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            except Exception:
                continue
            if row_dt >= cutoff:
                rows.append(row)
    return rows


def _aggregate(rows: list[dict]) -> dict:
    prompts = len(rows)
    tokens_saved = sum(int(r.get("achievable_tokens") or 0) for r in rows)
    dollars_saved = sum(float(r.get("estimated_dollars_saved") or 0.0) for r in rows)
    wh_saved = sum(float(r.get("estimated_wh_saved") or 0.0) for r in rows)

    ranked = sorted(
        rows,
        key=lambda r: float(r.get("achievable_pct") or 0.0) * int(r.get("original_tokens") or 0),
        reverse=True,
    )[:5]
    top = [
        {
            "original_tokens": int(r.get("original_tokens") or 0),
            "achievable_tokens": int(r.get("achievable_tokens") or 0),
            "achievable_pct": float(r.get("achievable_pct") or 0.0),
            "estimated_dollars_saved": float(r.get("estimated_dollars_saved") or 0.0),
        }
        for r in ranked
    ]

    return {
        "prompts": prompts,
        "tokens_saved": tokens_saved,
        "dollars_saved": round(dollars_saved, 6),
        "wh_saved": round(wh_saved, 4),
        "top_5_compressions": top,
    }


def personal_stats(window: str = "7d") -> dict:
    rows = _read_rows(window)
    out = _aggregate(rows)
    out["window"] = window
    out["source"] = str(_log_path())
    return out


def team_stats(team_id: str = "local", window: str = "7d") -> dict:
    base = personal_stats(window)
    base["team_id"] = team_id
    base["note"] = (
        "v0.1: team aggregation requires a self-hosted endpoint and is not "
        "implemented. Returning local stats only."
    )
    return base


def weekly_report(window: str = "7d") -> str:
    rows = _read_rows(window)
    agg = _aggregate(rows)
    lines = [
        f"## prompt-squeeze weekly report ({window})",
        "",
        f"- Prompts processed: {agg['prompts']}",
        f"- Tokens saved: {agg['tokens_saved']:,}",
        f"- Estimated dollars saved: ${agg['dollars_saved']:.4f}",
        f"- Estimated energy saved: {agg['wh_saved']:.2f} Wh",
        "",
        "### Top compressions",
    ]
    top3 = agg["top_5_compressions"][:3]
    if not top3:
        lines.append("- (none yet)")
    else:
        for i, item in enumerate(top3, 1):
            pct = item["achievable_pct"] * 100
            lines.append(
                f"{i}. {item['original_tokens']} -> "
                f"{item['original_tokens'] - item['achievable_tokens']} tokens "
                f"({pct:.0f}% reduction)"
            )
    lines.extend([
        "",
        "### Methodology",
        f"- Pricing: {PRICING_SOURCE}",
        f"- Energy: {ENERGY_SOURCE} (0.39 J/token, modern H100 floor)",
        "- Grid factor: 0.40 kg CO2e/kWh (EIA US average)",
    ])
    return "\n".join(lines)


def _serve() -> None:
    from mcp.server.fastmcp import FastMCP

    app = FastMCP("prompt-squeeze-stats")

    @app.tool()
    def personal_stats_tool(window: str = "7d") -> dict:
        """Return aggregated personal prompt-squeeze stats from the local log."""
        return personal_stats(window)

    @app.tool()
    def team_stats_tool(team_id: str = "local", window: str = "7d") -> dict:
        """Return team-aggregated stats. v0.1 returns local stats with a note."""
        return team_stats(team_id, window)

    @app.tool()
    def weekly_report_tool(window: str = "7d") -> str:
        """Return a Slack-ready markdown weekly savings report."""
        return weekly_report(window)

    app.run()


def _self_test() -> int:
    tmp_dir = tempfile.mkdtemp(prefix="ps-mcp-test-")
    log_path = Path(tmp_dir) / "log.jsonl"
    os.environ["PROMPT_SQUEEZE_LOG"] = str(log_path)

    now = datetime.now(timezone.utc)
    rows = [
        {
            "ts": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "session": "abcd",
            "model": "claude-sonnet-4-6",
            "prompt_hash": "h1",
            "original_tokens": 1200,
            "achievable_tokens": 600,
            "achievable_pct": 0.5,
            "estimated_dollars_saved": 0.0018,
            "estimated_wh_saved": 0.065,
            "action": "nudge",
            "user_action": None,
        },
        {
            "ts": (now - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "session": "efgh",
            "model": "claude-sonnet-4-6",
            "prompt_hash": "h2",
            "original_tokens": 2400,
            "achievable_tokens": 1500,
            "achievable_pct": 0.625,
            "estimated_dollars_saved": 0.0045,
            "estimated_wh_saved": 0.16,
            "action": "nudge",
            "user_action": None,
        },
        {
            "ts": (now - timedelta(days=40)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "session": "old1",
            "model": "claude-sonnet-4-6",
            "prompt_hash": "h3",
            "original_tokens": 5000,
            "achievable_tokens": 4000,
            "achievable_pct": 0.8,
            "estimated_dollars_saved": 0.012,
            "estimated_wh_saved": 0.43,
            "action": "nudge",
            "user_action": None,
        },
    ]
    log_path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")

    failures: list[str] = []

    p = personal_stats("7d")
    if p["prompts"] != 2:
        failures.append(f"personal_stats prompts expected 2 got {p['prompts']}")
    if p["tokens_saved"] != 2100:
        failures.append(f"personal_stats tokens_saved expected 2100 got {p['tokens_saved']}")

    t = team_stats(window="7d")
    if "note" not in t or "v0.1" not in t["note"]:
        failures.append("team_stats missing v0.1 note")

    p30 = personal_stats("30d")
    if p30["prompts"] != 2:
        failures.append(f"30d window expected 2 got {p30['prompts']}")

    p_all = personal_stats("90d")
    if p_all["prompts"] != 3:
        failures.append(f"90d window expected 3 got {p_all['prompts']}")

    report = weekly_report("7d")
    for needle in ("prompt-squeeze weekly report", "Prompts processed: 2", "Methodology"):
        if needle not in report:
            failures.append(f"weekly_report missing {needle!r}")
    if "h1" in report or "h2" in report:
        failures.append("weekly_report leaked prompt hashes")

    sys.stderr.write("personal_stats(7d) =>\n")
    sys.stderr.write(json.dumps(p, indent=2) + "\n\n")
    sys.stderr.write("weekly_report(7d) =>\n")
    sys.stderr.write(report + "\n\n")

    if failures:
        for f in failures:
            sys.stderr.write(f"FAIL: {f}\n")
        return 1
    sys.stderr.write("ALL PASS\n")
    return 0


def main() -> int:
    if "--self-test" in sys.argv:
        return _self_test()
    _serve()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
