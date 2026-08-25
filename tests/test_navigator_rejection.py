"""Tests for navigator web-entry rejection — count overflow and unrelated prompts.

仅 user_message 非空的网页场景触发;钉钉/日常调度不传 user_message,行为不变。
"""

import pytest

import agents.navigator.src.main as nav


class _FakeResp:
    def __init__(self, content):
        self.content = content
        self.response_metadata = {}
        self.usage_metadata = {"input_tokens": 10, "output_tokens": 20}


class _FakeLLM:
    """invoke 返回固定响应或抛异常;记录调用。"""

    def __init__(self, respond):
        self._respond = respond
        self.calls = []

    def invoke(self, messages, **kwargs):
        self.calls.append(messages)
        return self._respond()


class _FakeTool:
    def __init__(self):
        self.invoked = 0

    def invoke(self, *a, **k):
        self.invoked += 1
        return {}


NORMAL_DECISION = {
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


def _install_llm(monkeypatch, respond):
    fake = _FakeLLM(respond)
    monkeypatch.setattr(nav, "navigator_llm", lambda: fake)
    return fake


class TestCountOverflow:
    def test_reject_when_count_exceeds_max(self, monkeypatch, fake_tools):
        fake = _install_llm(monkeypatch, lambda: _FakeResp('{"reply": "单次最多60题,请减少题量。"}'))
        result = nav.navigator_node({
            "selected_topic": "人格阴影测试",
            "target_question_count": 1000,
            "suggested_price": 1.99,
            "user_message": "给我做1000道测试题",
        })
        assert result["rejected"] is True
        assert result["reply"]
        # 路径 A 在工具调用之前:零副作用
        assert fake_tools[0].invoked == 0
        assert fake_tools[1].invoked == 0

    def test_llm_failure_still_rejected_with_fallback(self, monkeypatch, fake_tools):
        def boom():
            raise RuntimeError("api down")

        _install_llm(monkeypatch, boom)
        result = nav.navigator_node({
            "selected_topic": "人格阴影测试",
            "target_question_count": 500,
            "suggested_price": 1.99,
            "user_message": "做500题",
        })
        assert result["rejected"] is True
        assert result["reply"] == nav._REFUSAL_FALLBACK

    def test_no_user_message_skips_count_check(self, monkeypatch, fake_tools):
        """钉钉/日常调度不传 user_message:大题量不触发拒绝(仅网页生效)。"""
        _install_llm(monkeypatch, lambda: _FakeResp(__import__("json").dumps(NORMAL_DECISION, ensure_ascii=False)))
        result = nav.navigator_node({
            "selected_topic": "人格阴影测试",
            "target_question_count": 200,
            "suggested_price": 1.99,
        })
        assert "rejected" not in result or result.get("rejected") is not True
        assert result["dimension_defs"]


class TestUnrelatedInput:
    def test_reject_when_user_message_unrelated(self, monkeypatch, fake_tools):
        fake = _install_llm(
            monkeypatch,
            lambda: _FakeResp('{"rejected": true, "reply": "我只生成付费心理测试题,例如「做一个人格阴影测试,15题」。"}'),
        )
        result = nav.navigator_node({
            "selected_topic": "你叫啥",
            "target_question_count": 15,
            "suggested_price": 1.99,
            "user_message": "你叫啥",
        })
        assert result["rejected"] is True
        assert "人格阴影测试" in result["reply"]
        # 判定段确实进入了 prompt
        assert any("你叫啥" in str(m.content) for m in fake.calls[0])

    def test_related_input_proceeds_normally(self, monkeypatch, fake_tools):
        """用户确实在请求测试题:正常决策流程,不拒绝。"""
        _install_llm(monkeypatch, lambda: _FakeResp(__import__("json").dumps(NORMAL_DECISION, ensure_ascii=False)))
        result = nav.navigator_node({
            "selected_topic": "人格阴影测试",
            "target_question_count": 15,
            "suggested_price": 1.99,
            "user_message": "做一个人格阴影测试,15题",
        })
        assert result.get("rejected") is not True
        assert result["dimension_defs"]
        assert result["selected_topic"] == "人格阴影测试"
