---
name: squeeze
description: Compress a prompt and show savings
argument-hint: "[prompt-text-or-file]"
---

<!-- ABOUTME: Slash command that compresses a user-supplied prompt and shows a savings receipt. -->
<!-- ABOUTME: Delegates the work to the bundled prompt-squeeze skill in skills/prompt-squeeze. -->

Invoke the bundled `prompt-squeeze` skill on the argument the user provided.

1. If the argument looks like a path that exists on disk, read the file with `Read` and treat its contents as the prompt to compress. Otherwise treat the argument verbatim as the prompt.
2. If no argument was provided, ask the user to either paste a prompt or supply a path.
3. Run the skill's compression flow (Stage 1 deterministic; offer Stage 2 if the user asks). Use `skills/prompt-squeeze/scripts/compress.py` and `skills/prompt-squeeze/scripts/estimate.py` per the skill's `SKILL.md`.
4. Render the receipt produced by the skill (template at `skills/prompt-squeeze/templates/receipt.md`). Show original tokens, compressed tokens, percent reduction, dollars saved, Wh saved, and the cited methodology lines.
5. Do not log or echo the raw prompt back to the user beyond what the receipt requires. Never write the raw prompt to disk outside the user's working directory unless they ask.
