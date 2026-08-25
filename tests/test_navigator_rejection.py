"""Tests for navigator web-entry gate — LLM 判读用户意图(选题/题量/拒绝)。

user_message 非空时先走 gate 判读,再走决策;日常调度不传 user_message,行为不变。
"""

import json

import pytest

import agents.navigator.src.main as nav


class _FakeResp:
    def __init__(self, content):
        self.content = content
        self.response_metadata = {}
        self.usage_metadata = {"input_tokens": 10, "output_tokens": 20}


class _SeqLLM:
    """按序返回响应(超出后重复最后一个),记录调用次数。"""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def invoke(self, messages, **kwargs):
        r = self.responses[min(self.calls, len(self.responses) - 1)]
        self.calls += 1
        return _FakeResp(r)


class _FakeTool:
    def __init__(self):
        self.invoked = 0

    def invoke(self, *a, **k):
        self.invoked += 1
        return {}


GATE_OK = json.dumps({"rejected": False, "user_requested_topic": "", "user_requested_count": 15},
                     ensure_ascii=False)
DECISION = {
    "strategy": "exploit",
    "selected_topic": "人格阴影测试",
    "dimension_defs": [
        {"id": "D1", "name": "维度一", "description": "d", "high_label": "高", "low_label": "低"},
    ],
    "target_question_count": 15,
    "suggested_price": 1.99,
    "best_publish_hour": 21,
    "decision_reasoning": "r",
}
DECISION_JSON = json.dumps(DECISION, ensure_ascii=False)


@pytest.fixture(autouse=True)
def _quiet(monkeypatch):
    """消噪:钉钉推送 no-op、review 存档 no-op。"""
    monkeypatch.setattr("utils.health.notifier.send", lambda *a, **k: None)
    monkeypatch.setattr(nav, "save", lambda *a, **k: None)
    monkeypatch.setattr(nav, "save_prompt", lambda *a, **k: None)
    monkeypatch.setattr(nav, "save_response", lambda *a, **k: None)


@pytest.fixture
def fake_tools(monkeypatch):
    rankings, diversity = _FakeTool(), _FakeTool()
    monkeypatch.setattr(nav, "get_product_rankings", rankings)
    monkeypatch.setattr(nav, "get_topic_diversity", diversity)
    return rankings, diversity


def _install_llm(monkeypatch, *responses):
    fake = _SeqLLM(list(responses))
    monkeypatch.setattr(nav, "navigator_llm", lambda: fake)
    return fake


class TestGateInterpretation:
    def test_gate_extracts_topic_and_count(self, monkeypatch, fake_tools):
        """LLM 判读选题与题量:「五题,你适合什么工作」→ 选题「你适合什么工作」、5题。"""
        gate = json.dumps({"rejected": False, "user_requested_topic": "你适合什么工作",
                           "user_requested_count": 5}, ensure_ascii=False)
        fake = _install_llm(monkeypatch, gate, DECISION_JSON)
        result = nav.navigator_node({
            "selected_topic": "",
            "target_question_count": 15,
            "suggested_price": 1.99,
            "user_message": "五题，你适合什么工作",
            "entry_web": True,
        })
        assert fake.calls == 2  # gate + decision
        assert result["selected_topic"] == "你适合什么工作"
        assert result["target_question_count"] == 5
        assert result["dimension_defs"]

    def test_gate_empty_topic_falls_back_to_pool(self, monkeypatch, fake_tools):
        """判读无主题 → 选题池(标题不再是用户原话)。"""
        fake = _install_llm(monkeypatch, GATE_OK, DECISION_JSON)
        result = nav.navigator_node({
            "selected_topic": "",
            "target_question_count": 15,
            "suggested_price": 1.99,
            "user_message": "帮我生成一个测试",
            "entry_web": True,
        })
        assert result["selected_topic"]  # 池选题(非空)
        assert result["selected_topic"] != "帮我生成一个测试"

    def test_gate_rejects_unrelated_input(self, monkeypatch, fake_tools):
        """无关输入 → gate 拒绝,不进入决策调用。"""
        gate = json.dumps({"rejected": True,
                           "reply": "我只生成付费心理测试题,例如「做一个人格阴影测试,15题」。"},
                          ensure_ascii=False)
        fake = _install_llm(monkeypatch, gate)
        result = nav.navigator_node({
            "selected_topic": "",
            "target_question_count": 15,
            "suggested_price": 1.99,
            "user_message": "你叫啥",
            "entry_web": True,
        })
        assert result["rejected"] is True
        assert "人格阴影测试" in result["reply"]
        assert fake.calls == 1  # 只调了 gate

    def test_gate_count_overflow_rejected_web_only(self, monkeypatch, fake_tools):
        """判读 1000 题 + web 入口 → 拒绝文案(LLM 生成)。"""
        gate = json.dumps({"rejected": False, "user_requested_topic": "",
                           "user_requested_count": 1000}, ensure_ascii=False)
        refusal = '{"reply": "单次最多60题,请减少题量。"}'
        fake = _install_llm(monkeypatch, gate, refusal)
        result = nav.navigator_node({
            "selected_topic": "",
            "target_question_count": 15,
            "suggested_price": 1.99,
            "user_message": "给我做1000道测试题",
            "entry_web": True,
        })
        assert result["rejected"] is True
        assert result["reply"] == "单次最多60题,请减少题量。"
        assert fake.calls == 2  # gate + 拒绝文案
        assert fake_tools[0].invoked > 0  # 工具调用在 gate 之前(数据收集先行)

    def test_no_user_message_skips_gate(self, monkeypatch, fake_tools):
        """日常调度/无 user_message:单次决策调用,无 gate,行为不变。"""
        fake = _install_llm(monkeypatch, DECISION_JSON)
        result = nav.navigator_node({
            "selected_topic": "人格阴影测试",
            "target_question_count": 200,
            "suggested_price": 1.99,
        })
        assert fake.calls == 1
        assert "rejected" not in result or result.get("rejected") is not True
        assert result["dimension_defs"]

    def test_overflow_without_entry_web_not_rejected(self, monkeypatch, fake_tools):
        """判读 1000 题但非 web 入口(钉钉):不拒绝(仅网页生效)。"""
        gate = json.dumps({"rejected": False, "user_requested_topic": "",
                           "user_requested_count": 1000}, ensure_ascii=False)
        _install_llm(monkeypatch, gate, DECISION_JSON)
        result = nav.navigator_node({
            "selected_topic": "",
            "target_question_count": 15,
            "suggested_price": 1.99,
            "user_message": "做1000道测试题",
        })
        assert result.get("rejected") is not True
        assert result["target_question_count"] == 1000