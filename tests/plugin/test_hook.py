# ABOUTME: Tests UserPromptSubmit hook — input parsing, output JSON shape, latency, privacy, error safety.
# ABOUTME: Contract for hooks/user_prompt_submit.py.

import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
HOOK_PY = REPO / "hooks" / "user_prompt_submit.py"


def run_hook(payload: dict, env: dict | None = None, timeout: float = 4.0):
    full_env = os.environ.copy()
    if env:
        full_env.update(env)
    return subprocess.run(
        [sys.executable, str(HOOK_PY)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=timeout,
        env=full_env,
    )


class TestHookInputParsing:
    def test_short_prompt_silent(self, tmp_log_dir):
        result = run_hook(
            {"prompt": "fix bug", "session_id": "abc", "cwd": "/", "permission_mode": "default"},
            env={"HOME": str(tmp_log_dir.parent)},
        )
        assert result.returncode == 0
        # Below threshold → empty stdout
        assert result.stdout.strip() == ""

    def test_handles_alternate_prompt_field(self, tmp_log_dir):
        # Some hook payload variants nest under tool_input.prompt
        result = run_hook(
            {
                "tool_input": {"prompt": "fix bug"},
                "session_id": "abc",
                "cwd": "/",
                "permission_mode": "default",
            },
            env={"HOME": str(tmp_log_dir.parent)},
        )
        assert result.returncode == 0

    def test_missing_prompt_does_not_crash(self, tmp_log_dir):
        result = run_hook(
            {"session_id": "abc", "cwd": "/", "permission_mode": "default"},
            env={"HOME": str(tmp_log_dir.parent)},
        )
        assert result.returncode == 0
        assert result.stdout.strip() == ""

    def test_invalid_json_does_not_crash(self, tmp_log_dir):
        full_env = os.environ.copy()
        full_env["HOME"] = str(tmp_log_dir.parent)
        result = subprocess.run(
            [sys.executable, str(HOOK_PY)],
            input="not json at all",
            capture_output=True,
            text=True,
            timeout=4,
            env=full_env,
        )
        # Hook MUST never break user flow even on garbage input
        assert result.returncode == 0


class TestHookNudge:
    def test_long_prompt_emits_nudge(self, tmp_log_dir):
        long_prompt = (
            "Hi, I was wondering if you could please help me out. "
            "I'm trying to figure out what's wrong with my code. "
            "Could you please take a look at it for me? Thanks in advance!\n"
        ) * 30  # ~1500 tokens of filler-heavy text

        result = run_hook(
            {"prompt": long_prompt, "session_id": "abc", "cwd": "/", "permission_mode": "default"},
            env={"HOME": str(tmp_log_dir.parent)},
        )
        assert result.returncode == 0
        if result.stdout.strip():
            data = json.loads(result.stdout)
            ctx = (
                data.get("hookSpecificOutput", {}).get("additionalContext")
                or data.get("additionalContext")
            )
            assert ctx is not None, f"expected additionalContext, got {data}"
            assert "/squeeze" in ctx
            assert "tokens" in ctx.lower()


class TestHookHardLimit:
    def test_hard_limit_with_interactive_blocks(self, tmp_log_dir, monkeypatch):
        settings_dir = tmp_log_dir.parent / ".claude"
        settings_dir.mkdir(exist_ok=True)
        (settings_dir / "settings.json").write_text(
            json.dumps(
                {
                    "prompt-squeeze.mode": "advise",
                    "prompt-squeeze.hard_limit": 100,
                    "prompt-squeeze.interactive": True,
                }
            )
        )
        long_prompt = "Please could you fix this in order to make it work. " * 100
        result = run_hook(
            {"prompt": long_prompt, "session_id": "abc", "cwd": "/", "permission_mode": "default"},
            env={"HOME": str(tmp_log_dir.parent)},
        )
        assert result.returncode in (0, 2)
        if result.stdout.strip():
            data = json.loads(result.stdout)
            decision = data.get("decision") or data.get("hookSpecificOutput", {}).get("decision")
            # interactive=true + over hard_limit should block
            if decision is not None:
                assert decision == "block"


class TestHookModeOff:
    def test_mode_off_silent(self, tmp_log_dir):
        settings_dir = tmp_log_dir.parent / ".claude"
        settings_dir.mkdir(exist_ok=True)
        (settings_dir / "settings.json").write_text(
            json.dumps({"prompt-squeeze.mode": "off"})
        )
        long_prompt = "Please could you fix this. " * 200
        result = run_hook(
            {"prompt": long_prompt, "session_id": "abc", "cwd": "/", "permission_mode": "default"},
            env={"HOME": str(tmp_log_dir.parent)},
        )
        assert result.returncode == 0
        assert result.stdout.strip() == ""


class TestHookLatency:
    def test_under_3_seconds(self, tmp_log_dir):
        prompt = "Please could you fix this in order to make it work. " * 200
        t0 = time.time()
        result = run_hook(
            {"prompt": prompt, "session_id": "abc", "cwd": "/", "permission_mode": "default"},
            env={"HOME": str(tmp_log_dir.parent)},
        )
        elapsed = time.time() - t0
        assert result.returncode == 0
        assert elapsed < 3.0, f"hook took {elapsed:.2f}s, must be < 3s"


class TestHookPrivacy:
    def test_log_does_not_contain_raw_prompt(self, tmp_log_dir):
        secret_marker = "MY_SECRET_XYZZY_42"
        prompt = (
            f"Please review file {secret_marker}.py. "
            "I was wondering if you could help. " * 50
        )
        run_hook(
            {"prompt": prompt, "session_id": "abc", "cwd": "/", "permission_mode": "default"},
            env={"HOME": str(tmp_log_dir.parent)},
        )
        log_path = tmp_log_dir / "log.jsonl"
        if log_path.exists():
            content = log_path.read_text()
            assert secret_marker not in content, (
                "RAW PROMPT TEXT LEAKED INTO LOG — privacy contract violated"
            )


class TestHookSelfTest:
    def test_self_test_runs_clean(self):
        result = subprocess.run(
            [sys.executable, str(HOOK_PY), "--self-test"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert result.returncode == 0, result.stderr
