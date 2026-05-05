# ABOUTME: Tests for redaction — pre-write secret stripping before explain artifacts hit disk.
# ABOUTME: Strips sk-..., ghp_..., AWS access keys, JWT-shaped strings, RFC-5321 emails.

import redaction  # noqa: E402 (added to sys.path by conftest)


class TestRedaction:
    def test_strips_openai_key(self):
        text = "use sk-1234567890abcdefghij1234567890abcdef as the key"
        out = redaction.redact(text)
        assert "sk-1234567890" not in out
        assert "<REDACTED:secret>" in out

    def test_strips_github_token(self):
        text = "auth: ghp_abcdefghijklmnopqrstuvwxyz0123456789 done"
        out = redaction.redact(text)
        assert "ghp_abcdefghij" not in out
        assert "<REDACTED:secret>" in out

    def test_strips_aws_access_key(self):
        text = "aws creds: AKIAIOSFODNN7EXAMPLE rotate them"
        out = redaction.redact(text)
        assert "AKIAIOSFODNN7EXAMPLE" not in out
        assert "<REDACTED:secret>" in out

    def test_strips_jwt(self):
        text = "token: eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTYifQ.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c rest"
        out = redaction.redact(text)
        assert "eyJhbGciOiJIUzI1NiJ9" not in out
        assert "<REDACTED:secret>" in out

    def test_strips_email(self):
        text = "contact alice@example.com about the bug"
        out = redaction.redact(text)
        assert "alice@example.com" not in out
        assert "<REDACTED:secret>" in out

    def test_preserves_normal_code(self):
        text = "fix the bug in foo.py:42 — TypeError on line 100"
        out = redaction.redact(text)
        # No secrets here; output should match input
        assert out == text

    def test_handles_multiple_secrets(self):
        text = "key1: sk-abcdefghij1234567890abcdefghij1234567890 and email a@b.com"
        out = redaction.redact(text)
        assert out.count("<REDACTED:secret>") == 2

    def test_idempotent(self):
        text = "auth: ghp_abcdefghijklmnopqrstuvwxyz0123456789"
        once = redaction.redact(text)
        twice = redaction.redact(once)
        assert once == twice
