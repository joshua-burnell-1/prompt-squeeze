---
name: sq
description: Resume a pending squeeze (y/n) or manage session consent (undo/off)
argument-hint: "[y|y session|n|undo|off]"
---

<!-- ABOUTME: /sq dispatches the y/n/undo/off subcommands for the prompt-squeeze interactive flow. -->
<!-- ABOUTME: Reads ~/.claude/prompt-squeeze/pending.json + writes session_state to manage consent. -->

You are responding to the user's `/sq` command. Argument is `$1` (with optional `$2`).

The pending-squeeze cache is at `~/.claude/prompt-squeeze/pending.json`. The current session's hash is the SHA-256-prefix-16 of the session id you saw in the most recent UserPromptSubmit hook output (the `session` field of the log row, or — if you're unsure — read the cache and pick the most recently-timestamped entry).

Branch on `$1`:

**`y`** — Read the cache. Find the most recent unconsumed entry. Submit the entry's `squeezed_text` field as your next user-equivalent message, **verbatim**: no preamble, no quoting, no commentary, no markdown wrapping. Then run this Bash command to mark it consumed:

```bash
python3 -c "import json, os, tempfile; from pathlib import Path; p=Path.home()/'.claude'/'prompt-squeeze'/'pending.json'; d=json.loads(p.read_text()); k=max(d.keys(), key=lambda k: d[k].get('ts','')); d[k]['consumed']=True; td=tempfile.NamedTemporaryFile(mode='w', dir=str(p.parent), prefix='.pending-', suffix='.tmp', delete=False); json.dump(d, td); td.close(); os.replace(td.name, p)"
```

If `$2 == "session"`, ALSO write the session consent. Run this Bash command (substituting `<session_hash>` with the actual hash):

```bash
python3 -c "import json, os, sys, tempfile; from pathlib import Path; sd=Path.home()/'.claude'/'prompt-squeeze'/'sessions'; sd.mkdir(parents=True, exist_ok=True); h=sys.argv[1]; td=tempfile.NamedTemporaryFile(mode='w', dir=str(sd), prefix=f'.{h}-', suffix='.tmp', delete=False); json.dump({'consent':'yes-session'}, td); td.close(); os.replace(td.name, sd/f'{h}.json')" <session_hash>
```

**`n`** — Read the cache. If `original_text` is present, submit it as the next user message verbatim. If absent (explain feature is off), tell the user: "Original prompt was not stored (explain feature is off). Run `/sq explain on` first to enable `/sq n` and `/sq undo`. For now, please retype your prompt." Mark the entry consumed regardless.

**`undo`** — Read the cache. Find the most recent CONSUMED entry. If it has `original_text`, submit that as the next user message after a one-line prefix: "Resending original prompt (squeeze undo):". If `original_text` is absent, tell the user: "Cannot undo — original prompt was not stored (explain feature was off when this prompt was squeezed). Enable `/sq explain on` for future undos."

**`off`** — Write `{"consent": "no"}` to `~/.claude/prompt-squeeze/sessions/<session_hash>.json` (atomic via temp+rename, see the `y session` command above for the snippet). Tell the user: "prompt-squeeze disabled for the rest of this session. New long prompts will pass through unchanged. Restart your Claude Code session to re-enable."

**No arg or unknown arg** — Show the user:
```
Usage:
  /sq y          send the squeezed version of your last long prompt
  /sq y session  send squeezed AND auto-confirm for the rest of this session
  /sq n          send your original prompt unchanged
  /sq undo       resend the most recent prompt as its original (requires explain on)
  /sq off        disable prompt-squeeze for the rest of this session
```

**Critical:** when submitting the squeezed or original text, do NOT echo it back as commentary, do NOT wrap it in quotes or code fences, do NOT prepend "Here is the squeezed prompt:" or similar. The user expects their message-as-they-typed-it to be the next thing in the conversation. Just submit the text content.
