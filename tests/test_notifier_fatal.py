"""Tests for utils.notifier.format_fatal_message — pure fatal-alert formatting."""

from utils.notifier import format_fatal_message


def _raise_error():
    raise ValueError("模拟失败" * 50)  # 超长信息,验证截断


def test_contains_stage_type_and_info():
    try:
        _raise_error()
    except Exception as e:
        msg = format_fatal_message("daily_workflow", e)
    assert "daily_workflow" in msg
    assert "ValueError" in msg
    assert "模拟失败" in msg
    assert len(msg) < 1500  # 长信息被截断


def test_handles_exception_without_traceback():
    err = ValueError("裸异常")
    msg = format_fatal_message("test_stage", err)
    assert "test_stage" in msg
    assert "ValueError" in msg
    assert "裸异常" in msg
