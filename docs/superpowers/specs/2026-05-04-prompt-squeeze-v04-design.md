<!-- ABOUTME: Design spec for prompt-squeeze v0.4 — aggressive LLM-comprehension compression, -->
<!-- ABOUTME: interactive blocking by default, persistent compounded savings, opt-in deep-dive. -->

# prompt-squeeze v0.4 — Aggressive LLM-comprehension compression with realized savings

**Date:** 2026-05-04
**Branch:** `v0.4-aggressive`
**Status:** Draft, awaiting user review

## Goal

Produce the bare-minimum prompt that an LLM still understands, save real (not aspirational) tokens and energy, and make the savings visible enough that users feel the compounding impact across a day of coding.

The compression target is **LLM comprehension**, not human readability. If a squeezed prompt does not read smoothly, that is acceptable provided the LLM produces equivalent output. The eval is the contract that holds this line.

## Constraints

- **Platform constraint (still binding as of 2026-05-04):** `UserPromptSubmit` hooks can emit `additionalContext` or `decision: block` only — they cannot rewrite the user's prompt. Tracked at anthropics/claude-code#27365. Real savings therefore require the user to confirm a swap, not silent rewriting. This shapes the consent flow.
- **Eval contract:** No new compression rule ships unless the 100-prompt eval keeps median fidelity ≥ 0.95, 5th-percentile ≥ 0.85, and no prompt currently scoring ≥ 0.95 regresses. The eval is wired into CI; failing rules are rejected automatically.
- **Privacy floor:** `log.jsonl` continues to store hashes only. The new explain artifact is opt-in, local-only, secret-redacted, capped at 100 entries, and never transmitted.

## Architecture

Six new or modified components, plus a rule-set expansion behind the existing skill:

```
                               ┌─────────────────────────────────────────────────┐
user prompt ──► UserPromptSubmit hook ──► compression (skill scripts) ──► block? │
                       │                          │                              │
                       ▼                          ▼                              │
              session consent state       per-squeeze artifact                   │
              (~/.claude/prompt-          (opt-in, redacted)                     │
               squeeze/sessions/)                                                │
                       │                          │                              │
                       ▼                          ▼                              │
              pending squeeze cache    /sq explain renderers                     │
                       │                                                         │
                       ▼                                                         │
              /sq y, /sq n, /sq undo, /sq off slash commands ──────► resume ◄────┘

log.jsonl (hashes only) ──► rollup derivation ──► status-line counter
                                                  /squeeze-stats
```

Components communicate through files in `~/.claude/prompt-squeeze/`. No new daemons, no network calls.

## Components

### 1. Compression rule set + eval gates

**Purpose:** Expand `skills/prompt-squeeze/scripts/compress.py` with rules that drop tokens an LLM does not need, while the eval CI rejects any rule that breaks the fidelity contract.

**New rule categories under exploration (not all will ship — eval decides):**

- Article dropping (`the`, `a`, `an`) where unambiguous
- Pronoun dropping at sentence start (`I want to...` → `Want to...` or imperative form)
- Politeness markers beyond the v0.3 list (`could you`, `would you mind`, `if it's not too much trouble`)
- Verbose connectors (`for the purpose of`, `with respect to`, `in terms of`, `in order to`)
- Helping-verb collapses (`I would like to → I want`, then `→ Ø` if imperative possible)
- Redundant qualifiers when already implied (`thoroughly explain` → `explain` if context is detailed)
- Repetition collapse (the same instruction stated twice in different phrasing)

**Two known v0.3 bugs fixed under this same component:**

1. The `for the purpose of → to` swap was the 0.72 fidelity outlier. Rules with semantic-loss risk (causal `for the purpose of`, conditional `provided that`) are reclassified as **context-gated**: they fire only when surrounding tokens supply the dropped meaning. Each context-gated rule has its own eval row.
2. Capitalization regression after filler stripping. A post-pass capitalizes the first letter of any sentence whose head was dropped. Implemented as a final stage after all token-removal rules.

**Eval gate (enforced in CI via `.github/workflows/ci.yml`):**

