# ABOUTME: Tests for session_state — read/write consent state per session, atomic writes, recovery.
# ABOUTME: The hook uses these to remember user consent across multiple prompts in one session.

import json

import session_state  # noqa: E402 (added to sys.path by conftest)


class TestSessionState:
    def test_read_returns_null_for_new_session(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        state = session_state.read_consent("abc123")
        assert state is None

    def test_write_then_read(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        session_state.write_consent("abc123", "yes-session")
        assert session_state.read_consent("abc123") == "yes-session"

    def test_write_no_consent(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        session_state.write_consent("abc123", "no")
        assert session_state.read_consent("abc123") == "no"

    def test_overwrite(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        session_state.write_consent("abc123", "yes-session")
        session_state.write_consent("abc123", "no")
        assert session_state.read_consent("abc123") == "no"

    def test_isolation_between_sessions(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        session_state.write_consent("abc123", "yes-session")
        session_state.write_consent("def456", "no")
        assert session_state.read_consent("abc123") == "yes-session"
        assert session_state.read_consent("def456") == "no"

    def test_corrupt_state_recovers_to_null(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        path = tmp_path / ".claude" / "prompt-squeeze" / "sessions" / "abc123.json"
        path.parent.mkdir(parents=True)
        path.write_text("{not valid json")
        # Corrupt state must not raise — return null and let hook treat as fresh.
        assert session_state.read_consent("abc123") is None

    def test_invalid_value_treated_as_null(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        path = tmp_path / ".claude" / "prompt-squeeze" / "sessions" / "abc123.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"consent": "invalid-value"}))
        assert session_state.read_consent("abc123") is None
