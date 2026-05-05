# ABOUTME: Tests Stage 1 deterministic compressor — filler stripping, phrase replacement, code-fence safety.
# ABOUTME: These are the contract for skills/prompt-squeeze/scripts/compress.py.



import compress  # noqa: E402  (added to sys.path by conftest)


class TestCompressBasics:
    def test_strips_leading_filler(self):
        out = compress.compress("Hi, I was wondering if you could fix this bug")
        assert "I was wondering if" not in out
        # v0.4 capitalization post-pass may capitalize the new sentence head; accept either.
        assert "fix this bug" in out.lower()

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


class TestCapitalizationPostPass:
    """v0.4 fix: after filler stripping, sentence heads can become lowercase.
    This pass re-capitalizes the first letter of each sentence."""

    def test_capitalizes_first_letter_after_filler_strip(self):
        out = compress.compress("please update foo.py.")
        assert out[:1].isupper(), f"expected leading capital, got {out!r}"

    def test_capitalizes_second_sentence_after_filler(self):
        # After "Fix this." the next sentence starts lowercase due to filler strip.
        out = compress.compress("Fix this. please update foo.py with the new API.")
        # No lowercase word should immediately follow ". " or "? " or "! ".
        import re
        bad = re.findall(r"[.!?]\s+([a-z]\w+)", out)
        assert not bad, f"found lowercase sentence starts: {bad!r}"

    def test_does_not_touch_proper_nouns(self):
        out = compress.compress("Use Python and JavaScript.")
        assert "Python" in out
        assert "JavaScript" in out

    def test_handles_question_and_exclamation(self):
        out = compress.compress("Why? please explain. Also! please clarify.")
        import re
        bad = re.findall(r"[.!?]\s+([a-z]\w+)", out)
        assert not bad, f"found lowercase sentence starts: {bad!r}"

    def test_preserves_camelcase_like_ios(self):
        # 'iOS' at sentence start must NOT become 'IOS'.
        out = compress.compress("Fix the bug. iOS users are affected.")
        assert "iOS" in out, f"camelCase identifier broken: {out!r}"

    def test_idempotent(self):
        first = compress.compress("Please fix foo.py. please also lint it.")
        second = compress.compress(first)
        assert first == second


class TestForThePurposeOfFix:
    """Regression tests for v0.3 fidelity bug #1 — 'for the purpose of' -> 'to' lost causal meaning.
    See spec section 1, Bug fix #1."""

    def test_swaps_when_followed_by_verb_ing(self):
        out = compress.compress("Wrote a script for the purpose of testing the API.")
        assert "for the purpose of" not in out
        assert "to test" in out
        assert "API" in out

    def test_swaps_when_followed_by_verb_ing_complex(self):
        out = compress.compress("Built it for the purpose of validating user input.")
        assert "for the purpose of" not in out
        assert "to validate" in out
        assert "user input" in out

    def test_does_not_swap_when_followed_by_noun(self):
        out = compress.compress("This code exists for the purpose of compatibility.")
        assert "for the purpose of compatibility" in out

    def test_does_not_swap_when_dangling(self):
        out = compress.compress("It's there for the purpose of, you know, that thing.")
        # Either it leaves the phrase OR it transforms safely. Just don't strip the meaning.
        assert "purpose" in out or "for that" in out.lower()


class TestAggressivePoliteness:
    def test_drops_if_not_too_much_trouble(self):
        out = compress.compress("If it's not too much trouble, please review foo.py.")
        assert "if it's not too much trouble" not in out.lower()
        assert "foo.py" in out

    def test_drops_if_you_have_a_moment(self):
        out = compress.compress("If you have a moment, can you check bar.py?")
        assert "if you have a moment" not in out.lower()
        assert "bar.py" in out

    def test_drops_when_you_get_a_chance(self):
        out = compress.compress("When you get a chance, please update README.md.")
        assert "when you get a chance" not in out.lower()
        assert "README.md" in out

    def test_drops_sorry_to_bother(self):
        out = compress.compress("Sorry to bother you, but the test in test_x.py is flaky.")
        assert "sorry to bother" not in out.lower()
        assert "test_x.py" in out

    def test_preserves_protected_content(self):
        out = compress.compress("```\n# If you have a moment, fix this\n```\nhelp")
        assert "If you have a moment" in out