- Median fidelity ≥ 0.95 across the 100-prompt eval set
- 5th-percentile fidelity ≥ 0.85
- No prompt currently scoring ≥ 0.95 regresses below 0.95
- A new test fails the build if any of the above is violated

**Interface:** Same `compress(text: str) -> str` entry point. Internals reorganize into a rule registry where each rule has `id`, `pattern`, `replacement`, `context_gate?`, `confidence_score` from eval.

**Dependencies:** `skills/prompt-squeeze/scripts/compress.py`, `skills/prompt-squeeze/scripts/eval/run_eval.py`, `skills/prompt-squeeze/data/eval_set.jsonl`. The eval set may grow during implementation if existing prompts do not exercise new rule categories — additions need user review since they shape what "passing eval" means.

### 2. UserPromptSubmit hook — interactive blocking by default

**Purpose:** Convert the hook from advise-mode-by-default to interactive-block-by-default so savings become real, not aspirational.

**Behavioral changes from v0.3:**

- `mode` default flips from `"advise"` to `"interactive"`
- `interactive` setting is removed (folded into `mode`)
- `hard_limit` semantics change: now the threshold above which blocking activates (default lowered from 4000 to 500 tokens to catch typical long prompts)
- `warn_threshold` removed — single threshold (`block_threshold`) governs the entire flow
- New `mode: "advise"` retained as opt-out for users who want v0.3 behavior

**Per-prompt flow (new):**

1. Hook receives prompt P
2. Tokenizes; if below `block_threshold` (default 500 tokens), no-op (log measurement only)
3. Reads session consent state from `~/.claude/prompt-squeeze/sessions/<session_hash>.json`. State is one of three values:
   - `null` (no decision yet this session) → continue to compression + full banner
   - `"yes-session"` → continue to compression + terse banner
   - `"no"` (user opted out via `/sq off`) → no-op, log measurement only, allow original prompt through
4. Runs Stage 1 compression → P'
5. Computes savings receipt
6. Writes pending entry to `~/.claude/prompt-squeeze/pending.json` keyed by session hash
7. If explain is enabled, writes the per-squeeze artifact (see §4)
8. Returns `decision: block` with reason text scaled to consent state:
   - **`null`:** Full banner — side-by-side diff, savings summary, three choices (`/sq y` once, `/sq y session` for rest of session, `/sq n` original)
   - **`"yes-session"`:** Terse one-liner — `auto: 1,248 → 761 tok (-39%) • saved $0.0009, 0.31 Wh • /sq y to send squeezed, /sq n to send original`
9. Surfaces a one-line transcript-visible message confirming the analysis happened (Option A visibility). The exact Claude Code mechanism — whether `hookSpecificOutput.systemMessage` renders user-visibly, or whether the visibility has to ride inside `decision: block`'s `reason` field — is verified during writing-plans (see Open Questions).

**Honest framing (load-bearing):** Even with session consent, the user still types `/sq y` per long prompt. This is not zero-friction — the platform constraint forbids that. v0.4 reduces friction from "read banner + decide + type" to "type one command." The spec calls this out so users are not surprised.

**Interface:** Stdin = hook payload JSON, stdout = hook response JSON. Same shape as v0.3. New side-effect files documented above.

**Dependencies:** `hooks/user_prompt_submit.py`, `skills/prompt-squeeze/scripts/compress.py`, `skills/prompt-squeeze/scripts/estimate.py`.

### 3. Pending cache + recovery commands

**Purpose:** Allow `/sq y` and friends to inject the cached squeezed prompt as the next user message.

**Cache file:** `~/.claude/prompt-squeeze/pending.json`

```json
{
  "<session_hash>": {
    "seq": 7,
    "ts": "2026-05-04T18:23:11Z",
    "original_text": "...",
    "squeezed_text": "...",
    "tokens_original": 1248,
    "tokens_squeezed": 761,
    "saved_dollars": 0.0009,
    "saved_wh": 0.31,
    "consumed": false
  }
}
```

