"""Tests for utils.command_parser — message intent parsing."""

from utils.command_parser import parse_command


class TestParseCommand:
    def test_generate_with_topic_and_count(self):
        cmd = parse_command("做一个人格阴影测试，20题")
        assert cmd["type"] == "generate"
        # Topic keeps its 测试 suffix and drops the 一个 prefix (fixed in round 1).
        assert cmd["topic"] == "人格阴影测试"
        assert cmd["question_count"] == 20

    def test_generate_default_count(self):
        cmd = parse_command("做一个恋爱人格测试")
        assert cmd["type"] == "generate"
        assert cmd["topic"] == "恋爱人格测试"
        assert cmd["question_count"] == 15

    def test_generate_plain_topic_falls_back(self):
        cmd = parse_command("随便来一个测试")
        assert cmd["type"] == "generate"
        assert cmd["topic"]

    def test_count_capped_at_100(self):
        assert parse_command("做一个测试，200题")["question_count"] == 100

    def test_publish_intent(self):
        assert parse_command("发小红书吧")["type"] == "publish"

    def test_regenerate_intent(self):
        assert parse_command("重新生成")["type"] == "regenerate"

    def test_modify_intent(self):
        cmd = parse_command("改成30题")
        assert cmd["type"] == "modify"
        assert cmd["new_count"] == 30

    def test_approve_intent(self):
        assert parse_command("不错，就这样")["type"] == "approve_publish"
