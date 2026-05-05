<!-- ABOUTME: Top-level README for the prompt-squeeze Claude Code plugin. -->
<!-- ABOUTME: Documents what the plugin does, install paths, settings, privacy, and platform constraints. -->
# prompt-squeeze

[![ci](https://github.com/joshua-burnell-1/prompt-squeeze/actions/workflows/ci.yml/badge.svg)](https://github.com/joshua-burnell-1/prompt-squeeze/actions/workflows/ci.yml) [![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](./LICENSE)

A Claude Code plugin that measures every prompt you send, surfaces avoidable spend, and reports cumulative dollar/Wh savings across a session, a project, or a team. Pairs a deterministic compression skill with a `UserPromptSubmit` hook and an MCP rollup so cost and sustainability stay visible without leaving the editor.

## Why

Prompt cost is the cheapest engineering discipline most teams haven't built yet. The `prompt-squeeze` skill turns a prompt into a smaller, equivalent prompt with a cited receipt (dollars saved, Wh saved, CO2e at US-grid average). The plugin wraps the skill with three surfaces:

- A hook that meters every prompt and nudges you toward `/squeeze` when meaningful savings exist.
- Slash commands (`/squeeze`, `/squeeze-stats`, `/squeeze-config`) for on-demand compression, personal stats, and configuration.
- An MCP server that aggregates the local log into weekly markdown reports.

The framing is prompt literacy plus visibility plus sustainability: write tighter prompts, see what they cost, and report the cumulative footprint.

## Install

From inside Claude Code:

```
/plugin marketplace add joshua-burnell-1/claude-plugins
/plugin install prompt-squeeze@joshua-burnell-1
```

Then start a fresh `claude` session — the `UserPromptSubmit` hook registers at session start.

### Runtime requirements

The hook runs with whatever `python3` is on your `PATH` and degrades gracefully:

- `tiktoken` if available for accurate cl100k token counts; falls back to a `len(text.split()) * 1.3` approximation otherwise.
- The skill's compress + estimate scripts use stdlib only (no external deps required at runtime).
- The MCP rollup server requires the `mcp` Python package — install with `pip install mcp` if you want the `/squeeze-stats` and weekly report tools.

For development (eval harness, judge, tests), use `uv sync --extra dev` from the repo root.

## Usage

Compress a prompt and view the savings receipt:

```
/squeeze Please could you kindly help me write a function that ...
```

Show personal savings for the last 7 days:

```
/squeeze-stats
/squeeze-stats 30d
```

Inspect or change settings:

```
/squeeze-config
```

The `UserPromptSubmit` hook fires on every prompt. When your prompt clears the warn threshold (default 800 tokens) and at least 25 percent of it is compressible, Claude receives an `additionalContext` nudge with the achievable savings and a pointer to `/squeeze`.

## Privacy

- Local-only by default. Nothing leaves your machine.
- The hook log (`~/.claude/prompt-squeeze/log.jsonl`) records token counts, dollar/Wh estimates, and a 16-character SHA-256 prefix for each prompt and session. It never stores raw prompt text.
- Setting `prompt-squeeze.telemetry` to `off` disables logging entirely.
- Team aggregation is opt-in (`telemetry=team` plus a configured `team_endpoint`) and is not implemented in v0.1.

## Settings (v0.4)

See [`settings.schema.json`](./settings.schema.json) for the full schema. Keys live under `.claude/settings.json` in your project (or your user-level settings).

| Key | Default | Notes |
| --- | --- | --- |
| `prompt-squeeze.mode` | `interactive` | `off` disables; `advise` is v0.3 behavior (nudge only); `interactive` blocks long prompts and offers `/sq y` (v0.4 default). |
| `prompt-squeeze.block_threshold` | `500` | v0.4: prompts above this token count are blocked in interactive mode. |
| `prompt-squeeze.explain` | `off` | When `on`, per-squeeze artifacts are stored locally for `/sq explain` and `/sq undo`. Opt-in. |
| `prompt-squeeze.warn_threshold` | `800` | Legacy v0.3 advise-mode threshold. Honored when `mode == "advise"`. |
| `prompt-squeeze.notify_threshold` | `0.25` | Min compressible fraction to nudge in advise mode. |
| `prompt-squeeze.model_override` | `null` | Force a specific model id for cost math. |
| `prompt-squeeze.telemetry` | `local` | `local`, `team`, or `off`. |
| `prompt-squeeze.team_endpoint` | `null` | Reserved for self-hosted team rollup. |

## v0.4 default flow (interactive blocking)

1. You type a prompt > 500 tokens.
2. The hook blocks submission and shows a side-by-side diff with savings:
   `prompt-squeeze: your prompt is 1,248 tokens. A compressed version saves 487 tokens (~$0.0009, ~0.31 Wh).`
3. Reply with one of:
   - `/sq y` — send the squeezed version once
   - `/sq y session` — send squeezed AND auto-confirm for the rest of this session
   - `/sq n` — send your original prompt unchanged
   - `/sq off` — disable prompt-squeeze for the rest of this session
4. After `/sq y session`, subsequent long prompts auto-block with a terse one-liner (`prompt-squeeze auto: 940 → 612 tok (-35%) ...`); `/sq y` confirms in one keystroke.
5. Escape hatches: `/sq off` (disable for session) and `/sq undo` (resend last as original; requires `explain: on`).

## Platform constraint

As of May 2026, Claude Code's `UserPromptSubmit` hook can add context or block submission, but cannot silently rewrite the prompt before the model sees it (canonical issue: anthropics/claude-code#27365). v0.4's default `interactive` mode works around this: the hook blocks the long prompt, caches both the original and squeezed versions, and the user's `/sq y` slash command submits the squeezed text as the next user message. When Anthropic ships native prompt replacement, the `replace` mode in the schema becomes available and the consent flow simplifies to a one-time-only banner.

## Migration from v0.3

v0.4 flips the default from `advise` (nudge only) to `interactive` (block + `/sq y`). If you preferred v0.3's behavior, opt out with:

```json
{ "prompt-squeeze.mode": "advise" }
```

The v0.3 nudge path is preserved exactly — the hook continues to emit `additionalContext` recommending `/squeeze` instead of blocking.

## Methodology

- Pricing: https://platform.claude.com/docs/en/about-claude/pricing
- Energy: 0.39 J/token modern H100 floor, EuroMLSys 2025 (https://euromlsys.eu/pdf/euromlsys25-27.pdf)
- Grid factor: 0.40 kg CO2e/kWh, EIA US average

The energy figure is a floor; production deployments vary 3-10x depending on batch size, sequence length, and hardware mix. The receipt cites the methodology so reviewers can recompute against their own numbers.

## Changelog

### 0.3.3 (2026-05-05)

- **Compression layer rewrite:** rules now live in a typed `Rule` registry with stable IDs (`skills/prompt-squeeze/scripts/rules.py`), setting up `/sq explain` rule attribution in v0.4
- **Bug fix:** `for the purpose of` is now context-gated — only swaps to `to` when followed by a verb-ing form, fixing the v0.3 0.72-fidelity outlier (`explain_03`)
- **Bug fix:** post-strip capitalization — sentences whose head was dropped by filler removal are re-capitalized (with iOS-safe lookahead so camelCase identifiers stay intact)
- **New aggressive rules** (all eval-gated, drop only when fidelity contract holds): expanded politeness ("if you have a moment", "sorry to bother you"), verbose connectors ("with respect to", "in terms of", "as a matter of fact"), redundant qualifiers ("very", "really", "actually", "basically"), imperative collapse ("I would like you to" → drop), narrow article dropping ("The function" → "Function" at sentence start)
- **Rule composition fixes:** patterns now consume trailing `you might/could/would (be able to)` and `if you <verb>` to avoid wrong-subject sentence heads after stripping
- **Eval contract enforced in CI:** median fidelity ≥ 0.95, 5th-percentile within 0.03 of v0.3 baseline, no individual prompt regresses more than 0.05. Any rule that breaks the gate is rejected automatically.

Default behavior is unchanged — the hook still operates in advise mode. v0.4 (next release) will flip the default to interactive blocking for realized savings.

## License

Apache-2.0. Copyright 2026 Josh Burnell. See [LICENSE](./LICENSE).
