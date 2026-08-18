"""Tests for packager's recommended-copy extraction (_extract_recommended).

契约(copy.md 输出格式):【首推版本】块 = 完整文案(含话题标签),
其后紧跟【推荐理由】标记 + 理由。提取函数只返回文案部分;
块缺失/不合格(无话题标签)时返回 None,由调用方走兜底文案。
"""

from agents.packager.src.main import _extract_recommended

RAW_NEW_FORMAT = """【A. 痛点共鸣型】
文案A内容……#标签

【B. 好奇心驱动型】
60道题，挖出的性格盲区，第4个让我起鸡皮疙瘩。
第二段内容。
#人格阴影测试 #性格盲点

【C. 挑战/反直觉型】
文案C内容……#标签

【首推版本】
60道题，挖出的性格盲区，第4个让我起鸡皮疙瘩。
第二段内容。
#人格阴影测试 #性格盲点
【推荐理由】
这类测试的核心用户，不是来寻求安慰的，而是来“抓自己”的。B版本用“第4个盲区”和“情感隔离”这种具体但未言尽的结果片段，精准制造了信息缺口。
"""


class TestExtractRecommended:
    def test_extracts_copy_until_reason_marker(self):
        copy = _extract_recommended(RAW_NEW_FORMAT)
        assert copy.startswith("60道题")
        assert "#人格阴影测试" in copy
        assert "不是来寻求安慰" not in copy  # 理由不得混入文案

    def test_multiline_copy_preserved(self):
        copy = _extract_recommended(RAW_NEW_FORMAT)
        assert "第二段内容。" in copy
        assert copy.count("\n") == 2  # 三行文案完整保留

    def test_leading_version_selector_dropped(self):
        raw = "【首推版本】\nB. 好奇心驱动型\n60道题，挖出的性格盲区。#人格阴影测试\n【推荐理由】\n理由……"
        copy = _extract_recommended(raw)
        assert copy == "60道题，挖出的性格盲区。#人格阴影测试"

    def test_rationale_only_block_returns_none(self):
        # 旧格式产物(版本名+理由,无完整文案):不得把理由当文案 → None 走兜底
        raw = "【首推版本】\nB. 好奇心驱动型\n这类测试的核心用户，不是来寻求安慰的，而是来“抓自己”的。"
        assert _extract_recommended(raw) is None

    def test_missing_marker_returns_none(self):
        assert _extract_recommended("【A. 痛点共鸣型】\n文案内容#标签") is None

    def test_copy_without_tags_returns_none(self):
        raw = "【首推版本】\n60道题挖出的性格盲区，第4个最意外。\n【推荐理由】\n理由……"
        assert _extract_recommended(raw) is None
