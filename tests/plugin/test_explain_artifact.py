# ABOUTME: Tests for explain_artifact — write per-squeeze JSON files for /sq explain deep-dive.
# ABOUTME: Verifies redaction, retention cap, atomic writes, and disable semantics.

import json

import explain_artifact  # noqa: E402 (added to sys.path by conftest)


class TestWriteArtifact:
    def test_writes_redacted_artifact(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        explain_artifact.write_artifact(
            session_hash="abc123",
            seq=1,
            original_text="please use sk-abcdefghij1234567890abcdefghij1234567890 to fix bar",
            squeezed_text="use sk-abcdefghij1234567890abcdefghij1234567890 to fix bar",
            tokens_original=20,
            tokens_squeezed=15,
            rules_fired=[
                {"rule_id": "FILLER_PLEASE", "span": [0, 7], "removed": "please ",
                 "tokens_saved": 1},
            ],
        )
        path = tmp_path / ".claude" / "prompt-squeeze" / "explain" / "abc123-1.json"
        assert path.exists()
        data = json.loads(path.read_text())
        # Original key fields present
        assert data["session"] == "abc123"
        assert data["seq"] == 1
        assert data["tokens_original"] == 20
        assert data["tokens_squeezed"] == 15
        # Redaction was applied
        assert "sk-abcdefghij" not in data["original_text"]
        assert "sk-abcdefghij" not in data["squeezed_text"]
        assert "<REDACTED:secret>" in data["original_text"]
        # Rules carried through
        assert data["rules_fired"][0]["rule_id"] == "FILLER_PLEASE"

    def test_directory_perms_0700(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        explain_artifact.write_artifact(
            session_hash="abc123", seq=1,
            original_text="x", squeezed_text="y",
            tokens_original=1, tokens_squeezed=1,
            rules_fired=[],
        )
        explain_dir = tmp_path / ".claude" / "prompt-squeeze" / "explain"
        # Mode bits — owner rwx only (0700 = 0o700 = 448)
        mode = explain_dir.stat().st_mode & 0o777
        assert mode == 0o700, f"expected 0700, got {oct(mode)}"

    def test_file_perms_0600(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        explain_artifact.write_artifact(
            session_hash="abc123", seq=1,
            original_text="x", squeezed_text="y",
            tokens_original=1, tokens_squeezed=1,
            rules_fired=[],
        )
        path = tmp_path / ".claude" / "prompt-squeeze" / "explain" / "abc123-1.json"
        mode = path.stat().st_mode & 0o777
        assert mode == 0o600, f"expected 0600, got {oct(mode)}"


class TestRetention:
    def test_retains_only_last_100(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        # Write 105 artifacts
        for i in range(1, 106):
            explain_artifact.write_artifact(
                session_hash="ses1", seq=i,
                original_text=f"prompt {i}", squeezed_text=f"sq {i}",
                tokens_original=10, tokens_squeezed=5,
                rules_fired=[],
            )
        explain_dir = tmp_path / ".claude" / "prompt-squeeze" / "explain"
        files = sorted(explain_dir.glob("*.json"))
        assert len(files) == 100
        # Should keep the latest (seq 6-105) and prune the earliest (1-5)
        assert not (explain_dir / "ses1-1.json").exists()
        assert (explain_dir / "ses1-105.json").exists()


class TestDisable:
    def test_disable_removes_directory(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        explain_artifact.write_artifact(
            session_hash="ses1", seq=1,
            original_text="a", squeezed_text="b",
            tokens_original=1, tokens_squeezed=1,
            rules_fired=[],
        )
        explain_dir = tmp_path / ".claude" / "prompt-squeeze" / "explain"
        assert explain_dir.exists()
        explain_artifact.disable()
        assert not explain_dir.exists()


class TestReadArtifact:
    def test_read_latest(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        for i in (1, 2, 3):
            explain_artifact.write_artifact(
                session_hash="ses1", seq=i,
                original_text=f"o{i}", squeezed_text=f"s{i}",
                tokens_original=1, tokens_squeezed=1,
                rules_fired=[],
            )
        latest = explain_artifact.read_artifact(session_hash="ses1", relative_index=0)
        assert latest["seq"] == 3
        assert latest["squeezed_text"] == "s3"

    def test_read_relative_index(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        for i in (1, 2, 3):
            explain_artifact.write_artifact(
                session_hash="ses1", seq=i,
                original_text=f"o{i}", squeezed_text=f"s{i}",
                tokens_original=1, tokens_squeezed=1,
                rules_fired=[],
            )
        # 0 = newest, 1 = second newest, 2 = oldest
        prev = explain_artifact.read_artifact(session_hash="ses1", relative_index=1)
        assert prev["seq"] == 2

    def test_read_returns_none_when_no_artifact(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        result = explain_artifact.read_artifact(session_hash="missing", relative_index=0)
        assert result is None
