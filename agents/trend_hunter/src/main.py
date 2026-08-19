"""热点嗅探 Agent (Trend Hunter) — 爆款结构分析."""

import json, re as _re
from langchain_core.messages import HumanMessage, SystemMessage
from loguru import logger

from utils.llm_factory import hunter_llm
from utils.review import save, save_prompt, save_response
from utils.token_tracker import add_from_response
from utils.prompt_loader import load_skill


HUNTER_SYSTEM_PROMPT = load_skill(__file__, "system")


def _repair_json(raw: str) -> str:
    raw = _re.sub(r",(\s*[}\]])", r"\1", raw)
    raw = _re.sub(r'"(\w+)":\s*\+(\d+)', r'"\1": \2', raw)
    return raw


def _parse_json(raw: str) -> dict:
    content = raw.strip()

    # 1. Try extracting from markdown code block first
    block = _re.search(r'```(?:json)?\s*([\s\S]*?)```', content)
    if block:
        try:
            return json.loads(_repair_json(block.group(1).strip()))
        except json.JSONDecodeError:
            pass

    # 2. Remove ``` fences
    if content.startswith("```"):
        parts = content.split("```")
        content = parts[1] if len(parts) > 1 else content
        if content.startswith("json"):
            content = content[4:]
    content = content.strip()

    # 3. Direct parse
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass

    # 4. With repairs
    try:
        return json.loads(_repair_json(content))
    except json.JSONDecodeError:
        pass

    # 5. Brace-count extraction
    start = content.find("{")
    if start >= 0:
        depth = 0
        for i in range(start, len(content)):
            if content[i] == "{": depth += 1
            elif content[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(_repair_json(content[start:i+1]))
                    except json.JSONDecodeError:
                        pass
                    break

    raise ValueError(f"Parse failed. Start: {content[:200]}")


def trend_hunter_node(state: dict) -> dict:
    """LangGraph node: extract hot pattern formulas from Xiaohongshu trends."""
    llm = hunter_llm()
    topic = state.get("selected_topic", "MBTI性格测试")

    logger.info(f"Trend Hunter: analyzing hot patterns for '{topic}'")

    # 三级回退获取真实搜索数据(缓存→live→None),注入 prompt
    notes = get_search_context(topic)
    save("trend_hunter", "search_context.json", {"topic": topic, "notes": notes or []})

    try:
        response = llm.invoke([
            SystemMessage(content=HUNTER_SYSTEM_PROMPT),
            HumanMessage(content=build_human_message(topic, notes)),
        ])
        add_from_response("trend_hunter", response)
        save_prompt("trend_hunter", HUNTER_SYSTEM_PROMPT + f"\n\nTopic: {topic}")
        save_response("trend_hunter", response.content)
        insights = _parse_json(response.content)
    except Exception as e:
        logger.warning(f"Trend hunter parse failed: {e}, using defaults")
        insights = {
            "title_formulas": ["测测你的______特质"],
            "question_structure": {"typical_count": 50, "options_per_question": 4},
            "visual_style": "莫兰迪配色 + 卡片式布局",
            "selling_hooks": ["深度分析报告 + 人格标签"],
            "hot_keywords": ["性格", "测试", "人格"],
            "summary": "当前选题已有成熟模板，建议在视觉风格上做差异化",
        }

    logger.info(f"Trend Hunter: found {len(insights.get('hot_keywords', []))} hot keywords")
    save("trend_hunter", "insights.json", insights)

    return {"_trend_insights": insights}


import tools.xhs_search as xhs_search


def get_search_context(topic: str, max_results: int = 10) -> list | None:
    """三级回退:缓存(7天内)→实时搜索(成功写缓存)→None(LLM先验兜底)。"""
    cached = xhs_search.read_cache(topic)
    if cached:
        logger.info(f"Trend Hunter: cache hit for '{topic}' ({len(cached)} notes)")
        return cached
    try:
        notes = xhs_search.search_notes(topic, sort="popularity_descending", max_results=max_results)
        notes = xhs_search.filter_notes(notes, top_n=max_results)
        if notes:
            xhs_search.write_cache(topic, notes)
            logger.info(f"Trend Hunter: live search '{topic}' -> {len(notes)} notes (cached)")
            return notes
    except Exception as e:
        logger.warning(f"Trend Hunter: live search failed ({e}) — falling back to LLM prior")
    return None


def format_search_context(notes: list) -> str:
    """格式化搜索结果供 prompt 使用,标注为推测性参考。"""
    if not notes:
        return ""
    lines = ["以下为小红书搜索结果中的标题与点赞数(仅供推测性参考,非官方数据):"]
    for n in notes:
        lines.append(f"- {n['title']} (点赞 {n['likes']})")
    return "\n".join(lines)


def build_human_message(topic: str, notes: list | None) -> str:
    """组装 human message:有真实数据时注入,无则仅用选题。"""
    base = f"请分析小红书上关于「{topic}」类付费测试题的爆款结构公式。注意: 只输出JSON。"
    if notes:
        return f"{base}\n\n{format_search_context(notes)}"
    return base
