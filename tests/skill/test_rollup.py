# ABOUTME: Tests for rollup — derive cumulative savings totals from log.jsonl with Wh equivalents.
# ABOUTME: Drives the status-line counter and /squeeze-stats personal totals.

import json

import rollup  # noqa: E402 (added to sys.path by conftest)


def _write_log(path, rows):
    with open(path, "w") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")


class TestComputeTotals:
    def test_empty_log_returns_zeros(self, tmp_path):
        log = tmp_path / "log.jsonl"
        log.write_text("")
        totals = rollup.compute_totals(log)
        assert totals["lifetime_tokens_saved"] == 0
        assert totals["lifetime_dollars_saved"] == 0.0
        assert totals["lifetime_wh_saved"] == 0.0
        assert totals["lifetime_prompts_realized"] == 0

    def test_only_realized_prompts_count(self, tmp_path):
        log = tmp_path / "log.jsonl"
        _write_log(log, [
            # nudge action -> not counted as realized
            {"ts": "2026-05-04T10:00:00Z", "action": "nudge",
             "achievable_tokens": 100, "estimated_dollars_saved": 0.001, "estimated_wh_saved": 0.05},
            # block_terse with downstream user_action="y" -> realized
            {"ts": "2026-05-04T11:00:00Z", "action": "block_terse", "user_action": "y",
             "achievable_tokens": 200, "estimated_dollars_saved": 0.002, "estimated_wh_saved": 0.10},
            # block_full_banner with user_action="n" -> NOT realized (sent original)
            {"ts": "2026-05-04T12:00:00Z", "action": "block_full_banner", "user_action": "n",
             "achievable_tokens": 300, "estimated_dollars_saved": 0.003, "estimated_wh_saved": 0.15},
            # measure_only -> not realized
            {"ts": "2026-05-04T13:00:00Z", "action": "measure_only"},
        ])
        totals = rollup.compute_totals(log)
        assert totals["lifetime_tokens_saved"] == 200
        assert totals["lifetime_prompts_realized"] == 1
        assert abs(totals["lifetime_dollars_saved"] - 0.002) < 1e-6
        # analyzed-but-not-realized rolls up separately
        assert totals["lifetime_tokens_analyzed_only"] == 400  # 100 + 300

    def test_today_bucket(self, tmp_path):
        # The 'today' bucket uses ISO date prefix matching against the most recent ts.
        log = tmp_path / "log.jsonl"
        _write_log(log, [
            {"ts": "2026-05-03T10:00:00Z", "action": "block_terse", "user_action": "y",
             "achievable_tokens": 100, "estimated_dollars_saved": 0.001, "estimated_wh_saved": 0.05},
            {"ts": "2026-05-04T10:00:00Z", "action": "block_terse", "user_action": "y",
             "achievable_tokens": 50, "estimated_dollars_saved": 0.0005, "estimated_wh_saved": 0.025},
            {"ts": "2026-05-04T15:00:00Z", "action": "block_terse", "user_action": "y",
             "achievable_tokens": 75, "estimated_dollars_saved": 0.0008, "estimated_wh_saved": 0.04},
        ])
        totals = rollup.compute_totals(log, today="2026-05-04")
        assert totals["today_tokens_saved"] == 125  # 50 + 75
        assert totals["today_prompts_realized"] == 2
        assert totals["lifetime_tokens_saved"] == 225


class TestWhEquivalents:
    def test_under_5_wh_shows_raw(self):
        assert "Wh" in rollup.format_wh_equivalent(2.5)

    def test_phone_charges_range(self):
        # 50-500 Wh -> phone charges (~17 Wh per charge)
        out = rollup.format_wh_equivalent(170)
        assert "phone" in out.lower()

    def test_laptop_hours_range(self):
        out = rollup.format_wh_equivalent(1500)
        assert "laptop" in out.lower()

    def test_kwh_range(self):
        out = rollup.format_wh_equivalent(7000)
        assert "kWh" in out

    def test_zero(self):
        # Just "0 Wh" or similar — no division-by-zero
        out = rollup.format_wh_equivalent(0.0)
        assert isinstance(out, str)


class TestStatusLine:
    def test_status_line_format(self, tmp_path):
        log = tmp_path / "log.jsonl"
        _write_log(log, [
            {"ts": "2026-05-04T11:00:00Z", "action": "block_terse", "user_action": "y",
             "achievable_tokens": 487, "estimated_dollars_saved": 0.0009, "estimated_wh_saved": 0.31},
        ] * 10)
        totals = rollup.compute_totals(log, today="2026-05-04")
        status = rollup.format_status_line(totals)
        # Should contain something parseable
        assert "squeeze" in status.lower()
        assert "tok" in status
