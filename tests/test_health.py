"""Tests for utils.health — note/dedup/cap/reset/message building."""

from utils import health


class TestBuildAlertMessage:
    def test_contains_node_kind_detail(self):
        msg = health.build_alert_message("navigator", "topic_pool_hardcoded", "文件缺失")
        assert "navigator" in msg
        assert "topic_pool_hardcoded" in msg
        assert "文件缺失" in msg

    def test_detail_truncated(self):
        msg = health.build_alert_message("x", "y", "长" * 500)
        assert len(msg) < 400


class TestNoteDedupAndCap:
    def test_same_node_kind_pushes_once_per_run(self, monkeypatch):
        health.reset()
        calls = {"v": 0}
        monkeypatch.setattr(health.notifier, "send", lambda **kw: calls.update(v=calls["v"] + 1))
        health.note("navigator", "llm_parse_failed", "a")
        health.note("navigator", "llm_parse_failed", "b")
        assert calls["v"] == 1
        assert len(health.summary()) == 1

    def test_cap_at_ten_per_run(self, monkeypatch):
        health.reset()
        calls = {"v": 0}
        monkeypatch.setattr(health.notifier, "send", lambda **kw: calls.update(v=calls["v"] + 1))
        for i in range(15):
            health.note(f"node{i}", "kind", "")
        assert calls["v"] == 10

    def test_reset_clears_dedup(self, monkeypatch):
        health.reset()
        calls = {"v": 0}
        monkeypatch.setattr(health.notifier, "send", lambda **kw: calls.update(v=calls["v"] + 1))
        health.note("a", "b", "")
        health.reset()
        health.note("a", "b", "")
        assert calls["v"] == 2

    def test_push_failure_does_not_raise(self, monkeypatch):
        health.reset()
        def boom(**kw):
            raise RuntimeError("webhook down")
        monkeypatch.setattr(health.notifier, "send", boom)
        health.note("a", "b", "")  # 不得抛出
        assert len(health.summary()) == 1
