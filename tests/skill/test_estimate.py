# ABOUTME: Tests cost + energy estimator — math correctness, model lookup, tokenizer inflation.
# ABOUTME: Contract for skills/prompt-squeeze/scripts/estimate.py.

import json
import subprocess
import sys
from pathlib import Path

import estimate  # noqa: E402
import pytest

SKILL_SCRIPTS = (
    Path(__file__).resolve().parents[2] / "skills" / "prompt-squeeze" / "scripts"
)
ESTIMATE_PY = SKILL_SCRIPTS / "estimate.py"


class TestEstimateMath:
    def test_zero_savings(self):
        r = estimate.estimate(1000, 1000, "claude-sonnet-4-6")
        assert r["saved_input_tokens"] == 0
        assert r["saved_dollars"] == 0.0
        assert r["saved_wh"] == 0.0
        assert r["compression_ratio"] == 0.0

    def test_50pct_savings_sonnet(self):
        r = estimate.estimate(1000, 500, "claude-sonnet-4-6")
        assert r["saved_input_tokens"] == 500
        assert r["saved_output_estimate"] == 250
        assert r["saved_total_tokens"] == 750
        # input: (500/1e6)*3 = $0.0015; output: (250/1e6)*15 = $0.00375
        assert r["saved_dollars"] == pytest.approx(0.00525, rel=0.01)

    def test_compression_ratio(self):
        r = estimate.estimate(1247, 423, "claude-sonnet-4-6")
        assert r["compression_ratio"] == pytest.approx(0.661, abs=0.01)

    def test_energy_calculation(self):
        # 750 saved tokens * 0.39 J/token = 292.5 J = 0.0813 Wh
        r = estimate.estimate(1000, 500, "claude-sonnet-4-6")
        assert r["saved_wh"] == pytest.approx(0.0813, abs=0.001)

    def test_co2e_calculation(self):
        # 0.0813 Wh / 1000 * 0.4 kg/kWh * 1000 = 0.0325 g
        r = estimate.estimate(1000, 500, "claude-sonnet-4-6")
        assert r["saved_g_co2e"] == pytest.approx(0.0325, abs=0.005)


class TestModelLookup:
    def test_haiku_pricing(self):
        r = estimate.estimate(2000, 1000, "claude-haiku-4-5")
        assert r["model"] == "claude-haiku-4-5"
        # input: (1000/1e6)*1.0 = $0.001; output: (500/1e6)*5.0 = $0.0025
        assert r["saved_dollars"] == pytest.approx(0.0035, abs=0.0005)

    def test_opus_pricing(self):
        r = estimate.estimate(1000, 500, "claude-opus-4-6")
        # input: (500/1e6)*5.0 = $0.0025; output: (250/1e6)*25.0 = $0.00625
        assert r["saved_dollars"] == pytest.approx(0.00875, abs=0.0005)

    def test_unknown_model_raises_or_handles(self):
        with pytest.raises((KeyError, ValueError)):
            estimate.estimate(1000, 500, "nonexistent-model-xyz")


class TestTokenizerInflation:
    def test_opus_47_applies_inflation(self):
        r = estimate.estimate(1000, 500, "claude-opus-4-7")
        assert r["tokenizer_inflation_applied"] == pytest.approx(1.35, abs=0.01)

    def test_sonnet_no_inflation(self):
        r = estimate.estimate(1000, 500, "claude-sonnet-4-6")
        assert (
            r["tokenizer_inflation_applied"] is None
            or r["tokenizer_inflation_applied"] == 1.0
        )


class TestExpectedOutputMultiplier:
    def test_multiplier_zero_means_input_only(self):
        r = estimate.estimate(
            1000, 500, "claude-sonnet-4-6", expected_output_multiplier=0.0
        )
        assert r["saved_output_estimate"] == 0
        # input only: $0.0015
        assert r["saved_dollars"] == pytest.approx(0.0015, abs=0.0005)

    def test_multiplier_one(self):
        r = estimate.estimate(
            1000, 500, "claude-sonnet-4-6", expected_output_multiplier=1.0
        )
        assert r["saved_output_estimate"] == 500


class TestSources:
    def test_includes_sources(self):
        r = estimate.estimate(1000, 500, "claude-sonnet-4-6")
        assert "sources" in r
        assert "pricing" in r["sources"]
        assert "energy" in r["sources"]
        # Sources must be URLs
        assert r["sources"]["pricing"].startswith("http")
        assert r["sources"]["energy"].startswith("http")


class TestCLI:
    def test_cli_json_output(self):
        result = subprocess.run(
            [
                sys.executable,
                str(ESTIMATE_PY),
                "--original-tokens", "1247",
                "--compressed-tokens", "423",
                "--model", "claude-sonnet-4-6",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0, result.stderr
        data = json.loads(result.stdout)
        assert data["compression_ratio"] == pytest.approx(0.661, abs=0.01)

    def test_cli_markdown_output(self):
        result = subprocess.run(
            [
                sys.executable,
                str(ESTIMATE_PY),
                "--original-tokens", "1000",
                "--compressed-tokens", "500",
                "--model", "claude-sonnet-4-6",
                "--format", "markdown",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0, result.stderr
        assert "Prompt squeeze receipt" in result.stdout
        assert "tokens" in result.stdout
        # Must include sources for the sustainability claim
        assert "euromlsys" in result.stdout.lower() or "platform.claude.com" in result.stdout


class TestRounding:
    def test_dollars_rounded_4_decimals(self):
        r = estimate.estimate(123, 45, "claude-sonnet-4-6")
        # No more than 4 decimal places
        s = f"{r['saved_dollars']}"
        if "." in s:
            assert len(s.split(".")[1]) <= 4

    def test_wh_rounded_4_decimals(self):
        r = estimate.estimate(123, 45, "claude-sonnet-4-6")
        s = f"{r['saved_wh']}"
        if "." in s:
            assert len(s.split(".")[1]) <= 4
