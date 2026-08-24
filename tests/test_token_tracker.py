"""Tests for utils.token_tracker.add_from_response — streaming responses
expose usage in usage_metadata instead of response_metadata.token_usage."""

from utils.token_tracker import add_from_response, reset, summary


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
