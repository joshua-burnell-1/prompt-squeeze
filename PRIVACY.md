<!-- ABOUTME: Privacy policy for prompt-squeeze - what data is collected, where it lives, and user rights. -->
<!-- ABOUTME: Plugin is local-only by default; nothing leaves the user's machine without explicit opt-in. -->

# Privacy policy

`prompt-squeeze` runs locally on your machine. **No data leaves your machine by default.** This document tells you exactly what gets stored, where, and what you can do about it.

## What gets stored

Every time the `UserPromptSubmit` hook fires (i.e., on every prompt you submit to Claude Code), the plugin appends one JSON row to a local log file. Each row contains:

| Field | Example | Purpose |
|---|---|---|
| `ts` | `2026-05-04T01:20:11Z` | Timestamp |
| `session` | `c0302da4e5163e96` | First 16 hex chars of SHA-256 of the session ID |
| `model` | `claude-sonnet-4-6` | Model the prompt was sent to |
| `prompt_hash` | `493c736cc7b922d1` | First 16 hex chars of SHA-256 of the prompt text |
| `original_tokens` | `1352` | Token count of the prompt |
| `achievable_tokens` | `832` | Tokens that could have been saved by compression |
| `achievable_pct` | `0.6154` | Compression headroom |
| `estimated_dollars_saved` | `0.0087` | Dollar estimate at the model's list rate |
| `estimated_wh_saved` | `0.1352` | Energy estimate using a peer-reviewed J/token figure |
| `action` | `nudge` | What the hook did: `silent`, `nudge`, `block`, `measure_only`, `hook_error` |
| `user_action` | `null` | Reserved for future user-response tracking |

## What does NOT get stored

- **Raw prompt text is never written to the log file.** Only a 16-character SHA-256 prefix.
- **Raw session IDs are not stored.** Only a hashed prefix.
- No PII, no email addresses, no file contents, no error messages, no environment variables.
- The hash prefixes cannot be reversed back to the original text.

This is verified by an automated test on every commit: `tests/plugin/test_hook.py::TestHookPrivacy::test_log_does_not_contain_raw_prompt`.

## Where the data lives

```
~/.claude/prompt-squeeze/log.jsonl
```

That's the only location. One file, one machine. No cloud, no analytics, no third-party services.

## Network calls

The plugin makes **zero network calls during normal operation.** The hook is purely local; the slash commands are purely local; the MCP server reads only the local log file.

The single exception is the optional eval harness (`scripts/eval/run_eval.py`), which is only invoked if you explicitly run it with the `--judge` flag. In that mode, original and compressed prompts are sent to either:

- The Anthropic API (if `ANTHROPIC_API_KEY` is set), governed by [Anthropic's Privacy Policy](https://www.anthropic.com/legal/privacy), **or**
- Your local Claude Code subscription via `claude -p` (uses your existing Claude Code auth).

The eval harness is for plugin developers, not end users. Don't run it on prompts containing sensitive data.

## Your rights

You can:

- **Delete all stored data at any time** by removing the log file: `rm ~/.claude/prompt-squeeze/log.jsonl`
- **Disable logging entirely** by setting `prompt-squeeze.telemetry: "off"` in `.claude/settings.json`
- **Disable the plugin without uninstalling** by setting `prompt-squeeze.mode: "off"`
- **Inspect every row that was ever written** — it's a plain-text JSONL file you can `cat`, `jq`, or grep at will

## Future telemetry options

The settings schema reserves a `prompt-squeeze.telemetry: "team"` mode that would send the same hashed rollup data (no raw prompts) to a self-hosted endpoint for team-level reporting. **This is not implemented as of v0.3.2** — the field is a stub. If/when it ships, opt-in will be explicit and the team-endpoint URL will be user-controlled.

## Changes to this policy

If the data the plugin collects ever changes, this file gets updated in the same commit. Check the [git history](https://github.com/joshua-burnell-1/prompt-squeeze/commits/main/PRIVACY.md) to see what changed and when.

## Verifying it yourself

Don't trust this document — verify it.

```bash
# Run the hook with a marked prompt and confirm the marker doesn't appear in the log
echo '{"prompt": "MY_SECRET_TOKEN_XYZ", "session_id": "test", "cwd": "/", "permission_mode": "default"}' \
  | python3 hooks/user_prompt_submit.py
grep MY_SECRET_TOKEN_XYZ ~/.claude/prompt-squeeze/log.jsonl
# (no output = the secret is not in the log)
```

## Questions

Open an issue at https://github.com/joshua-burnell-1/prompt-squeeze/issues with the label `privacy`.
