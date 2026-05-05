# ABOUTME: Tests the hook's side-by-side renderer and the interactive-block path that uses it.
# ABOUTME: Contract: when interactive=true and prompt > hard_limit, reason includes a 2-column diff.

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
HOOK_PY = REPO / "hooks" / "user_prompt_submit.py"


def _load_hook_module():
    spec = importlib.util.spec_from_file_location("hook_mod", HOOK_PY)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@pytest.fixture()
def hook():
    return _load_hook_module()


class TestWrap:
    def test_short_text_single_line(self, hook):
        assert hook._wrap("hello", 40) == ["hello"]

    def test_wraps_to_width(self, hook):
        out = hook._wrap("one two three four five six seven eight nine ten", 20)
        for line in out:
            assert len(line) <= 20

    def test_preserves_explicit_newlines(self, hook):
        out = hook._wrap("first\n\nsecond", 40)
        assert "" in out  # blank line preserved
        assert "first" in out
        assert "second" in out

    def test_hard_break_long_word(self, hook):
        long_word = "x" * 100
        out = hook._wrap(long_word, 20)
        for line in out:
            assert len(line) <= 20

    def test_empty_returns_single_blank(self, hook):
        assert hook._wrap("", 40) == [""]


class TestSideBySide:
    def test_includes_both_labels(self, hook):
        out = hook._side_by_side("hello", "hi")
        assert "ORIGINAL" in out
        assert "COMPRESSED" in out

    def test_renders_separator(self, hook):
        out = hook._side_by_side("hello", "hi")
        # Has a column separator pipe
        assert " | " in out

    def test_custom_labels(self, hook):
        out = hook._side_by_side(
            "a", "b", original_label="BEFORE (10 tok)", compressed_label="AFTER (5 tok)"
        )
        assert "BEFORE (10 tok)" in out
        assert "AFTER (5 tok)" in out

    def test_truncates_long_input(self, hook):
        original = "\n".join(f"line {i}" for i in range(50))
        out = hook._side_by_side(original, "short", max_lines=10)
        assert "more lines" in out

    def test_includes_truncation_notice(self, hook):
        original = "\n".join(f"line {i}" for i in range(50))
        out = hook._side_by_side(original, "short", max_lines=10)
        assert "truncated for display" in out

    def test_short_input_no_truncation(self, hook):
        out = hook._side_by_side("hello", "hi")
        assert "truncated" not in out

    def test_handles_unicode(self, hook):
        out = hook._side_by_side("café résumé", "café")
        assert "café" in out

    def test_handles_empty_compressed(self, hook):
        out = hook._side_by_side("hello world", "")
        assert "ORIGINAL" in out
        # Must not crash; empty side renders as blank cells
        assert "hello" in out


class TestHookBlockOutputIncludesDiff:
    def test_block_reason_contains_side_by_side(self, tmp_path):
        settings_dir = tmp_path / ".claude"
        settings_dir.mkdir()
        (settings_dir / "settings.json").write_text(
            json.dumps(
                {
                    "prompt-squeeze.mode": "interactive",
                    "prompt-squeeze.block_threshold": 20,
                    "prompt-squeeze.notify_threshold": 0.05,
                }
            )
        )

        long_prompt = (
            "Hi, I was wondering if you could please fix this in order to make it work. "
            "Thanks in advance! "
        ) * 30

        env = os.environ.copy()
        env["HOME"] = str(tmp_path)

        result = subprocess.run(
            [sys.executable, str(HOOK_PY)],
            input=json.dumps(
                {
                    "prompt": long_prompt,
                    "session_id": "diff_test",
                    "cwd": str(tmp_path),
                    "permission_mode": "default",
                }
            ),
            capture_output=True,
            text=True,
            timeout=5,
            env=env,
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip(), "expected non-empty stdout from block path"

        data = json.loads(result.stdout)
        decision = data.get("decision") or data.get("hookSpecificOutput", {}).get(
            "decision"
        )
        reason = data.get("reason") or data.get("hookSpecificOutput", {}).get("reason")

        assert decision == "block", f"expected block decision, got {data}"
        assert reason is not None, "expected reason to be present"
        assert "ORIGINAL" in reason
        assert "COMPRESSED" in reason
        assert "|" in reason
        assert "/sq y" in reason


class TestHookSelfTestStillPasses:
    def test_self_test_runs_clean(self):
        result = subprocess.run(
            [sys.executable, str(HOOK_PY), "--self-test"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert result.returncode == 0, result.stderr