class TestAggressiveConnectors:
    def test_with_respect_to_to_about(self):
        out = compress.compress("Tell me about the trade-offs with respect to latency.")
        assert "with respect to" not in out.lower()
        assert "about latency" in out

    def test_in_terms_of_drops(self):
        out = compress.compress("Optimize in terms of memory usage.")
        assert "in terms of" not in out.lower()
        assert "memory usage" in out

    def test_with_reference_to_to_about(self):
        out = compress.compress("Update the doc with reference to the new schema.")
        assert "with reference to" not in out.lower()
        assert "schema" in out

    def test_in_relation_to_to_about(self):
        out = compress.compress("How does this work in relation to caching?")
        assert "in relation to" not in out.lower()
        assert "caching" in out

    def test_as_a_matter_of_fact_drops(self):
        out = compress.compress("As a matter of fact, the bug is in line 42.")
        assert "as a matter of fact" not in out.lower()
        assert "line 42" in out

    def test_at_the_end_of_the_day_drops(self):
        out = compress.compress("At the end of the day, performance matters most.")
        assert "at the end of the day" not in out.lower()
        assert "performance matters most" in out.lower()


class TestAggressiveQualifiers:
    def test_drops_very_before_adjective(self):
        out = compress.compress("This is a very important fix for foo.py.")
        assert " very important" not in out
        assert "important fix for foo.py" in out

    def test_drops_really_before_verb(self):
        out = compress.compress("I really need this to work.")
        assert " really need" not in out
        assert "need this to work" in out.lower()

    def test_drops_actually(self):
        out = compress.compress("This actually causes a memory leak.")
        assert " actually " not in out
        assert "causes a memory leak" in out.lower()

    def test_drops_basically(self):
        out = compress.compress("It basically does the same thing.")
        assert " basically " not in out
        assert "does the same thing" in out.lower()

    def test_drops_essentially(self):
        out = compress.compress("They essentially work the same way.")
        assert " essentially " not in out

    def test_does_not_drop_inside_quoted_string(self):
        out = compress.compress('The error says "this is very bad"')
        assert "very bad" in out


class TestAggressiveImperativeCollapse:
    def test_i_would_like_you_to_drops(self):
        out = compress.compress("I would like you to refactor foo.py:42.")
        assert "I would like you to" not in out
        assert "refactor foo.py:42" in out.lower()

    def test_i_want_you_to_drops(self):
        out = compress.compress("I want you to write a test for the parser.")
        assert "I want you to" not in out
        assert "write a test for the parser" in out.lower()

    def test_i_need_you_to_drops(self):
        out = compress.compress("I need you to fix the bug in handler.go.")
        assert "I need you to" not in out
        assert "handler.go" in out

    def test_id_appreciate_it_if_drops(self):
        out = compress.compress("I'd appreciate it if you could update the README.")
        assert "appreciate it if" not in out.lower()
        assert "README" in out

    def test_what_id_like_drops(self):
        out = compress.compress("What I'd like is for you to add a unit test.")
        assert "what i'd like is for you to" not in out.lower()
        assert "add a unit test" in out.lower()


class TestAggressiveArticleDropping:
    def test_drops_the_at_sentence_start_before_lowercase_noun(self):
        # 'The function is broken' — 'The' is droppable when followed by a common noun.
        out = compress.compress("The function in foo.py is broken.")
        # Capitalization post-pass may capitalize 'function' once 'The' is dropped — accept either.
        assert "function in foo.py" in out.lower()
        assert "is broken" in out

    def test_keeps_the_inside_noun_phrase(self):
        # Inside a noun phrase article is not at sentence start, so rule won't touch it.
        out = compress.compress("Update the API contract with a new field.")
        assert "the API" in out or "API contract" in out

    def test_does_not_break_camelcase_identifier(self):
        # 'The iOS bug...' — 'iOS' must stay 'iOS' even if 'The' drops.
        out = compress.compress("The iOS bug is in src/main.swift.")
        assert "iOS" in out

    def test_preserves_articles_in_quoted_speech(self):
        # Quoted content is protected upstream.
        out = compress.compress('The error message says "the connection was reset".')
        assert "the connection was reset" in out

    def test_does_not_drop_before_snake_case(self):
        # 'The user_id field...' — 'user_id' is an identifier; rule should skip.
        out = compress.compress("The user_id field is null.")
        assert "user_id" in out
