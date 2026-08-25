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


class TestWhitelist:
    def test_loopback_bypasses_limit(self, tmp_path):
        """本机测试:回环 IP 同日多次放行。"""
        lim = DailyLimit(tmp_path / "rl.json")
        assert lim.allow("127.0.0.1", today="2026-08-24") is True
        assert lim.allow("127.0.0.1", today="2026-08-24") is True

    def test_ipv4_mapped_loopback_bypasses(self, tmp_path):
        lim = DailyLimit(tmp_path / "rl.json")
        assert lim.allow("::ffff:127.0.0.1", today="2026-08-24") is True

    def test_custom_whitelist_not_recorded(self, tmp_path):
        p = tmp_path / "rl.json"
        lim = DailyLimit(p, whitelist={"5.5.5.5"})
        assert lim.allow("5.5.5.5", today="2026-08-24") is True
        # 白名单 IP 不落盘、不消耗配额
        assert "5.5.5.5" not in lim._data
        assert lim.allow("5.5.5.5", today="2026-08-24") is True

    def test_non_whitelisted_still_limited(self, tmp_path):
        lim = DailyLimit(tmp_path / "rl.json", whitelist={"5.5.5.5"})
        assert lim.allow("6.6.6.6", today="2026-08-24") is True
        assert lim.allow("6.6.6.6", today="2026-08-24") is False
