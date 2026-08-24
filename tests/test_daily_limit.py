"""Tests for utils.daily_limit — one generation per IP per day."""

from utils.daily_limit import DailyLimit


class TestDailyLimit:
    def test_first_allow_then_deny_same_day(self, tmp_path):
        lim = DailyLimit(tmp_path / "rl.json")
        assert lim.allow("1.2.3.4", today="2026-08-24") is True
        assert lim.allow("1.2.3.4", today="2026-08-24") is False

    def test_new_day_allows_again(self, tmp_path):
        lim = DailyLimit(tmp_path / "rl.json")
        assert lim.allow("1.2.3.4", today="2026-08-24") is True
        assert lim.allow("1.2.3.4", today="2026-08-25") is True

    def test_different_ips_independent(self, tmp_path):
        lim = DailyLimit(tmp_path / "rl.json")
        assert lim.allow("1.1.1.1", today="2026-08-24") is True
        assert lim.allow("2.2.2.2", today="2026-08-24") is True

    def test_persists_across_instances(self, tmp_path):
        p = tmp_path / "rl.json"
        DailyLimit(p).allow("9.9.9.9", today="2026-08-24")
        lim2 = DailyLimit(p)
        assert lim2.allow("9.9.9.9", today="2026-08-24") is False