`original_text` is stored only when explain is enabled; otherwise the field is absent and `/sq undo` returns `original artifact unavailable — explain feature is off`.

**Slash commands (new, all in `commands/`):**

| Command | Behavior |
|---|---|
| `/sq y` | Read pending entry, submit `squeezed_text` as next user message, mark consumed |
| `/sq y session` | Same as `/sq y`, AND set session consent to `"yes-session"` |
| `/sq n` | Submit `original_text` and mark consumed. If explain is disabled, `original_text` was never stored — command instead instructs the user to retype their prompt and notes that enabling explain would avoid this in future |
| `/sq undo` | Resubmit the most recent consumed entry's `original_text`. Useful when an auto-squeeze degraded results. Requires explain enabled |
| `/sq off` | Set session consent to `"no"` for the rest of the session — no more blocking |
| `/sq explain` | Render deep-dive (Option A); see §5 |
| `/sq explain --side` | Render deep-dive (Option B) |
| `/sq explain --by-rule` | Render deep-dive (Option C) |
| `/sq explain on` / `off` | Toggle the explain feature in user settings |

**Mechanism:** Slash command markdown files instruct Claude to `Read` the cache file, take the appropriate action, and emit the squeezed (or original) text as the next user-message-equivalent. This costs ~50 Claude tokens per recovery — much smaller than the savings on the squeezed prompt itself.

**Dependencies:** `commands/sq.md` (or split into multiple files; tactical decision in writing-plans), `~/.claude/prompt-squeeze/pending.json`, `~/.claude/prompt-squeeze/sessions/<session_hash>.json`.

### 4. Per-squeeze artifact + privacy controls

**Purpose:** Persist the data needed to render `/sq explain` deep-dives, with explicit user opt-in and strong local-only guarantees.

**Default state:** OFF. Setting `prompt-squeeze.explain` defaults to `"off"`. Users enable via `/sq explain on` (which writes the setting to `~/.claude/settings.json`).

**Artifact location:** `~/.claude/prompt-squeeze/explain/<session_hash>-<seq>.json`

```json
{
  "ts": "2026-05-04T18:23:11Z",
  "session": "<hash>",
  "seq": 7,
  "original_text": "<redacted>",
  "squeezed_text": "<redacted>",
  "tokens_original": 1248,
  "tokens_squeezed": 761,
  "rules_fired": [
    {"rule_id": "POLITENESS_FILLER", "span": [0, 19], "removed": "Could you please ", "tokens_saved": 4},
    ...
  ]
}
```

**Privacy guarantees:**

- Default off — explicit opt-in required
- Directory `0700`, files `0600`
- Pre-write redaction: regex strip of OpenAI-shaped (`sk-...`), GitHub-shaped (`ghp_...`), AWS access keys (`AKIA...`), JWT-shaped strings, RFC-5321 emails. Replacement token: `<REDACTED:secret>`. The same redaction is applied to spans inside `rules_fired`.
- Retention: last 100 entries, FIFO eviction on write
- Never transmitted, even when `telemetry: "team"` is set in some future version
- `/sq explain off` disables and removes `~/.claude/prompt-squeeze/explain/` entirely

**Interface:** Read by deep-dive renderers. Written by the hook only when `prompt-squeeze.explain == "on"`.

**Dependencies:** `hooks/user_prompt_submit.py`, new `~/.claude/prompt-squeeze/explain/` directory.

### 5. Deep-dive renderers (`/sq explain`)

**Purpose:** Let users audit what the squeezer changed and why, so they can build trust (or catch bad rules) when auto-mode is active.

**Three render modes, all reading from the same artifact:**

- **`/sq explain` (default — Option A):** Inline annotated diff. Original prompt with strikethrough on removed spans, each removal footnoted to its rule:
  ```
  Could you¹ please² help me to³ write a function that takes a list of integers...

  ¹ POLITENESS_VERB · saved 2 tok
  ² POLITENESS_FILLER · saved 1 tok
  ³ VERBOSE_TO · saved 2 tok
  ```

- **`/sq explain --side` (Option B):** Side-by-side with original on left, squeezed on right, rule annotations between. Best when many rule hits cluster.

