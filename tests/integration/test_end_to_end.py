# ABOUTME: End-to-end smoke test — real prompt → compress → estimate → receipt.
# ABOUTME: Catches integration breaks between skill scripts and the plugin's hook.

import subprocess
import sys
from pathlib import Path

import compress  # noqa: E402
import estimate  # noqa: E402

REPO = Path(__file__).resolve().parents[2]


def test_full_pipeline_verbose_prompt():
    original = (
        "Hi! I was wondering if you could please help me out. "
        "I'm trying to figure out what's going wrong with my Python code. "
        "In foo.py at line 42, I'm getting a TypeError because the variable is None. "
        "Could you please look at it and tell me how to fix it? Thanks in advance!"
    ) * 4

    compressed = compress.compress(original)

    # Critical preservation: every literal that matters
    for must in ("foo.py", "TypeError", "42"):
        assert must in compressed

    # Approx token count via word count for the integration test
    orig_tok = len(original.split())
    comp_tok = len(compressed.split())
    assert comp_tok < orig_tok, "compression should reduce length"

    # Plug counts into estimator
    receipt = estimate.estimate(orig_tok, comp_tok, "claude-sonnet-4-6")
    assert receipt["saved_input_tokens"] > 0
    assert receipt["saved_dollars"] > 0
    assert receipt["saved_wh"] > 0
    assert "sources" in receipt


def test_pipeline_short_prompt_no_savings():
    original = "fix foo.py:42"
    compressed = compress.compress(original)

    orig_tok = max(1, len(original.split()))
    comp_tok = max(1, len(compressed.split()))
    receipt = estimate.estimate(orig_tok, comp_tok, "claude-sonnet-4-6")
    # Tight prompt: ratio should be ≤ 0.3 (mostly nothing to compress)
    assert receipt["compression_ratio"] <= 0.3


def test_eval_harness_runs_without_judge():
    eval_path = REPO / "skills" / "prompt-squeeze" / "scripts" / "eval" / "run_eval.py"
    result = subprocess.run(
        [sys.executable, str(eval_path)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    # Should print something resembling a summary
    assert "compression" in result.stdout.lower() or "ratio" in result.stdout.lower()
