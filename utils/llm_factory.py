"""
Shared LLM factory — every agent gets its own temperature.

All agents use DeepSeek via the OpenAI-compatible endpoint.
Only the temperature and system prompt differ.
"""

import os
from langchain_openai import ChatOpenAI


def create_llm(
    temperature: float = 0.7,
    max_tokens: int = 4096,
    timeout: int = 120,
    max_retries: int = 3,
) -> ChatOpenAI:
    """Create a ChatOpenAI instance pointing to DeepSeek."""
    return ChatOpenAI(
        model=os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=timeout,
        max_retries=max_retries,
        api_key=os.getenv("DEEPSEEK_API_KEY"),
        base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
    )


# Pre-configured factories per agent role
def navigator_llm() -> ChatOpenAI:
    """领航员: moderate creativity for strategic decisions."""
    return create_llm(temperature=0.7)

def analyst_llm() -> ChatOpenAI:
    """数据分析: low temperature, factual only."""
    return create_llm(temperature=0.2)

def hunter_llm() -> ChatOpenAI:
    """热点嗅探: moderate, pattern extraction."""
    return create_llm(temperature=0.5)

def generator_llm() -> ChatOpenAI:
    """测试题生成: high temperature, maximum creativity, large output."""
    return create_llm(temperature=0.85, max_tokens=16384)

def packager_llm() -> ChatOpenAI:
    """包装: moderate-high, creative copywriting."""
    return create_llm(temperature=0.7, max_tokens=8192)

def auditor_llm() -> ChatOpenAI:
    """审核: very low temperature, strict and consistent."""
    return create_llm(temperature=0.1)

def healer_llm() -> ChatOpenAI:
    """自愈: low temperature, precise code fixes."""
    return create_llm(temperature=0.3)
