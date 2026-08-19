"""Tests for trend_hunter's Playwright integration — offline helpers only.

Covers: context formatting, the cache-first → live → LLM-prior fallback chain,
and prompt injection. LLM and live network calls are mocked (unavoidable).
"""

from agents.trend_hunter.src import main as hunter


class TestFormatSearchContext:
    def test_formats_notes_with_titles_and_likes(self):
        notes = [{"title": "爆款标题A", "likes": "1万"}, {"title": "爆款标题B", "likes": "300"}]
        out = hunter.format_search_context(notes)
        assert "爆款标题A" in out
        assert "1万" in out
        assert "爆款标题B" in out
        assert "推测" in out

    def test_empty_notes_returns_empty_string(self):
        assert hunter.format_search_context([]) == ""


class TestGetSearchContext:
    def test_uses_fresh_cache_without_live_search(self, monkeypatch):
        notes = [{"title": "T1", "likes": "1万"}]
        live_called = {"v": False}

        monkeypatch.setattr("tools.xhs_search.read_cache", lambda kw: notes)

        def fake_live(kw):
            live_called["v"] = True
            return []

        monkeypatch.setattr("tools.xhs_search.search_notes", fake_live)
        assert hunter.get_search_context("MBTI测试") == notes
        assert not live_called["v"]

    def test_live_fallback_on_cache_miss_and_writes_cache(self, monkeypatch):
        notes = [{"title": "T2", "likes": "300"}]
        written = {"v": None}

        monkeypatch.setattr("tools.xhs_search.read_cache", lambda kw: None)
        monkeypatch.setattr("tools.xhs_search.search_notes", lambda kw, **kwargs: notes)
        # search_notes already returns the final bounded list; model filter_notes as identity
        monkeypatch.setattr("tools.xhs_search.filter_notes", lambda ns, **kwargs: ns)
        monkeypatch.setattr("tools.xhs_search.write_cache", lambda kw, n: written.update(v=(kw, n)))
        assert hunter.get_search_context("MBTI测试") == notes
        assert written["v"] == ("MBTI测试", notes)

    def test_returns_none_when_live_fails(self, monkeypatch):
        monkeypatch.setattr("tools.xhs_search.read_cache", lambda kw: None)

        def boom(kw, **kwargs):
            raise RuntimeError("no valid cookie")

        monkeypatch.setattr("tools.xhs_search.search_notes", boom)
        assert hunter.get_search_context("MBTI测试") is None


class TestBuildHumanMessage:
    def test_prompt_includes_notes_when_available(self):
        notes = [{"title": "爆款标题A", "likes": "1万"}]
        msg = hunter.build_human_message("MBTI测试", notes)
        assert "爆款标题A" in msg
        assert "MBTI测试" in msg

    def test_prompt_unchanged_without_notes(self):
        msg = hunter.build_human_message("MBTI测试", None)
        assert "真实数据" not in msg
        assert "MBTI测试" in msg
