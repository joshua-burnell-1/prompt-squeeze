---
name: prompt-squeeze
description: Rewrite the user's draft prompt into a token-efficient equivalent and report dollar + electricity savings. Use when the user runs /squeeze, mentions "shorten this prompt", "compress prompt", "optimize for token cost", or asks to make their prompt more efficient.
allowed-tools: Read, Bash
disable-model-invocation: false
---

<!-- ABOUTME: Skill instructions Claude follows to compress a user prompt and emit a savings receipt. -->
<!-- ABOUTME: Two-stage pipeline - deterministic Stage 1 via compress.py, then Claude in-context Stage 2. -->

# Prompt squeeze

You are squeezing a verbose user-supplied prompt into a token-efficient equivalent, then reporting the savings. Do not execute the user's compressed request - only return the rewrite and the receipt.

## Inputs you will receive
- The original prompt text (call it `ORIGINAL`).
- Optionally, a target model (default: `claude-sonnet-4-6`).

## Stage 1 - deterministic heuristic compression

Pipe the original prompt through the deterministic compressor. Use Bash:

```
echo "$ORIGINAL" | python "$SKILL_DIR/scripts/compress.py" --stdin
```

Capture stdout as `STAGE1`. This strips filler ("please", "I was wondering"), swaps verbose phrases ("in order to" -> "to"), and normalizes whitespace without touching code blocks, URLs, or file paths.

## Stage 2 - in-context rewrite

Apply these rules to `STAGE1` and produce `STAGE2`:

1. Identify the **task verb** (fix, refactor, explain, write) and **mandatory constraints**:
   - File paths and line numbers (e.g. `src/foo.py:42`)
   - Error strings (`TypeError`, stack frames, exit codes)
   - Version numbers (`v3.4.1`, `Django 4.2`)
   - Code snippets, URLs, identifiers, environment names
   These NEVER drop.
2. Identify **explanatory padding** - background that does not change the answer. Drop or compress.
3. Collapse polite scaffolding and second-person framing into imperative voice.
4. Output the rewrite inside a fenced block tagged `rewritten`:

   ```rewritten
   <your rewrite>
   ```
5. After the block, list any constraint you were unsure whether to drop, each on its own line prefixed with `?` (e.g. `? "uses Bolt framework" - kept; might be optional context`).

## Stage 3 - estimate savings

Count tokens for `ORIGINAL` and the Stage 2 rewrite. Use the same encoding the compressor uses (`tiktoken` cl100k_base) for consistency.

Run:

```
python "$SKILL_DIR/scripts/estimate.py" \
  --original-tokens N \
  --compressed-tokens M \
  --model claude-sonnet-4-6
```

This emits a JSON receipt with `saved_dollars`, `saved_wh`, `saved_g_co2e`, and source URLs.

## Stage 4 - render the receipt

Read `templates/receipt.md` and substitute the placeholders from the JSON receipt. Or call `estimate.py` with `--format markdown` to do the substitution for you. Print the rendered receipt below the `rewritten` block.

## Output format

Always emit, in order:

1. **A side-by-side comparison** as a markdown table. Two columns: `Original` and `Compressed`. Split each prompt into 1-3 sentence chunks so the table is scannable. If the prompts are too long for a clean table (more than ~10 rows), fall back to two consecutive blockquotes labeled `**Original**` and `**Compressed**` so the user can still see both.

   Example table format:

   ```
   | Original | Compressed |
   | --- | --- |
   | Hi, I was wondering if you could please look at foo.py:42 | Look at foo.py:42 |
   | because I'm getting a TypeError that I can't figure out | TypeError - help debug |
   ```

2. The fenced `rewritten` block (Claude Code can copy-paste it).
3. Any `?` uncertainty lines.
4. The rendered receipt (markdown).

The side-by-side is the headline output; the receipt is the proof. Show both. The user explicitly asked for visibility into what changed - never skip the comparison even when the compression is small.

Do not log or echo the raw original prompt back to the user beyond the comparison and the fenced block.
