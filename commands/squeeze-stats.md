---
name: squeeze-stats
description: Show personal prompt-squeeze savings (last 7 days)
argument-hint: "[window e.g. 7d, 30d, 24h]"
---

<!-- ABOUTME: Slash command that prints the user's last-7-day prompt-squeeze savings rollup. -->
<!-- ABOUTME: Reads from the prompt-squeeze-stats MCP server, which aggregates the local hook log. -->

Call the MCP tool `prompt-squeeze-stats.personal_stats` with the user's window argument, defaulting to `7d` when none is given.

Render the result as a short markdown block:

- Window
- Prompts processed
- Tokens saved (formatted with thousands separators)
- Estimated dollars saved (4 decimals)
- Estimated energy saved (Wh, 2 decimals)
- Top compressions (original tokens, percent reduction, dollars saved)

Close with a one-line pointer: "Full report: run `/squeeze-stats 30d` or ask for `weekly_report`." Do not invent numbers; if the tool returns zero prompts, say so plainly.