- **`/sq explain --by-rule` (Option C):** Rule-grouped breakdown. Lists each rule that fired with all hits clustered. Best for rule-set audits.

**Selection of which squeeze to explain:** No argument = most recent. Optional positional argument = relative index (e.g., `/sq explain 3` for third-most-recent).

**Renderer location:** `skills/prompt-squeeze/scripts/explain.py`. Pure function `(artifact_dict, mode) -> str`. Slash command files instruct Claude to invoke this script and print its output.

**Dependencies:** Per-squeeze artifact (§4), new `skills/prompt-squeeze/scripts/explain.py`.

### 6. Status-line cumulative counter ("refill-counter")

**Purpose:** Make compounded savings visible across a day of coding, the way water-bottle stations show cumulative bottles diverted.

**Format:**

```
🌱 squeeze: today -4,217 tok | lifetime -187k tok / 70 Wh ≈ 2 phone charges
```

**Data source:** Existing `log.jsonl` is already per-prompt. A small derivation script (`mcp/rollup.py` or similar) reads the log, computes today's and lifetime totals, and writes to `~/.claude/prompt-squeeze/totals.json`. The status line reads from `totals.json`.

**Wh-to-equivalent table:**

| Wh range | Equivalent shown |
|---|---|
| < 5 | `≈ X Wh` (raw) |
| 5–50 | `≈ N LED-bulb hours` |
| 50–500 | `≈ N phone charges` |
| 500–5000 | `≈ N hours of laptop use` |
| > 5000 | `≈ N kWh` (raw kWh, with EV-mile flavor) |

**Update cadence:** Hook writes a small marker after each log row; status-line reader recomputes if the marker is newer than `totals.json`. No background daemon.

**Counts what was actually realized:** Only entries with `action == "block"` and downstream `/sq y` consumption count toward "saved." Analyzed-but-not-realized prompts roll up under a separate `analyzed_only` counter, surfaced in `/squeeze-stats` but not the main "saved" number, to keep the headline honest.

**Dependencies:** `log.jsonl` (existing), new `mcp/rollup.py` or `skills/prompt-squeeze/scripts/rollup.py`, new `~/.claude/prompt-squeeze/totals.json`, status-line config snippet documented in `README.md`.

## Per-prompt data flow

**First long prompt of a session, no consent yet (explain off — the default state):**

1. User types prompt P (1,248 tok), hits enter
2. Hook fires; reads session state (consent = `null`)
3. Hook compresses P → P' (761 tok)
4. Hook writes pending entry to `pending.json` (no explain artifact, since explain is off by default)
5. Hook returns `decision: block` with full consent banner
6. User reads banner, types `/sq y session`
7. `/sq y session` slash command:
   - Reads pending entry → emits `squeezed_text` as next user message
   - Marks pending entry consumed
   - Sets session consent to `"yes-session"`
8. Claude responds to P' (the squeezed version, 761 input tokens)
9. Status-line counter increments; `log.jsonl` row written

**Subsequent long prompt of the same session:**

1. User types prompt Q (940 tok), hits enter
2. Hook reads session state (consent = `"yes-session"`)
3. Hook compresses Q → Q'
4. Hook writes pending + explain artifact
5. Hook returns `decision: block` with terse banner: `auto: 940 → 612 tok (-35%) • /sq y to send squeezed, /sq n to send original`
6. User types `/sq y` (4 keystrokes)
7. Squeezed Q' goes through; counter increments

**User changes their mind mid-session (`/sq off`):**

1. User runs `/sq off`
2. Slash command writes session consent = `"no"`
3. Subsequent long prompts pass through unchanged; hook only writes a measurement row to `log.jsonl`. No block, no compression.

**User regrets a squeeze (`/sq undo`):**

1. After Claude responds to P', user judges the response degraded
2. User runs `/sq undo`
3. Slash command reads the most recent consumed pending entry, emits its `original_text` as the next user message (requires explain enabled — otherwise `original_text` was never stored)
4. Claude re-responds based on the original prompt; user can compare

