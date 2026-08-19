"""Tests for utils.health.classify_error."""

import json

from utils.health import classify_error


class TestClassifyError:
    def test_timeout_is_environmental(self):
        assert classify_error(TimeoutError("timed out")) == "environmental"

    def test_connection_is_environmental(self):
        assert classify_error(ConnectionError("connection reset")) == "environmental"

    def test_oserror_is_environmental(self):
        assert classify_error(OSError("no space left on device")) == "environmental"

    def test_message_pattern_is_environmental(self):
        assert classify_error(RuntimeError("429 Too Many Requests")) == "environmental"
        assert classify_error(RuntimeError("dns resolution failed")) == "environmental"

    def test_keyerror_is_code(self):
        assert classify_error(KeyError("missing")) == "code"

    def test_json_decode_is_code(self):
        try:
            json.loads("{bad")
        except Exception as e:
            assert classify_error(e) == "code"

    def test_valueerror_is_code(self):
        assert classify_error(ValueError("Failed to parse JSON")) == "code"

    def test_unknown(self):
        assert classify_error(RuntimeError("something weird")) == "unknown"
