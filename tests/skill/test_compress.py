# ABOUTME: Tests Stage 1 deterministic compressor — filler stripping, phrase replacement, code-fence safety.
# ABOUTME: These are the contract for skills/prompt-squeeze/scripts/compress.py.



import compress  # noqa: E402  (added to sys.path by conftest)


class TestCompressBasics:
    def test_strips_leading_filler(self):
        out = compress.compress("Hi, I was wondering if you could fix this bug")
        assert "I was wondering if" not in out
        assert "fix this bug" in out

    def test_strips_thanks(self):
        out = compress.compress("Fix the bug. Thanks in advance!")
        assert "Thanks in advance" not in out
        assert "Fix the bug" in out

    def test_replaces_in_order_to(self):
        out = compress.compress("I need to refactor in order to improve perf")
        assert "in order to" not in out
        assert "to improve perf" in out

    def test_replaces_due_to_the_fact_that(self):
        out = compress.compress("Failing due to the fact that the input is null")
        assert "due to the fact that" not in out
        assert "because" in out

    def test_normalizes_whitespace(self):
        out = compress.compress("a    b\n\n\n\nc")
        assert "    " not in out
        assert "\n\n\n" not in out


class TestCompressPreservation:
    def test_preserves_file_paths(self, verbose_prompt):
        out = compress.compress(verbose_prompt)
        assert "foo.py" in out

    def test_preserves_error_strings(self, verbose_prompt):
        out = compress.compress(verbose_prompt)
        assert "TypeError" in out

    def test_preserves_line_numbers(self, verbose_prompt):
        out = compress.compress(verbose_prompt)
        assert "42" in out

    def test_preserves_code_fence_contents(self, code_fenced_prompt):
        out = compress.compress(code_fenced_prompt)
        # Filler INSIDE the fence must NOT be rewritten
        assert "please_compute_in_order_to_succeed" in out
        assert "'in order to'" in out

    def test_preserves_inline_code(self):
        out = compress.compress("Please update `in order to` in the docs")
        assert "`in order to`" in out

    def test_preserves_urls(self):
        out = compress.compress(
            "Please check https://example.com/in-order-to-thing/ thanks"
        )
        assert "https://example.com/in-order-to-thing/" in out


class TestCompressionRatio:
    def test_ratio_positive_on_verbose(self, verbose_prompt):
        compressed = compress.compress(verbose_prompt)
        ratio = compress.compression_ratio(verbose_prompt, compressed)
        assert 0.05 < ratio < 1.0

    def test_ratio_zero_or_low_on_already_tight(self):
        tight = "fix foo.py:42 TypeError"
        compressed = compress.compress(tight)
        ratio = compress.compression_ratio(tight, compressed)
        assert ratio < 0.30

    def test_ratio_uses_token_counter_when_provided(self, verbose_prompt):
        compressed = compress.compress(verbose_prompt)

        # Word-count proxy
        def word_count(s: str) -> int:
            return len(s.split())

        ratio = compress.compression_ratio(
            verbose_prompt, compressed, count_tokens=word_count
        )
        assert 0.0 <= ratio <= 1.0


class TestCompressEdgeCases:
    def test_empty_string(self):
        assert compress.compress("") == ""

    def test_whitespace_only(self):
        out = compress.compress("   \n\n  ")
        assert out.strip() == ""

    def test_idempotent_on_already_compressed(self):
        first = compress.compress(
            "Please could you in order to fix this thanks in advance"
        )
        second = compress.compress(first)
        assert first == second

    def test_unicode_safe(self):
        text = "Please fix the café emoji bug — thanks 🎉"
        out = compress.compress(text)
        # café should still be there even though we strip filler
        assert "café" in out


class TestSelfTest:
    def test_self_test_mode_runs_clean(self, capsys):
        import subprocess
        import sys
        from pathlib import Path

        compress_path = (
            Path(__file__).resolve().parents[2]
            / "skills"
            / "prompt-squeeze"
            / "scripts"
            / "compress.py"
        )
        result = subprocess.run(
            [sys.executable, str(compress_path), "--self-test"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0, f"self-test failed: {result.stderr}"

    def test_stdin_mode(self):
        import subprocess
        import sys
        from pathlib import Path

        compress_path = (
            Path(__file__).resolve().parents[2]
            / "skills"
            / "prompt-squeeze"
            / "scripts"
            / "compress.py"
        )
        result = subprocess.run(
            [sys.executable, str(compress_path), "--stdin"],
            input="Please could you in order to fix this. Thanks in advance!",
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0
        assert "in order to" not in result.stdout
        assert "Thanks in advance" not in result.stdout


def test_compression_does_not_invent_content():
    """Compression must not introduce text that wasn't in the original (besides
    canonical replacements like 'to' for 'in order to'). Catches hallucination regressions."""
    sample = "Please could you fix foo.py thanks"
    out = compress.compress(sample)
    forbidden = ["TODO", "NOTE:", "HACK", "FIXME"]
    for f in forbidden:
        assert f not in out
