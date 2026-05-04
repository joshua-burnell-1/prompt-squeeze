<!-- ABOUTME: Vulnerability disclosure process and threat model summary for prompt-squeeze. -->
<!-- ABOUTME: This plugin runs as a UserPromptSubmit hook with file/log access on the user's machine. -->

# Security policy

## Reporting a vulnerability

If you find a vulnerability in prompt-squeeze, please report it privately rather than opening a public issue.

- Open a [draft security advisory](https://github.com/joshua-burnell-1/prompt-squeeze/security/advisories/new) on this repo, **or**
- Open a regular issue tagged `security` if no sensitive details are involved.

I'll acknowledge within 7 days and aim to ship a fix within 30 days for high-severity findings.

## Threat model

This plugin runs locally on the user's machine. It does **not** make network calls at runtime; the only network surface is the optional `--judge` mode of the eval harness, which calls the Anthropic API or shells out to `claude -p` and is opt-in.

### What the plugin can do

- Read every prompt the user submits (via `UserPromptSubmit` hook).
- Read `~/.claude/settings.json` and the project's `.claude/settings.json`.
- Append to `~/.claude/prompt-squeeze/log.jsonl`.
- Read pricing/energy reference data bundled in the skill.
- Spawn a Python subprocess for the deterministic compression script.

### What the plugin must not do

- **Never log raw prompt text.** Logs contain SHA-256 prefixes only. Verified by `tests/plugin/test_hook.py::TestHookPrivacy::test_log_does_not_contain_raw_prompt`.
- **Never make network calls in the hook path.** The hook is purely local. `--judge` is the only network code path and is gated behind an explicit flag.
- **Never break the user's prompt flow on error.** All hook logic is wrapped in a broad `try/except`; on any failure the hook exits 0 with empty output and logs an error row (without prompt text).

### Out of scope

- Threats from a compromised user account or a compromised settings file are out of scope; the plugin trusts whatever `.claude/settings.json` says.
- Telemetry to a `team_endpoint` is currently a stub (planned for v0.2 of the rollup). When implemented, raw prompts will still never be transmitted.
- The Claude-as-judge eval harness sends compressed and original prompts to a model. Don't run `--judge` on prompts containing secrets.

## Verifying privacy

To audit that no raw prompt text leaks into logs:

```bash
echo '{"prompt": "MY_SECRET_TOKEN_XYZ", "session_id": "audit", "cwd": "/", "permission_mode": "default"}' \
  | python3 hooks/user_prompt_submit.py
grep MY_SECRET_TOKEN_XYZ ~/.claude/prompt-squeeze/log.jsonl
# (should produce no output)
```
