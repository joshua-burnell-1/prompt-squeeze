# ABOUTME: Pins the stranded-punctuation and orphan-fragment failure modes the judge eval flagged.
# ABOUTME: When v0.2 ships, these tests fail; v0.3 cleanup pass should make them pass.

import compress  # noqa: E402  (sys.path injected by conftest)


class TestNoStrandedPunctuation:
    def test_no_solo_exclamation_after_stripped_thanks(self):
        # "Thanks in advance!" stripping currently leaves a stranded "!"
        out = compress.compress("Fix the bug. Thanks in advance!")
        # The original sentence-ending period should remain; no orphan "!" should follow.
        assert "!" not in out or out.endswith("!"), (
            f"stranded ! found: {out!r}"
        )
        # Stronger: no ".!" or "!.!" runs
        assert ".!" not in out
        assert "!." not in out
        assert "!!" not in out

    def test_no_doubled_punctuation_after_filler_strip(self):
        out = compress.compress("Fix this. I was wondering if you could! Thanks!")
        # No ".!" "!." "!!" sequences should appear
        for bad in (".!", "!.", "!!", "..", "?!"):
            assert bad not in out, f"found {bad!r} in {out!r}"

    def test_no_orphan_punctuation_at_sentence_start(self):
        out = compress.compress("Fix foo.py. Thanks in advance! Then check bar.py.")
        # Should not leave " ! " between sentences
        assert " ! " not in out
        assert " . " not in out

    def test_thanks_for_x_fragment_dropped(self):
        # "Thanks in advance for any help you can give!" must drop the whole phrase,
        # not leave "for any help you can give!" dangling.
        out = compress.compress(
            "Fix the bug in foo.py. Thanks in advance for any help you can give!"
        )
        assert "for any help you can give" not in out
        assert "thanks in advance" not in out.lower()

    def test_hi_there_pattern(self):
        # Live-test artifact: "Hi there!" was leaving "there!" stranded.
        for greeting in ("Hi there!", "Hello there,", "Hey folks!", "Hi everyone,", "Hey team,"):
            out = compress.compress(f"{greeting} fix foo.py")
            assert "there" not in out.lower(), f"stranded 'there' from {greeting!r}: {out!r}"
            assert "everyone" not in out.lower(), f"stranded 'everyone' from {greeting!r}: {out!r}"
            assert "folks" not in out.lower(), f"stranded 'folks' from {greeting!r}: {out!r}"
            assert "team" not in out.lower(), f"stranded 'team' from {greeting!r}: {out!r}"
            assert "foo.py" in out

    def test_thank_you_so_much_in_advance_eats_full_phrase(self):
        # Real eval-row artifact (judge fidelity 0.82): "thank you so much in advance"
        # was leaving " in advance" stranded after partial match.
        out = compress.compress(
            "Fix foo.py:42 TypeError. Thank you so much in advance for your help!"
        )
        assert "in advance" not in out.lower()
        assert "for your help" not in out
        # Core preserved
        assert "foo.py:42" in out
        assert "TypeError" in out


class TestNoLeadingHiArtifact:
    def test_hi_at_start_with_punctuation(self):
        out = compress.compress("Hi! I was wondering if you could fix foo.py")
        assert not out.lower().startswith("hi")

    def test_hi_between_sentences(self):
        # After stripping filler in a multi-sentence prompt, "Hi" should not appear
        # mid-text as a leftover fragment from a stripped greeting.
        out = compress.compress(
            "Fix foo.py first. Hi I was wondering if you could also fix bar.py."
        )
        # Lowercase check: "hi " should not appear at the start of any sentence
        # (look for ". hi" or sentence-start "hi ")
        assert ". hi " not in out.lower()
        assert ".hi " not in out.lower()
        assert not out.lower().startswith("hi ")

    def test_hi_in_middle_of_prose_preserved(self):
        # If "hi" is part of legit content (e.g. "she said hi to me"), keep it.
        out = compress.compress("She said hi to her teammate")
        assert "hi" in out.lower()


class TestPreservationStillHolds:
    def test_file_paths_still_preserved(self):
        out = compress.compress(
            "Hi I was wondering if you could fix foo.py:42 thanks in advance!"
        )
        assert "foo.py:42" in out

    def test_error_strings_still_preserved(self):
        out = compress.compress(
            "Hi! Could you please tell me why I'm getting TypeError. Thanks in advance!"
        )
        assert "TypeError" in out

    def test_idempotent_after_cleanup(self):
        first = compress.compress(
            "Hi I was wondering if you could in order to fix this. Thanks in advance!"
        )
        second = compress.compress(first)
        assert first == second, f"not idempotent: {first!r} -> {second!r}"


class TestRealEvalRowRegression:
    """Reproduces the exact mode the Claude judge flagged on explain_03 (fidelity 0.60)
    and code_fix_05 ('properly.!' artifact, fidelity 0.82)."""

    def test_explain_03_pattern(self):
        out = compress.compress(
            "Hi! For the purpose of preparing for an interview, I was wondering "
            "if you could explain B-tree indexes in PostgreSQL. Thanks in advance!"
        )
        # Should not strand "for any help" or doubled punct
        assert "for any help" not in out.lower()
        assert ".!" not in out
        # Core content survives
        assert "B-tree" in out
        assert "PostgreSQL" in out

    def test_code_fix_05_pattern(self):
        out = compress.compress(
            "Hi I was wondering if you could fix foo.py:42 at this point in time. "
            "Thanks in advance for any help you can give!"
        )
        assert "foo.py:42" in out
        assert ".!" not in out
        assert "for any help you can give" not in out
        # The whole "thanks in advance for X" tail goes
        assert "thanks" not in out.lower()
