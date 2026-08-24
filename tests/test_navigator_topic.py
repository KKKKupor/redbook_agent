"""Tests for navigator topic selection: user-first, pool no-repeat, cycle reset."""

from agents.navigator.src.main import select_topic

POOL = ["A", "B", "C"]


class TestSelectTopic:
    def test_user_topic_wins(self):
        sel = select_topic("用户选题", POOL, set(), 0.1)
        assert sel["topic"] == "用户选题"
        assert sel["strategy"] == "user"
        assert sel["generated"] == set()  # 用户选题不记录

    def test_exploit_picks_first_ungenerated(self):
        sel = select_topic(None, POOL, {"A"}, 0.1)
        assert sel["topic"] == "B"
        assert sel["strategy"] == "exploit"
        assert sel["generated"] == {"A", "B"}

    def test_explore_picks_from_remaining(self):
        sel = select_topic(None, POOL, {"A"}, 0.9)
        assert sel["topic"] in ("B", "C")
        assert sel["strategy"] == "explore"

    def test_cycle_reset_when_exhausted(self):
        sel = select_topic(None, POOL, {"A", "B", "C"}, 0.1)
        assert sel["strategy"] == "exploit"
        assert sel["topic"] == "A"