## Failure modes

- **Hook timeout (> 2,500ms):** Falls back to no-op behavior identical to v0.3's `hook_timeout` action — log a row with `action: "hook_timeout"`, return empty, allow original prompt to pass. No partial blocks.
- **Compression script raises:** Same fallback — log `hook_error`, allow original prompt through. We never block a user's prompt because the compressor crashed.
- **Pending cache corrupt or missing:** `/sq y` reports `no pending squeeze found — your last prompt may already have been sent or the cache was cleared. Type your prompt again.` and exits cleanly.
- **Session state corrupt:** Hook ignores corrupt state, treats session as having no consent (safe default — full banner shown again).
- **Eval CI red on a PR:** PR cannot merge. Contributor must either remove the offending rule or expand the context-gate to fix the regression.
- **Pricing data missing:** Falls back to default Sonnet pricing (existing v0.3 behavior).
- **Explain artifact write fails (permission, disk full):** Hook proceeds without writing the artifact, logs an `explain_write_failed` flag in the per-prompt log row, and the block message gracefully degrades to omit `/sq explain`-related instructions.

## Testing

**Unit tests** (`tests/skill/`, `tests/plugin/`):
- Compression rules: each new rule has positive cases, context-gate cases, and a regression case from a prior eval failure (where applicable)
- Capitalization post-pass: 10+ cases including multi-sentence prompts, contractions, proper nouns
- Hook block flow: payload → expected `decision: block` JSON for each consent state
- Recovery commands: pending cache parsing, consume-and-mark, missing-cache fallback
- Privacy: redaction regex hits all secret-shaped strings in test fixtures; opt-in default verified; off-state writes nothing
- Rollup: log.jsonl → totals.json computation with multi-day mixed entries

**Integration tests** (`tests/integration/`):
- Full hook run with stub compressor on long prompt, verify pending + explain artifacts written
- Slash command (`/sq y`) end-to-end: hook block → cache write → command read → emitted text matches squeezed

**Eval CI:**
- Run on every PR via existing `.github/workflows/ci.yml`
- Fails build if median < 0.95, p5 < 0.85, or any ≥0.95 prompt regresses

**Test count target:** v0.3 has 83 tests. v0.4 should add ~40 (rule unit tests, hook flow per consent state, recovery commands, privacy redaction, rollup). Net target: ~120 tests passing.

## Out of scope (deferred to v0.5+)

- Stage 2 LLM-rewrite as an actual Python script (currently lives in SKILL.md instructions only)
- Team-telemetry endpoint
- Native prompt rewrite when Anthropic ships #27365 — will simplify consent flow (auto-submit possible)
- Visual GUI for `/sq explain` (terminal-only for v0.4)
- Per-project compression rules (`prompt-squeeze.rules` setting)
- Streaks ("you've used squeeze 7 days in a row")

## Open questions

None block the design. Tactical decisions and one mechanism uncertainty are deferred to writing-plans:

- Single `commands/sq.md` with subcommand parsing vs. multiple slash files
- Whether the rollup script lives under `mcp/` or `skills/prompt-squeeze/scripts/`
- Exact eval-set additions needed to exercise new rule categories (will surface during rule-by-rule eval iteration)
- **User-visible transcript line mechanism:** Claude Code's `UserPromptSubmit` hook supports `additionalContext` (Claude-only) and `decision: block` (user-visible reason). Whether there is a third user-visible-but-non-blocking surface (e.g., `hookSpecificOutput.systemMessage`) needs verification before writing-plans finalizes the visibility implementation. Fallback: the one-line summary rides inside the `block` reason header, which is user-visible by definition.

## Migration / rollout

- Branch `v0.4-aggressive` off `main` (done)
- Implementation lands as one or more PRs back to `main`
- v0.4.0 tagged on GitHub when eval contract holds
- Marketplace tag-and-release **held** until anthropics/claude-plugins-official review of v0.3.2 lands — avoids muddying the in-flight review
- v0.3 users upgrading: settings file may need `mode` field updated; CHANGELOG and README will document the default flip from advise to interactive
