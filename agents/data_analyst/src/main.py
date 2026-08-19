"""
数据分析 Agent (Data Analyst) — 商业智能参谋

职责:
  绑定5个销售数据Tools，供领航员调用进行数据驱动的决策。
  本Agent本身不做决策，只汇集和分析数据。

  V1.0: 作为被领航员调用的工具节点
"""

from langchain_core.messages import HumanMessage, SystemMessage
from loguru import logger

from utils.llm_factory import analyst_llm
from utils.review import save, save_prompt, save_response
from utils.prompt_loader import load_skill
from utils.token_tracker import add_from_response
from utils.health import note
from tools.sales_tools import (
    get_sales_analytics,
    get_product_rankings,
    get_competitor_trend,
    time_series_forecast,
    get_topic_diversity,
)


ANALYST_SYSTEM_PROMPT = load_skill(__file__, "system")


def data_analyst_node(state: dict) -> dict:
    """
    LangGraph node: 数据汇总。

    Called after navigator decision, before generation.
    Queries all available data tools and produces a summary.

    Args:
        state: AgentState

    Returns:
        Partial state with analysis results
    """
    llm = analyst_llm()

    logger.info("Data Analyst: querying sales tools...")

    # Query all tools
    rankings = get_product_rankings.invoke({"time_range": "7d"})
    diversity = get_topic_diversity.invoke({})

    save("data_analyst", "tool_rankings.json", rankings)
    save("data_analyst", "tool_diversity.json", diversity)

    # Build data report
    data_context = f"""## 店铺排行榜
{rankings}

## 题材分布
{diversity}
"""

    try:
        response = llm.invoke([
            SystemMessage(content=ANALYST_SYSTEM_PROMPT),
            HumanMessage(content=f"请分析以下数据并生成业务复盘报告:\n{data_context}"),
        ])
        add_from_response("data_analyst", response)
        save_prompt("data_analyst", ANALYST_SYSTEM_PROMPT + "\n\n" + data_context)
        save_response("data_analyst", response.content)
        save("data_analyst", "report.txt", response.content)
        logger.info("Data Analyst: report generated")
    except Exception as e:
        logger.warning(f"Data analyst LLM call failed: {e}")
        note("data_analyst", "analytics_failed", str(e)[:200])

    return {
        "_analysis_report": str(response.content) if 'response' in dir() else "N/A",
    }
