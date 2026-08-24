"""
Global token cost tracker. Each agent calls add() after LLM invocation.

DeepSeek pricing: input ¥1.00/1M tokens, output ¥2.00/1M tokens
(approx — adjust if actual pricing differs)
"""

from loguru import logger

# Pricing per 1M tokens (DeepSeek)
PRICE_INPUT_PER_1M = 3.00   # yuan
PRICE_OUTPUT_PER_1M = 6.00  # yuan

_breakdown = []  # list of {"agent": str, "input": int, "output": int, "cost": float}


def add(agent: str, input_tokens: int, output_tokens: int):
    """Record token usage for one agent call."""
    cost = (input_tokens / 1_000_000) * PRICE_INPUT_PER_1M + (output_tokens / 1_000_000) * PRICE_OUTPUT_PER_1M
    _breakdown.append({
        "agent": agent,
        "input": input_tokens,
        "output": output_tokens,
        "total": input_tokens + output_tokens,
        "cost": round(cost, 6),
    })
    logger.debug(f"[TOKEN] {agent}: {input_tokens}in + {output_tokens}out = ¥{cost:.4f}")


def add_from_response(agent: str, response):
    """Extract token usage from a langchain_openai response and record it."""
    try:
        usage = response.response_metadata.get("token_usage", {})
        inp = usage.get("prompt_tokens", 0)
        out = usage.get("completion_tokens", 0)
        if not (inp or out):
            # streaming=True 时 usage 在 usage_metadata 而非 response_metadata.token_usage
            um = response.usage_metadata or {}
            inp = um.get("input_tokens", 0)
            out = um.get("output_tokens", 0)
        if inp or out:
            add(agent, inp, out)
    except Exception:
        pass


def summary() -> dict:
    """Return cost summary."""
    total_input = sum(b["input"] for b in _breakdown)
    total_output = sum(b["output"] for b in _breakdown)
    total_cost = sum(b["cost"] for b in _breakdown)
    return {
        "breakdown": _breakdown,
        "total_input": total_input,
        "total_output": total_output,
        "total_tokens": total_input + total_output,
        "total_cost": round(total_cost, 4),
    }


def reset():
    _breakdown.clear()
