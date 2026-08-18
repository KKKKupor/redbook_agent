"""Tests for tools/xhs_search.py — offline parts: note parsing, cache read/write.

Live scraping (search_notes) is intentionally not covered here — it needs
network + a valid login cookie; it is exercised manually (see README).
"""

import json
from datetime import datetime, timedelta

import pytest

import tools.xhs_search as xhs_search


@pytest.fixture
def cache_file(tmp_path, monkeypatch):
    p = tmp_path / "xhs_search_cache.json"
    monkeypatch.setattr(xhs_search, "CACHE_FILE", p)
    return p


NOTES = [
    {"title": "MBTI职场性格测试｜你是哪种打工人", "likes": "2.3万"},
    {"title": "测测你的职业性格", "likes": "3924"},
]


def _write_cache(path, keyword, scraped_at, notes):
    path.write_text(
        json.dumps(
            {keyword: {"scraped_at": scraped_at.isoformat(), "notes": notes}},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


class TestReadCache:
    def test_returns_notes_when_fresh(self, cache_file):
        _write_cache(cache_file, "MBTI测试", datetime.now(), NOTES)
        assert xhs_search.read_cache("MBTI测试") == NOTES

    def test_returns_none_when_stale(self, cache_file):
        stale = datetime.now() - timedelta(days=8)
        _write_cache(cache_file, "MBTI测试", stale, NOTES)
        assert xhs_search.read_cache("MBTI测试") is None

    def test_returns_none_when_keyword_missing(self, cache_file):
        _write_cache(cache_file, "情商测试", datetime.now(), NOTES)
        assert xhs_search.read_cache("MBTI测试") is None

    def test_returns_none_when_file_missing(self, cache_file):
        assert xhs_search.read_cache("MBTI测试") is None


class TestWriteCache:
    def test_writes_keyword_with_timestamp(self, cache_file):
        xhs_search.write_cache("MBTI测试", NOTES)
        data = json.loads(cache_file.read_text(encoding="utf-8"))
        assert "MBTI测试" in data
        assert data["MBTI测试"]["notes"] == NOTES
        assert "scraped_at" in data["MBTI测试"]

    def test_preserves_other_keywords(self, cache_file):
        _write_cache(cache_file, "情商测试", datetime.now(), NOTES)
        xhs_search.write_cache("MBTI测试", NOTES)
        data = json.loads(cache_file.read_text(encoding="utf-8"))
        assert set(data.keys()) == {"情商测试", "MBTI测试"}


SAMPLE_TEXT = (
    "也是神了\n"
    "呀嘿\n"
    "2.3万\n"
    "蜘蛛会记住人类在家里的生活作息 老铁娱乐观察站\n"
    "笑笑小鸭鸭\n"
    "3924\n"
    "首页\n"
    "我\n"
    "心理治疗师眼中的危险人格信号！\n"
    "硬派心学\n"
    "1745\n"
    "1.2万\n"
)


class TestParseNotes:
    def test_extracts_title_likes_pairs(self):
        notes = xhs_search.parse_notes(SAMPLE_TEXT, max_results=10)
        assert {"title": "也是神了", "likes": "2.3万"} in notes
        assert {"title": "心理治疗师眼中的危险人格信号！", "likes": "1745"} in notes
        # author nicknames and UI chrome must not leak in as titles
        assert "呀嘿" not in [n["title"] for n in notes]
        assert "首页" not in [n["title"] for n in notes]

    def test_caps_results(self):
        notes = xhs_search.parse_notes(SAMPLE_TEXT, max_results=2)
        assert len(notes) <= 2
