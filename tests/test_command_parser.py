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

    def test_count_not_capped(self):
        """题量原样返回(截断已移除);超限校验由 navigator 拒绝逻辑负责。"""
        assert parse_command("做一个测试，200题")["question_count"] == 200
        assert parse_command("做一个测试，1000题")["question_count"] == 1000

    def test_count_with_measure_word(self):
        """量词兼容:"1000道测试题" / "15道测试题" 同样提取题数。"""
        assert parse_command("给我做1000道测试题")["question_count"] == 1000
        assert parse_command("做15道测试题")["question_count"] == 15

    def test_count_bare_measure_word(self):
        """仅量词无"题"字:"做15道"。"""
        assert parse_command("做15道")["question_count"] == 15

    def test_topic_stripped_with_measure_word(self):
        cmd = parse_command("做一个MBTI测试，20道题")
        assert cmd["topic"] == "MBTI测试"
        assert cmd["question_count"] == 20

    def test_generate_verb_prefix(self):
        """「帮我生成」等生成动词同样解析出主题。"""
        assert parse_command("帮我生成一个人格阴影测试")["topic"] == "人格阴影测试"
        assert parse_command("帮我生成一个人格阴影测试，10道题")["question_count"] == 10

    def test_no_topic_yields_empty_for_pool(self):
        """无实质主题 → topic 为空,由 navigator 走选题池(不再把 prompt 当标题)。"""
        assert parse_command("呃，帮我生成一个10道测试题")["topic"] == ""
        assert parse_command("生成15道测试题")["topic"] == ""
        assert parse_command("帮我生成测试")["topic"] == ""
        assert parse_command("做15道")["topic"] == ""

    def test_bare_topic_with_count_stripped(self):
        """无动词前缀的选题(如"你几岁了,10道题")同样剥离题量尾巴。"""
        cmd = parse_command("你几岁了，10道题")
        assert cmd["topic"] == "你几岁了"
        assert cmd["question_count"] == 10

    def test_chinese_number_counts(self):
        """中文数字题量:"五题"→5、"十五题"→15、"二十三题"→23、"十题"→10。"""
        assert parse_command("你的核心欲望，五题")["question_count"] == 5
        assert parse_command("你的核心欲望，五题")["topic"] == "你的核心欲望"
        assert parse_command("做十五题")["question_count"] == 15
        assert parse_command("做二十三道测试题")["question_count"] == 23
        assert parse_command("做十题")["question_count"] == 10
        assert parse_command("做两题")["question_count"] == 2
        assert parse_command("做五道")["question_count"] == 5

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
