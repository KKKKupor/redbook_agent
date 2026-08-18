"""Tests for utils/posting_materials.py — pure message assembly."""

from datetime import datetime

from utils.posting_materials import build_message


def _full_state() -> dict:
    return {
        "selected_topic": "MBTI职场性格测试",
        "packaging_text": "测测你是哪种打工人!",
        "html_url": "https://my-app.vercel.app",
        "scheduled_publish_time": datetime(2026, 8, 18, 21, 7),
        "cover_image_url": "https://my-app.vercel.app/cover.png",
        "result_image_url": "https://my-app.vercel.app/result.png",
        "product_image_url": "https://my-app.vercel.app/product.png",
    }


class TestBuildMessage:
    def test_full_state_includes_all_sections(self):
        msg = build_message(_full_state())
        assert "测测你是哪种打工人!" in msg
        assert "08-18 21:07" in msg
        assert "**商品链接**: https://my-app.vercel.app" in msg
        assert "![封面-起始页](https://my-app.vercel.app/cover.png)" in msg
        assert "![封面-结果页](https://my-app.vercel.app/result.png)" in msg
        assert "![商品主图](https://my-app.vercel.app/product.png)" in msg
        assert "定时发布" in msg  # 操作指引存在

    def test_missing_copy_returns_none(self):
        state = _full_state()
        state["packaging_text"] = "   "
        assert build_message(state) is None

    def test_capture_failure_degrades_with_warning(self):
        state = _full_state()
        state["cover_image_url"] = ""
        state["result_image_url"] = ""
        state["product_image_url"] = ""
        msg = build_message(state)
        assert "封面图生成失败" in msg
        assert "![封面" not in msg

    def test_deploy_failure_degrades_with_warning(self):
        state = _full_state()
        state["html_url"] = r"output\deploy\latest\index.html"
        state["cover_image_url"] = ""
        state["result_image_url"] = ""
        state["product_image_url"] = ""
        msg = build_message(state)
        assert "部署失败" in msg
        assert "![封面" not in msg

    def test_missing_publish_time_shows_undecided(self):
        state = _full_state()
        state["scheduled_publish_time"] = None
        msg = build_message(state)
        assert "未定" in msg
