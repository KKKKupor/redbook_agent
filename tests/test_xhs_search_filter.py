"""Tests for xhs_search filtering: parse_likes / filter_notes / time attachment."""

from tools.xhs_search import parse_likes, filter_notes, parse_notes


class TestParseLikes:
    def test_wan(self):
        assert parse_likes("2.3万") == 23000
        assert parse_likes("1万") == 10000

    def test_plain(self):
        assert parse_likes("3924") == 3924
        assert parse_likes("300") == 300

    def test_invalid(self):
        assert parse_likes("") == 0
        assert parse_likes("abc") == 0


class TestFilterNotes:
    def _notes(self):
        return [
            {"title": "冷门", "likes": "300"},
            {"title": "爆款", "likes": "2.3万"},
            {"title": "中等", "likes": "3924"},
        ]

    def test_sorts_by_likes_desc(self):
        out = filter_notes(self._notes())
        assert [n["title"] for n in out] == ["爆款", "中等", "冷门"]
        assert out[0]["likes_num"] == 23000

    def test_min_likes(self):
        out = filter_notes(self._notes(), min_likes=1000)
        assert [n["title"] for n in out] == ["爆款", "中等"]

    def test_top_n(self):
        out = filter_notes(self._notes(), top_n=1)
        assert [n["title"] for n in out] == ["爆款"]

    def test_age_filter_drops_unknown_when_active(self):
        notes = [{"title": "无日期", "likes": "1万"}, {"title": "三天前", "likes": "1万", "days_ago": 3}]
        out = filter_notes(notes, max_age_days=7)
        assert [n["title"] for n in out] == ["三天前"]

    def test_age_filter_keeps_all_when_inactive(self):
        notes = [{"title": "无日期", "likes": "1万"}, {"title": "十天前", "likes": "1万", "days_ago": 10}]
        out = filter_notes(notes)
        assert len(out) == 2


class TestParseNotesTimeAttachment:
    def test_attaches_days_ago_when_time_line_follows_likes(self):
        text = "标题甲\n作者名\n1.2万\n3天前\n下一段内容"
        notes = parse_notes(text)
        assert notes[0]["days_ago"] == 3


class TestParseNotesOrphanLikes:
    def test_orphan_likes_line_does_not_pair_previous_author(self):
        text = "危险人格信号!\n硬派心学\n1745\n1.2万"
        notes = parse_notes(text)
        titles = [n["title"] for n in notes]
        assert "硬派心学" not in titles
        assert {"title": "危险人格信号!", "likes": "1745"} in notes
