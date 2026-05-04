# ABOUTME: Tests MCP stats server — tool registration, log aggregation, weekly report rendering.
# ABOUTME: Contract for mcp/stats_server.py.

import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SERVER_PY = REPO / "mcp" / "stats_server.py"


def write_synthetic_log(log_path: Path, n_rows: int = 5):
    log_path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    now = datetime.now(UTC)
    for i in range(n_rows):
        rows.append(
            {
                "ts": (now - timedelta(hours=i)).isoformat(),
                "session": f"sha256:{i:016x}",
                "model": "claude-sonnet-4-6",
                "prompt_hash": f"sha256:{i*7:016x}",
                "original_tokens": 1000 + i * 100,
                "achievable_tokens": 400 + i * 30,
                "achievable_pct": 0.6,
                "estimated_dollars_saved": 0.001 * (i + 1),
                "estimated_wh_saved": 0.05 * (i + 1),
                "action": "nudge",
                "user_action": None,
            }
        )
    log_path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")


class TestServerSelfTest:
    def test_self_test_runs(self):
        result = subprocess.run(
            [sys.executable, str(SERVER_PY), "--self-test"],
            capture_output=True,
            text=True,
            timeout=20,
        )
        assert result.returncode == 0, result.stderr


class TestServerImports:
    def test_module_imports_cleanly(self):
        result = subprocess.run(
            [sys.executable, "-c", f"import importlib.util, sys; spec = importlib.util.spec_from_file_location('s', r'{SERVER_PY}'); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); print('OK')"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0, result.stderr
        assert "OK" in result.stdout


class TestPersonalStats:
    def test_aggregates_log(self, tmp_path, monkeypatch):
        log_path = tmp_path / "prompt-squeeze" / "log.jsonl"
        write_synthetic_log(log_path, n_rows=5)
        monkeypatch.setenv("HOME", str(tmp_path))

        # Import the server module to call personal_stats directly
        import importlib.util
        spec = importlib.util.spec_from_file_location("stats_server", SERVER_PY)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)

        # Find the function — server may register it via @tool or expose directly
        fn = getattr(m, "personal_stats", None) or getattr(m, "_personal_stats", None)
        if fn is None:
            pytest.skip("personal_stats not exposed for direct call")

        result = fn(window="7d") if not hasattr(fn, "fn") else fn.fn(window="7d")
        # Result may be JSON string or dict
        if isinstance(result, str):
            result = json.loads(result)
        assert "prompts" in result or "prompts_processed" in result or "count" in result


class TestWeeklyReport:
    def test_returns_markdown(self, tmp_path, monkeypatch):
        log_path = tmp_path / "prompt-squeeze" / "log.jsonl"
        write_synthetic_log(log_path, n_rows=10)
        monkeypatch.setenv("HOME", str(tmp_path))

        import importlib.util
        spec = importlib.util.spec_from_file_location("stats_server", SERVER_PY)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)

        fn = getattr(m, "weekly_report", None) or getattr(m, "_weekly_report", None)
        if fn is None:
            pytest.skip("weekly_report not exposed for direct call")

        result = fn(window="7d") if not hasattr(fn, "fn") else fn.fn(window="7d")
        if isinstance(result, str):
            text = result
        else:
            text = result.get("markdown") or result.get("text") or json.dumps(result)
        # Markdown report must include sources for credibility
        assert "tokens" in text.lower()
        # Either pricing or energy citation
        assert "euromlsys" in text.lower() or "platform.claude.com" in text.lower() or "source" in text.lower()


class TestEmptyLog:
    def test_no_log_file_returns_zero_aggregate(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        # No log file at all
        import importlib.util
        spec = importlib.util.spec_from_file_location("stats_server", SERVER_PY)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)

        fn = getattr(m, "personal_stats", None) or getattr(m, "_personal_stats", None)
        if fn is None:
            pytest.skip("personal_stats not exposed for direct call")

        result = fn(window="7d") if not hasattr(fn, "fn") else fn.fn(window="7d")
        if isinstance(result, str):
            result = json.loads(result)
        # Must not crash; should return zeros
        prompts = result.get("prompts") or result.get("prompts_processed") or result.get("count") or 0
        assert prompts == 0
