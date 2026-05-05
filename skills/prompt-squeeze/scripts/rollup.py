# ABOUTME: Rollup — derive cumulative savings totals from log.jsonl for status-line + /squeeze-stats.
# ABOUTME: Counts only REALIZED savings (block + downstream /sq y) toward the headline number.

from __future__ import annotations

import json
from datetime import datetime, timezone  # noqa: UP017
from pathlib import Path

# Wh-to-equivalent conversion table. Each entry is (upper_bound_wh, formatter).
# Energy figures sourced from Plan D spec section 6.
_PHONE_WH = 17.0  # ~17 Wh to fully charge a typical smartphone
_LAPTOP_HOUR_WH = 50.0  # ~50 Wh per hour of typical laptop use
_LED_HOUR_WH = 0.5  # ~0.5 Wh per hour for an LED bulb


def _is_realized(row: dict) -> bool:
    """A log row counts as realized iff the user accepted the squeeze (action=block_*, user_action=y)."""
    action = row.get("action", "")
    if not action.startswith("block"):
        return False
    return row.get("user_action") == "y"


def _is_analyzed_only(row: dict) -> bool:
    """A row was analyzed but not realized — savings are potential, not actual."""
    action = row.get("action", "")
    if action.startswith("block") and row.get("user_action") != "y":
        return True
    if action == "nudge":
        return True
    return False


def compute_totals(log_path: Path, today: str | None = None) -> dict:
    """Walk log.jsonl and produce a totals dict.

    `today` is an ISO date prefix (YYYY-MM-DD). When provided, today_* fields are
    populated by matching row ts against this prefix. Defaults to current UTC date."""
    if today is None:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    totals = {
        "lifetime_tokens_saved": 0,
        "lifetime_dollars_saved": 0.0,
        "lifetime_wh_saved": 0.0,
        "lifetime_prompts_realized": 0,
        "lifetime_tokens_analyzed_only": 0,
        "today_tokens_saved": 0,
        "today_dollars_saved": 0.0,
        "today_wh_saved": 0.0,
        "today_prompts_realized": 0,
    }

    if not log_path.is_file():
        return totals

    with open(log_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue

            ts = row.get("ts", "")
            tok = int(row.get("achievable_tokens") or 0)
            dollars = float(row.get("estimated_dollars_saved") or 0.0)
            wh = float(row.get("estimated_wh_saved") or 0.0)

            if _is_realized(row):
                totals["lifetime_tokens_saved"] += tok
                totals["lifetime_dollars_saved"] += dollars
                totals["lifetime_wh_saved"] += wh
                totals["lifetime_prompts_realized"] += 1
                if ts.startswith(today):
                    totals["today_tokens_saved"] += tok
                    totals["today_dollars_saved"] += dollars
                    totals["today_wh_saved"] += wh
                    totals["today_prompts_realized"] += 1
            elif _is_analyzed_only(row):
                totals["lifetime_tokens_analyzed_only"] += tok

    return totals


def format_wh_equivalent(wh: float) -> str:
    """Render Wh in user-friendly equivalents (phone charges, laptop hours, kWh)."""
    if wh < 5:
        return f"{wh:.1f} Wh"
    if wh < 50:
        hours = wh / _LED_HOUR_WH
        return f"{hours:.0f} LED-bulb hours"
    if wh < 500:
        charges = wh / _PHONE_WH
        return f"{charges:.0f} phone charges"
    if wh < 5000:
        hours = wh / _LAPTOP_HOUR_WH
        return f"{hours:.0f} hours of laptop use"
    return f"{wh / 1000:.1f} kWh"


def format_status_line(totals: dict) -> str:
    """Render the compact status-line string used by the IDE prompt area."""
    today = totals.get("today_tokens_saved", 0)
    lifetime = totals.get("lifetime_tokens_saved", 0)
    wh = totals.get("lifetime_wh_saved", 0.0)
    if lifetime == 0 and today == 0:
        return "squeeze: 0 saved (run a long prompt with prompt-squeeze on)"
    eq = format_wh_equivalent(wh)
    today_str = f"-{today:,} tok" if today else "0 tok"
    lifetime_str = f"-{lifetime:,} tok / {wh:.1f} Wh ~= {eq}"
    return f"squeeze: today {today_str} | lifetime {lifetime_str}"


def write_totals(log_path: Path, totals_path: Path) -> bool:
    """Compute totals from log_path and write to totals_path. Returns True on success."""
    try:
        totals = compute_totals(log_path)
        totals["computed_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        totals_path.parent.mkdir(parents=True, exist_ok=True)
        totals_path.write_text(json.dumps(totals, indent=2), encoding="utf-8")
        return True
    except OSError:
        return False
