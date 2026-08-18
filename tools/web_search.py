"""
Knowledge lookup tool — uses LLM training data as search proxy (no network needed).
China-friendly: avoids blocked search APIs.
"""

from langchain_core.tools import tool
from loguru import logger


@tool
def knowledge_lookup(query: str, context: str = "") -> str:
    """查询LLM训练数据中关于特定主题的知识（相当于离线搜索）。

    用于获取IP作品的详细信息：角色列表、分类体系、特征描述等。
    不需要网络连接，完全基于LLM的知识库。

    Args:
        query: 查询主题，如"哈利波特四大学院及代表角色"
        context: 可选的上下文信息

    Returns:
        空字符串——实际查询结果由Navigator的LLM在上下文中直接生成。
        这个tool是标记性的：它告诉LLM"你需要动用训练数据来回答这个问题"。
    """
    # This tool is a marker — the LLM generates the knowledge from training data
    return f"[KNOWLEDGE_LOOKUP] {query}"


@tool
def web_search(query: str, max_results: int = 5) -> str:
    """搜索网页获取实时信息。优先使用，失败时fallback到knowledge_lookup。

    Args:
        query: 搜索关键词
        max_results: 返回结果数

    Returns:
        搜索结果或fallback提示
    """
    try:
        from duckduckgo_search import DDGS
        results = []
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=max_results):
                results.append(f"【{r.get('title','')}】\n{r.get('body','')}")
        if results:
            return "\n\n".join(results)
    except Exception as e:
        logger.debug(f"Web search unavailable (China network): {str(e)[:80]}")

    # Fallback: tell LLM to use training data
    return f"[离线模式] 请基于你的训练数据回答关于'{query}'的知识。列出该IP的主要角色/分类及其特征。"
