"""Tests for utils.token_tracker.add_from_response — streaming responses
expose usage in usage_metadata instead of response_metadata.token_usage."""

import threading

from utils.token_tracker import add, add_from_response, reset, summary


class _FakeResp:
    def __init__(self, token_usage=None, usage_metadata=None):
        # token_usage 为 None 时键缺席,与真实 langchain 流式响应一致
        self.response_metadata = {} if token_usage is None else {"token_usage": token_usage}
        self.usage_metadata = usage_metadata


class TestAddFromResponse:
    def test_legacy_token_usage_key(self):
        reset()
        add_from_response("nav", _FakeResp(token_usage={"prompt_tokens": 100, "completion_tokens": 50}))
        s = summary()
        assert s["total_input"] == 100
        assert s["total_output"] == 50
        assert s["total_cost"] > 0

    def test_streaming_usage_metadata_fallback(self):
        reset()
        add_from_response("nav", _FakeResp(token_usage=None, usage_metadata={"input_tokens": 80, "output_tokens": 20}))
        s = summary()
        assert s["total_input"] == 80
        assert s["total_output"] == 20
        assert s["total_cost"] > 0


class TestThreadIsolation:
    def test_records_are_thread_local(self):
        """并发生成链各占一个线程:一条链的记录不能被另一条链看到。"""
        reset()
        add("chain_a", 100, 50)

        results = {}
        errors = []

        def read_other_thread():
            try:
                results["other"] = summary()["total_input"]
            except Exception as e:  # pragma: no cover
                errors.append(e)

        t = threading.Thread(target=read_other_thread)
        t.start()
        t.join()
        assert not errors
        # 另一个线程看不到 chain_a 的记录
        assert results["other"] == 0
        # 当前线程自己的记录不受影响
        assert summary()["total_input"] == 100
