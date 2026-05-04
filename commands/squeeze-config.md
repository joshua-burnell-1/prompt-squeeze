---
name: squeeze-config
description: Walk through prompt-squeeze settings
---

<!-- ABOUTME: Slash command that walks the user through prompt-squeeze settings in .claude/settings.json. -->
<!-- ABOUTME: Validates against settings.schema.json and edits the file in place via the Edit tool. -->

Help the user inspect and update their prompt-squeeze configuration.

1. Read `.claude/settings.json` from the project root with `Read`. If it doesn't exist, tell the user and offer to create it.
2. Show the current values for any of these keys (and their defaults if absent):
   - `prompt-squeeze.mode` (default `advise`)
   - `prompt-squeeze.warn_threshold` (default `800`)
   - `prompt-squeeze.notify_threshold` (default `0.25`)
   - `prompt-squeeze.hard_limit` (default `4000`)
   - `prompt-squeeze.interactive` (default `false`)
   - `prompt-squeeze.model_override` (default `null`)
   - `prompt-squeeze.telemetry` (default `local`)
   - `prompt-squeeze.team_endpoint` (default `null`)
3. Validate any proposed change against `settings.schema.json` at the plugin root. Reject values outside the schema and explain why.
4. Apply changes by editing `.claude/settings.json` with `Edit`. Preserve all other keys exactly.
5. After saving, summarize the new values and remind the user that `mode=off` disables the hook entirely while `mode=measure` only logs without nudging.
