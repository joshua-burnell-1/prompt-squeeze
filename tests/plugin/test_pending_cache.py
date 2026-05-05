# ABOUTME: Tests for pending_cache — write/read/consume a single pending squeeze per session.
# ABOUTME: Drives /sq y/n/undo recovery; cache lives at ~/.claude/prompt-squeeze/pending.json.

import pending_cache  # noqa: E402 (added to sys.path by conftest)


class TestPendingCache:
    def test_read_returns_none_when_no_entry(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        assert pending_cache.read_pending("abc123") is None

    def test_write_then_read(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        pending_cache.write_pending(
            session_hash="abc123",
            seq=1,
            original_text="please fix foo.py",
            squeezed_text="fix foo.py",
            tokens_original=10,
            tokens_squeezed=5,
            saved_dollars=0.0001,
            saved_wh=0.05,
            store_original=False,
        )
        entry = pending_cache.read_pending("abc123")
        assert entry["squeezed_text"] == "fix foo.py"
        assert entry["seq"] == 1
        assert entry["consumed"] is False
        assert "original_text" not in entry or entry["original_text"] is None

    def test_write_with_original_stored_when_explain_on(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        pending_cache.write_pending(
            session_hash="abc123",
            seq=1,
            original_text="please fix foo.py",
            squeezed_text="fix foo.py",
            tokens_original=10,
            tokens_squeezed=5,
            saved_dollars=0.0001,
            saved_wh=0.05,
            store_original=True,
        )
        entry = pending_cache.read_pending("abc123")
        assert entry["original_text"] == "please fix foo.py"

    def test_mark_consumed(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        pending_cache.write_pending(
            session_hash="abc123", seq=1,
            original_text="x", squeezed_text="y",
            tokens_original=1, tokens_squeezed=1,
            saved_dollars=0.0, saved_wh=0.0, store_original=True,
        )
        pending_cache.mark_consumed("abc123")
        entry = pending_cache.read_pending("abc123")
        assert entry["consumed"] is True

    def test_isolation_between_sessions(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        pending_cache.write_pending("abc123", 1, "a", "b", 1, 1, 0.0, 0.0, False)
        pending_cache.write_pending("def456", 2, "c", "d", 1, 1, 0.0, 0.0, False)
        assert pending_cache.read_pending("abc123")["squeezed_text"] == "b"
        assert pending_cache.read_pending("def456")["squeezed_text"] == "d"

    def test_overwrite_replaces_entry(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        pending_cache.write_pending("abc123", 1, "a", "b", 1, 1, 0.0, 0.0, False)
        pending_cache.write_pending("abc123", 2, "c", "d", 1, 1, 0.0, 0.0, False)
        entry = pending_cache.read_pending("abc123")
        assert entry["seq"] == 2
        assert entry["squeezed_text"] == "d"
