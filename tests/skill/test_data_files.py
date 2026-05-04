# ABOUTME: Tests that the skill's data files (pricing, energy, eval set) are well-formed.
# ABOUTME: Catches missing keys, schema drift, and broken eval rows before they reach CI.

import json
from pathlib import Path

import pytest

DATA_DIR = (
    Path(__file__).resolve().parents[2] / "skills" / "prompt-squeeze" / "data"
)


class TestPricing:
    @pytest.fixture()
    def pricing(self):
        return json.loads((DATA_DIR / "pricing.json").read_text())

    def test_has_required_models(self, pricing):
        for m in [
            "claude-haiku-4-5",
            "claude-sonnet-4-6",
            "claude-opus-4-6",
            "claude-opus-4-7",
        ]:
            assert m in pricing, f"missing pricing for {m}"

    def test_each_model_has_input_and_output(self, pricing):
        for k, v in pricing.items():
            if k.startswith("_"):
                continue
            assert "input_per_mtok" in v, f"{k} missing input_per_mtok"
            assert "output_per_mtok" in v, f"{k} missing output_per_mtok"
            assert isinstance(v["input_per_mtok"], (int, float))
            assert v["input_per_mtok"] > 0

    def test_opus_47_has_tokenizer_inflation(self, pricing):
        assert "tokenizer_inflation" in pricing["claude-opus-4-7"]
        assert pricing["claude-opus-4-7"]["tokenizer_inflation"] == pytest.approx(1.35)

    def test_has_source_url(self, pricing):
        assert "_source" in pricing
        assert pricing["_source"].startswith("http")


class TestEnergy:
    @pytest.fixture()
    def energy(self):
        return json.loads((DATA_DIR / "energy.json").read_text())

    def test_has_default_joules_per_token(self, energy):
        assert "default_joules_per_token" in energy
        assert energy["default_joules_per_token"] > 0
        assert energy["default_joules_per_token"] < 5  # sanity ceiling

    def test_has_grid_factor(self, energy):
        assert "grid_kg_co2_per_kwh" in energy
        assert 0 < energy["grid_kg_co2_per_kwh"] < 1

    def test_has_cited_sources(self, energy):
        assert energy["source"].startswith("http")
        assert energy["grid_source"].startswith("http")

    def test_has_caveat(self, energy):
        # The skill's credibility depends on this caveat being present
        assert "caveat" in energy
        assert len(energy["caveat"]) > 20


class TestEvalSet:
    @pytest.fixture()
    def rows(self):
        path = DATA_DIR / "eval_set.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]

    def test_has_at_least_20_prompts(self, rows):
        assert len(rows) >= 20

    def test_each_row_has_required_fields(self, rows):
        for r in rows:
            assert "id" in r
            assert "family" in r
            assert "prompt" in r
            assert "must_preserve" in r
            assert isinstance(r["must_preserve"], list)

    def test_covers_all_four_families(self, rows):
        families = {r["family"] for r in rows}
        assert {"code_fix", "explain", "refactor", "multi_turn_starter"} <= families

    def test_must_preserve_substrings_in_prompts(self, rows):
        """If a row says it must preserve substring X, then X must be in the original prompt."""
        for r in rows:
            for sub in r["must_preserve"]:
                assert sub in r["prompt"], (
                    f"{r['id']}: must_preserve substring {sub!r} not found in prompt"
                )

    def test_unique_ids(self, rows):
        ids = [r["id"] for r in rows]
        assert len(ids) == len(set(ids))
