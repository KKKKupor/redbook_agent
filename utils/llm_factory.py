"""
Shared LLM factory — every agent gets its own temperature.

All agents use DeepSeek via the OpenAI-compatible endpoint.
Only the temperature and system prompt differ.
"""

import os
from typing import Optional

from langchain_core.callbacks import BaseCallbackHandler
from langchain_openai import ChatOpenAI


class _TokenStreamHandler(BaseCallbackHandler):
    """把 LLM 输出 token 转发到 stream_bus(带 agent 标识)。"""

    def __init__(self, agent_key: str):
        self.agent_key = agent_key

    def on_llm_new_token(self, token: str, **kwargs) -> None:
        from utils.stream_bus import emit
        emit({"event": "token", "agent": self.agent_key, "text": token})


def create_llm(
    temperature: float = 0.7,
    max_tokens: int = 4096,
    timeout: int = 120,
    max_retries: int = 3,
    agent_key: Optional[str] = None,
) -> ChatOpenAI:
    """Create a ChatOpenAI instance pointing to DeepSeek.

    agent_key 非 None 时开启 streaming 并挂 _TokenStreamHandler,
    把 token 实时推到 stream_bus(无消费者时 no-op)。
    """
    kwargs = dict(
        model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=timeout,
        max_retries=max_retries,
        api_key=os.getenv("DEEPSEEK_API_KEY"),
        base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
    )
    if agent_key is not None:
        kwargs["streaming"] = True
        kwargs["callbacks"] = [_TokenStreamHandler(agent_key)]
    return ChatOpenAI(**kwargs)


# Pre-configured factories per agent role
def navigator_llm() -> ChatOpenAI:
    """领航员: moderate creativity for strategic decisions."""
    return create_llm(temperature=0.7, agent_key="navigator")

def analyst_llm() -> ChatOpenAI:
    """数据分析: low temperature, factual only."""
    return create_llm(temperature=0.2, agent_key="data_analyst")

def hunter_llm() -> ChatOpenAI:
    """热点嗅探: moderate, pattern extraction."""
    return create_llm(temperature=0.5, agent_key="trend_hunter")

def generator_llm() -> ChatOpenAI:
    """测试题生成: high temperature, maximum creativity, large output."""
    return create_llm(temperature=0.85, max_tokens=16384, agent_key="generator")

def packager_llm() -> ChatOpenAI:
    """包装: moderate-high, creative copywriting."""
    return create_llm(temperature=0.7, max_tokens=8192, agent_key="packager")

def auditor_llm() -> ChatOpenAI:
    """审核: very low temperature, strict and consistent."""
    return create_llm(temperature=0.1, agent_key="auditor")

def healer_llm() -> ChatOpenAI:
    """自愈: low temperature, precise code fixes."""
    return create_llm(temperature=0.3, agent_key="self_healer")
