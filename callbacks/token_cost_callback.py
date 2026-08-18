"""
Token cost callback handler.

Tracks input/output token consumption per graph node,
enabling fine-grained cost attribution in the daily report.
"""

from typing import Optional
from langchain_core.callbacks.base import BaseCallbackHandler


class TokenCostCallback(BaseCallbackHandler):
    """Records token usage per node with node label attribution."""

    def __init__(self, node_label: str = "unknown"):
        self.node_label = node_label
        self.input_tokens: int = 0
        self.output_tokens: int = 0

    def on_llm_start(self, serialized, prompts, **kwargs):
        pass

    def on_llm_end(self, response, **kwargs):
        usage = response.llm_output.get("token_usage", {})
        self.input_tokens += usage.get("prompt_tokens", 0)
        self.output_tokens += usage.get("completion_tokens", 0)

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    @property
    def cost_summary(self) -> dict:
        return {
            "node": self.node_label,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
        }
