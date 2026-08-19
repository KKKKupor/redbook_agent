"""
Multi-channel notification dispatcher.

Supports: Feishu, DingTalk, WeCom, ServerChan.
Configured via NOTIFICATION_CHANNELS env var (comma-separated).
"""

import os
import traceback
from datetime import datetime
import httpx
from loguru import logger


class Notifier:
    """Sends formatted messages to configured notification channels."""

    def __init__(self):
        self.channels = os.getenv("NOTIFICATION_CHANNELS", "").split(",")

    def send(self, title: str, content: str, level: str = "info"):
        """Dispatch to all configured channels."""
        for ch in self.channels:
            ch = ch.strip()
            if not ch:
                continue
            method = getattr(self, f"_send_{ch}", None)
            if method:
                try:
                    method(title, content, level)
                except Exception as e:
                    logger.error(f"Failed to send to {ch}: {e}")

    def _send_feishu(self, title: str, content: str, level: str):
        url = os.getenv("FEISHU_WEBHOOK_URL", "")
        if not url:
            return
        payload = {
            "msg_type": "interactive",
            "card": {
                "header": {"title": {"tag": "plain_text", "content": title}},
                "elements": [{"tag": "markdown", "content": content}],
            },
        }
        httpx.post(url, json=payload, timeout=10)

    def _send_dingtalk(self, title: str, content: str, level: str):
        self._send_dingding(title, content, level)

    def _send_dingding(self, title: str, content: str, level: str):
        url = os.getenv("DINGTALK_WEBHOOK_URL", "")
        if not url:
            logger.warning("DINGTALK_WEBHOOK_URL not set")
            return
        text = f"## {title}\n\n{content}"
        if len(text) > 4096:
            text = text[:4000] + "\n\n... (truncated)"
        payload = {
            "msgtype": "markdown",
            "markdown": {"title": title[:256], "text": text},
        }
        try:
            resp = httpx.post(url, json=payload, timeout=10)
            logger.info(f"DingTalk response: {resp.status_code} — {resp.text[:200]}")
        except Exception as e:
            logger.error(f"DingTalk send failed: {e}")

    def _send_serverchan(self, title: str, content: str, level: str):
        key = os.getenv("SERVERCHAN_SEND_KEY", "")
        if not key:
            return
        url = f"https://sctapi.ftqq.com/{key}.send"
        httpx.post(url, data={"title": title, "desp": content}, timeout=10)


# Singleton
notifier = Notifier()


def format_fatal_message(stage: str, error: BaseException) -> str:
    """组装致命错误告警消息体(纯函数,便于单测)。"""
    tb_lines = traceback.format_exception(type(error), error, error.__traceback__)
    tail = "".join(tb_lines).strip().split("\n")[-5:]
    msg = str(error)[:300]
    return (
        f"⏰ 时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"📍 阶段: {stage}\n"
        f"❌ 错误类型: {type(error).__name__}\n"
        f"📝 信息: {msg or '(无信息)'}\n"
        f"```\n{''.join(tail)[:800]}\n```\n"
        f"👉 请查看 logs/app.log;环境类错误(网络/限流)恢复后重跑,代码类错误修复后重启调度。"
    )
