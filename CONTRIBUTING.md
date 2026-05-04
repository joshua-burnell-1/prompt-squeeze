<!-- ABOUTME: How to contribute to prompt-squeeze: dev setup, run tests, propose changes. -->
<!-- ABOUTME: Issue/PR conventions are minimal - aim for short, traceable changes. -->

# Contributing to prompt-squeeze

Issues, PRs, and constructive critiques are all welcome.

## Development setup

```bash
git clone https://github.com/joshua-burnell-1/prompt-squeeze
cd prompt-squeeze
uv sync --extra dev
```

This pulls Python 3.12, the runtime deps (`anthropic`, `mcp`, `tiktoken`, `jsonschema`), and the dev deps (`pytest`, `ruff`).

## Run the test suite

```bash
.venv/bin/pytest               # full suite (~1.5s)
.venv/bin/ruff check .         # lint
.venv/bin/python skills/prompt-squeeze/scripts/eval/run_eval.py  # 100-prompt eval
```

The Claude-as-judge eval is gated behind `--judge` because it makes paid API calls:

```bash
# With ANTHROPIC_API_KEY in env (faster, ~$0.05 per row at Sonnet rates)
uv run python skills/prompt-squeeze/scripts/eval/run_eval.py --judge --judge-sample 20

# Without API key (uses your Claude Code subscription via `claude -p`, ~$0.10 per row)
uv run python skills/prompt-squeeze/scripts/eval/run_eval.py --judge --judge-backend cli --judge-sample 20
```

## Code conventions

- New files start with a 2-line `ABOUTME:` comment block describing what the file does.
- Comments explain WHY when non-obvious — never WHAT (good identifiers do that already).
- Tests live under `tests/skill/`, `tests/plugin/`, or `tests/integration/`. Each test class describes one behavior; one assertion per concept.
- The `UserPromptSubmit` hook **must remain stdlib-only and Python 3.9 compatible** because it runs against `python3` on the user's PATH (macOS ships with 3.9). The CI workflow verifies this on every commit.
- Logs **must never contain raw prompt text** — only sha256 hash prefixes. The privacy contract is verified by `tests/plugin/test_hook.py::TestHookPrivacy`.

## Proposing a change

1. Open an issue describing the behavior you want changed and why.
2. For non-trivial changes, sketch the approach in the issue before writing code.
3. PRs should:
   - Include a test that fails on `main` and passes on your branch.
   - Update the eval set if the change affects compression behavior.
   - Run lint clean and pass the full pytest suite.
4. Keep diffs focused. Refactors and unrelated cleanup go in separate PRs.

## Releasing

Tag-based:

```bash
git tag -a vX.Y.Z -m "release notes"
git push origin vX.Y.Z
```

Then bump the `version` field in `joshua-burnell-1/claude-plugins/.claude-plugin/marketplace.json` and the plugin's own `.claude-plugin/plugin.json`.

## License

By contributing, you agree that your contributions are licensed under the [Apache License 2.0](./LICENSE).
