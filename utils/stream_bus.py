"""流式事件总线 — 把各 agent 的 LLM token 流与步骤事件推给当前消费者(如 Web 控制台)。

contextvar 保证同一请求线程内可见;无消费者时 emit 为 no-op(日常调度零影响)。
"""

from contextvars import ContextVar, Token
from typing import Optional

from loguru import logger

_emitter: ContextVar = ContextVar("stream_emitter", default=None)


def emit(event: dict) -> None:
    """向当前 context 的 emitter 发送事件;无 emitter 时静默忽略。"""
    em = _emitter.get()
    if em is None:
        return
    try:
        em.emit(event)
    except Exception as e:
        logger.error(f"stream_bus: emitter 处理事件失败: {e}")


def set_emitter(emitter) -> Token:
    """设置当前 context 的 emitter,返回 reset 用的 Token。"""
    return _emitter.set(emitter)


def reset_emitter(token: Token) -> None:
    """恢复之前的 emitter(通常为 None)。"""
    _emitter.reset(token)
