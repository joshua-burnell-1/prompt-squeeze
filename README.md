<!-- ABOUTME: Top-level README for the prompt-squeeze Claude Code plugin. -->
<!-- ABOUTME: Documents what the plugin does, install paths, settings, privacy, and platform constraints. -->
# prompt-squeeze

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

## Settings

See [`settings.schema.json`](./settings.schema.json) for the full schema. Keys live under `.claude/settings.json` in your project (or your user-level settings).

| Key | Default | Notes |
| --- | --- | --- |
| `prompt-squeeze.mode` | `advise` | `off` disables hook; `measure` logs only; `replace` reserved for future native rewrite. |
| `prompt-squeeze.warn_threshold` | `800` | Below this, the hook only logs. |
| `prompt-squeeze.notify_threshold` | `0.25` | Minimum compressible fraction to emit a nudge. |
| `prompt-squeeze.hard_limit` | `4000` | If `interactive=true`, prompts above this can be blocked. |
| `prompt-squeeze.interactive` | `false` | Enables the block decision path. |
| `prompt-squeeze.model_override` | `null` | Force a specific model id for cost math. |
| `prompt-squeeze.telemetry` | `local` | `local`, `team`, or `off`. |
| `prompt-squeeze.team_endpoint` | `null` | Reserved for self-hosted team rollup (v0.2). |

## Platform constraint

As of May 2026, Claude Code's `UserPromptSubmit` hook can add context but cannot rewrite the prompt before the model sees it (canonical issue: anthropics/claude-code#27365). The plugin therefore ships in Advisor mode: it measures every prompt and nudges Claude to either respond efficiently or recommend `/squeeze` for the next similar prompt. The `replace` mode is in the schema but inert. When Anthropic ships native prompt replacement, flipping `prompt-squeeze.mode` to `replace` will switch the hook from nudging to rewriting without further changes.

## Methodology

- Pricing: https://platform.claude.com/docs/en/about-claude/pricing
- Energy: 0.39 J/token modern H100 floor, EuroMLSys 2025 (https://euromlsys.eu/pdf/euromlsys25-27.pdf)
- Grid factor: 0.40 kg CO2e/kWh, EIA US average

The energy figure is a floor; production deployments vary 3-10x depending on batch size, sequence length, and hardware mix. The receipt cites the methodology so reviewers can recompute against their own numbers.

## License

Apache-2.0. Copyright 2026 Josh Burnell. See [LICENSE](./LICENSE).
