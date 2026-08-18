"""
监控与推送 Agent (Monitor) — V1.0 桩

职责:
  1. 汇总各节点Token消耗
  2. 成本核算（人民币）
  3. 生成日报推送到钉钉/飞书

Status: V1.0 — 基础成本核算，推送由 main.py 中 logger 代替。
"""

from loguru import logger
from utils.notifier import notifier


def monitor_node(state: dict) -> dict:
    """
    Cost summary + notification dispatch.
    """
    total_cost = state.get("total_token_cost", 0.0)
    breakdown = state.get("cost_breakdown", {})

    logger.info(f"Monitor: total token cost = ¥{total_cost:.4f}")

    # Build simple daily report
    report = f"""📊 小红书Agent组日报

📅 选题: {state.get('selected_topic', 'N/A')}
📝 题量: {state.get('target_question_count', 0)}题
💰 Token成本: ¥{total_cost:.4f}
🔗 文件: {state.get('html_url', 'N/A')}
✅ 审核: {state.get('audit_status', 'N/A')}
"""

    # Push to configured channels
    try:
        notifier.send(
            title="小红书Agent组日报",
            content=report,
            level="info",
        )
    except Exception as e:
        logger.error(f"Notification failed: {e}")

    return {
        "total_token_cost": total_cost,
        "cost_breakdown": breakdown,
    }
