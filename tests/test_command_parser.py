"""Tests for utils.command_parser — 指令分类(语义判读在 navigator LLM,不在此层)。"""

from utils.command_parser import parse_command


class TestParseCommand:
    def test_generate_type_passes_through(self):
        """generate 类只透传原文,选题/题量由 navigator LLM 判读。"""
        cmd = parse_command("五题，你适合什么工作")
        assert cmd["type"] == "generate"
        assert cmd["text"] == "五题，你适合什么工作"
        assert cmd["topic"] == ""
        assert cmd["question_count"] == 15

    def test_generate_any_phrasing_is_generate(self):
        """任何句式(不是协调指令)都归 generate,交给 LLM 判读。"""
        for t in ["你几岁了", "帮我生成一个人格阴影测试", "随便来一个测试", "测测我是什么动物"]:
            assert parse_command(t)["type"] == "generate"

    def test_publish_intent(self):
        assert parse_command("发小红书吧")["type"] == "publish"

    def test_regenerate_intent(self):
        assert parse_command("重新生成")["type"] == "regenerate"

    def test_modify_intent(self):
        cmd = parse_command("改成30题")
        assert cmd["type"] == "modify"
        assert cmd["new_count"] == 30
        assert parse_command("改成五题")["new_count"] == 5

    def test_approve_intent(self):
        assert parse_command("不错，就这样")["type"] == "approve_publish"