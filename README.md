<!-- ABOUTME: Top-level README for the prompt-squeeze Claude Code plugin. -->
<!-- ABOUTME: Documents what the plugin does, install paths, settings, privacy, and platform constraints. -->
# prompt-squeeze

[![ci](https://github.com/joshua-burnell-1/prompt-squeeze/actions/workflows/ci.yml/badge.svg)](https://github.com/joshua-burnell-1/prompt-squeeze/actions/workflows/ci.yml) [![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](./LICENSE)

A Claude Code plugin that compresses long prompts into the bare minimum an LLM still understands, blocks bloated prompts before they ship, and reports cumulative tokens / dollars / Wh saved across a session, project, or team. Pairs an eval-gated deterministic compression skill with a `UserPromptSubmit` hook and a refill-counter-style status line so the savings stay visible without leaving the editor.

## Why

Prompt cost is the cheapest engineering discipline most teams haven't built yet. v0.4 turns prompt-squeeze from "nudge to compress later" into "compress now or send original" — every long prompt is a one-keystroke decision (`/sq y` to send the squeezed version) instead of an unbilled-token leak. The plugin wraps the compression skill with four surfaces:

- A `UserPromptSubmit` hook that **blocks** prompts above a token threshold and shows you the compressed version with realized savings.
- The `/sq` slash command suite — `/sq y`, `/sq y session`, `/sq n`, `/sq undo`, `/sq off` — to confirm or skip squeeze, opt in for the rest of a session, or opt out entirely.
- An opt-in `/sq explain` deep-dive that shows rule-by-rule attribution for any squeeze (locally redacted, never transmitted).
- A status-line counter that compounds your savings across the day like a water-bottle refill station: `squeeze: today -4,217 tok | lifetime -187k tok / 70 Wh ≈ 4 phone charges`.

The framing is **prompt literacy + realized savings + ambient visibility**: rewrite prompts the LLM understands but with fewer tokens, see what each one cost, watch the lifetime tally compound.

## Install

Direct install from this repo (the recommended path while marketplace listing is pending review):

```bash
git clone https://github.com/joshua-burnell-1/prompt-squeeze ~/.claude/plugins/local/prompt-squeeze
```

Add to `~/.claude/settings.json`:

```json
{
  "hooks": {
    "UserPromptSubmit": [
      {
        "hooks": [
          { "type": "command", "command": "python3 ~/.claude/plugins/local/prompt-squeeze/hooks/user_prompt_submit.py" }
        ]
      }
    ]
  }
}
```

Then start a fresh `claude` session — the `UserPromptSubmit` hook registers at session start. Slash commands (`/sq`, `/squeeze`, `/squeeze-stats`, `/squeeze-config`) auto-discover from the repo's `commands/` directory.

> **Note:** A Claude Code plugin marketplace listing is in review. Once approved, install will simplify to one line. The direct-clone path above stays supported indefinitely.

### Runtime requirements

The hook runs with whatever `python3` is on your `PATH` and degrades gracefully:

- `tiktoken` if available for accurate cl100k token counts; falls back to a `len(text.split()) * 1.3` approximation otherwise.
- The skill's compress + estimate scripts use stdlib only (no external deps required at runtime).
- The MCP rollup server requires the `mcp` Python package — install with `pip install mcp` if you want the `/squeeze-stats` and weekly report tools.

For development (eval harness, judge, tests), use `uv sync --extra dev` from the repo root.

## Usage (v0.4 default)

Just type. The hook does the rest.

```text
> Could you please help me refactor this 800-line module into smaller files?
  I think it would be great if you could split out the auth logic, the database
  layer, and the request handlers into their own modules. I want to make sure...
  [continues for 1,200 tokens]

prompt-squeeze: your prompt is 1,248 tokens. A compressed version saves
487 tokens (~$0.0009, ~0.31 Wh).

ORIGINAL (1248 tok)                    | COMPRESSED (761 tok, -39%)
---------------------------------------+-------------------------------------
Could you please help me refactor this | Refactor this 800-line module into
800-line module into smaller files?    | smaller files. Split out auth logic,
I think it would be great if you could | database layer, and request handlers
split out the auth logic, the database | into their own modules. Make sure...
layer, and the request handlers into   |
...                                    |

Reply with one of:
  /sq y          send the squeezed version once
  /sq y session  send squeezed AND auto-confirm for the rest of this session
  /sq n          send your original prompt unchanged
  /sq off        disable prompt-squeeze for the rest of this session
```

After `/sq y session`, subsequent long prompts get a terse one-liner — `prompt-squeeze auto: 940 → 612 tok (-35%) ...` — and a single `/sq y` confirms.

### Other commands

- `/sq undo` — resend the most recent prompt as its original (requires `/sq explain on`)
- `/sq explain` / `/sq explain --side` / `/sq explain --by-rule` — inspect rule-by-rule attribution for the most recent squeeze (requires `/sq explain on` first)
- `/squeeze` — manual one-off: compress arbitrary text and show a receipt
- `/squeeze-stats` — personal savings report (e.g. `/squeeze-stats 30d`)
- `/squeeze-config` — inspect or change settings inline

## Privacy

- **Local-only by default.** Nothing leaves your machine.
- **`log.jsonl` stores hashes only.** `~/.claude/prompt-squeeze/log.jsonl` records token counts, dollar/Wh estimates, and a 16-character SHA-256 prefix per prompt and session. It never stores raw prompt text.
- **`/sq explain` is opt-in.** Default OFF. When enabled (`/sq explain on`), per-squeeze artifacts at `~/.claude/prompt-squeeze/explain/` store the original + squeezed text + rule hits with **secrets pre-redacted** (sk-`...`, ghp_`...`, AWS access keys, JWT-shaped strings, RFC-5321 emails). Capped at the last 100 squeezes. Never transmitted. `/sq explain off` disables and removes everything.
- **`prompt-squeeze.telemetry = "off"`** disables logging entirely.
- **Team aggregation** is opt-in (`telemetry=team` plus a configured `team_endpoint`) and is not yet implemented; the field is reserved for a self-hosted rollup.

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

## Status line (v0.4)

prompt-squeeze emits a compact cumulative-savings line you can plug into Claude Code's status-line config. Add this to `~/.claude/settings.json` (assumes the direct-clone install path from the install section above):

```json
{
  "statusLine": "python3 ~/.claude/plugins/local/prompt-squeeze/skills/prompt-squeeze/scripts/status_line.py"
}
```

Then your Claude Code prompt area shows:

```
squeeze: today -4,217 tok | lifetime -187,304 tok / 70.1 Wh ~= 4 phone charges
```

Format scales with how much you've saved: small numbers show raw Wh, mid-range shows phone-charge-equivalents, larger shows hours of laptop use, very large shows kWh. Counts only **realized** savings (block + `/sq y`), never aspirational nudges. Updated automatically each time the hook fires.

## Deep-dive (v0.4, opt-in)

To inspect rule-by-rule attribution for any squeeze, enable the explain feature first:

```
/sq explain on
```

This writes a redacted artifact at `~/.claude/prompt-squeeze/explain/<session>-<seq>.json` for each squeeze (last 100 retained, secrets stripped, never transmitted). Then:

- `/sq explain` — inline annotated diff with footnoted rule attribution
- `/sq explain --side` — side-by-side ORIGINAL | COMPRESSED with rules listed below
- `/sq explain --by-rule` — group hits by rule_id, show frequency

Run `/sq explain off` to disable and remove all stored artifacts.

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

### 0.4.0 (2026-05-05)

- **Default flips to interactive blocking.** `mode=interactive` is the new default; long prompts (>500 tokens) are blocked and offered for squeeze with a side-by-side diff. v0.3 nudge-only behavior preserved via `mode=advise`.
- **One-time-per-session consent flow.** First long prompt shows the full banner with three choices (`/sq y` once / `/sq y session` rest-of-session / `/sq n` original). Subsequent long prompts get a terse one-liner banner that takes a single `/sq y` to confirm.
- **`/sq` slash command suite:** `/sq y`, `/sq y session`, `/sq n`, `/sq undo`, `/sq off` for the runtime flow; `/sq explain`, `/sq explain on/off`, `/sq explain --side`, `/sq explain --by-rule` for the deep-dive.
- **Per-squeeze deep-dive (opt-in).** Enable with `/sq explain on`; future squeezes write a redacted artifact at `~/.claude/prompt-squeeze/explain/`. Three render modes (inline diff, side-by-side, by-rule). Last 100 retained, secrets stripped, never transmitted.
- **Persistent compounded savings.** A new `rollup` module derives cumulative tokens/dollars/Wh from `log.jsonl`. The included `status_line.py` emits a compact "today / lifetime" string for Claude Code's status line ("squeeze: today -4,217 tok | lifetime -187k tok / 70 Wh ≈ 4 phone charges").
- **Honest accounting.** Only prompts the user actually approved (`block` + `user_action=y`) count toward "saved." Analyzed-but-skipped prompts roll up under a separate `analyzed_only` counter.
- **Settings:** new `block_threshold` (default 500), `explain` (default `off`), `mode` enum extended to include `interactive`.

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
