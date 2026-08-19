"""Tests for tools/xhs_scraper noise filtering."""

from tools.xhs_scraper import _filter_noise


class TestFilterNoise:
    def test_drops_search_queries(self):
        assert _filter_noise(["人格测试", "恋爱人格匹配测试"]) == ["恋爱人格匹配测试"]

    def test_drops_noise_word_topics(self):
        assert _filter_noise(["免费测试", "怎么测试", "女巫测试"]) == ["女巫测试"]

    def test_keeps_clean_topics(self):
        topics = ["人格阴影测试", "职场性格测试", "失忆测试"]
        assert _filter_noise(topics) == topics
