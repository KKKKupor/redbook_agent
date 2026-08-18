"""
包装 Agent (Packager) — 风格设计 + 深度分析 + HTML输出 + 文案

职责:
  1. 根据选题生成视觉风格（配色/图标）
  2. 生成6维深度分析文案（每维200-300字，含社群归属感）
  3. 16+人格映射
  4. 渲染起始页→逐题→结果的完整HTML
  5. 小红书种草文案
"""

import json
import re as _re
from pathlib import Path
from langchain_core.messages import HumanMessage, SystemMessage
from jinja2 import Template
from loguru import logger

from utils.llm_factory import packager_llm
from utils.review import save, save_prompt, save_response
from utils.prompt_loader import load_skill
from utils.token_tracker import add_from_response


STYLE_PROMPT = load_skill(__file__, "style")
ANALYSIS_PROMPT = load_skill(__file__, "analysis")
COPY_PROMPT = load_skill(__file__, "copy")
PERSONALITY_PROMPT = load_skill(__file__, "personality")

FALLBACK_COPY = "测测你的隐藏人格！#性格测试 #MBTI"


# ═══ JSON repair (same logic as generator) ═══

def _repair_json(raw: str) -> str:
    """Fix common LLM JSON issues: trailing commas, + prefix on numbers."""
    raw = _re.sub(r",(\s*[}\]])", r"\1", raw)
    raw = _re.sub(r'"(\w+)":\s*\+(\d+)', r'"\1": \2', raw)
    return raw


def _parse_json(raw: str) -> dict:
    """Robust JSON extraction from LLM output."""
    content = raw.strip()
    if content.startswith("```"):
        parts = content.split("```")
        content = parts[1] if len(parts) > 1 else content
        if content.startswith("json"):
            content = content[4:]
    content = content.strip()

    # Direct
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass

    # With repairs
    try:
        return json.loads(_repair_json(content))
    except json.JSONDecodeError:
        pass

    # Brace-count extraction
    start = content.find("{")
    if start >= 0:
        depth = 0
        for i in range(start, len(content)):
            if content[i] == "{":
                depth += 1
            elif content[i] == "}":
                depth -= 1
                if depth == 0:
                    extracted = content[start:i+1]
                    try:
                        return json.loads(_repair_json(extracted))
                    except json.JSONDecodeError:
                        pass
                    break

    raise ValueError(f"JSON parse failed. First 200 chars: {content[:200]}")


# ═══ Generation functions ═══

def _gen_style(topic: str, llm) -> dict:
    prompt = STYLE_PROMPT.replace("{topic}", topic)
    try:
        resp = llm.invoke([HumanMessage(content=prompt)])
        add_from_response("packager_style", resp)
        save_prompt("packager", prompt + "\n\n---\n\n" + resp.content)
        return _parse_json(resp.content)
    except Exception as e:
        logger.warning(f"Style gen failed: {e}")
        return {
            "accent_color": "#6c5ce7", "accent_light": "#a29bfe",
            "accent_glass": "rgba(108,92,231,0.12)", "icon_emoji": "🧠",
            "tagline": "揭开你性格的隐藏面", "theme": "light", "mood": "专业",
        }


def _gen_analysis(topic: str, dimensions: list, llm) -> list:
    """Generate per-dimension analysis — one LLM call per dimension for equal quality."""
    results = []
    for dim in dimensions:
        dim_prompt = (
            f"为测试题「{topic}」的维度「{dim['name']}」写深度分析。\n\n"
            f"高分端描述: {dim.get('high_label','高')}，低分端描述: {dim.get('low_label','低')}\n\n"
            f"要求:\n"
            f"1. 三个小节: 🔍核心特质、⚠️潜在盲点、💡专属建议\n"
            f"2. 每小节恰好80-120字，三个小节总字数240-360字,如果任何小节不足80字或超过120字，你的回答视为不合格。\n"
            f"3. 用第二人称\"你\"，具体场景，有洞察力\n"
            f"4. 自然融入社群归属感\n\n"
            f"只输出JSON: {{\"dim_id\":\"{dim['id']}\",\"核心特质\":\"...\",\"潜在盲点\":\"...\",\"专属建议\":\"...\"}}"
        )
        try:
            resp = llm.invoke([HumanMessage(content=dim_prompt)])
            add_from_response("packager_analysis", resp)
            result = _parse_json(resp.content)
            result["dim_id"] = dim["id"]  # ensure correct
            results.append(result)
            logger.debug(f"Analysis: {dim['id']} ({sum(len(result.get(k,'')) for k in ['核心特质','潜在盲点','专属建议'])} chars)")
        except Exception as e:
            logger.warning(f"Analysis gen failed for {dim['id']}: {e}")
            results.append({
                "dim_id": dim["id"],
                "核心特质": f"你在{dim['name']}方面表现突出。这种特质让你在相关场景中游刃有余，但也带来独特的挑战。",
                "潜在盲点": f"过度依赖{dim['name']}的倾向可能在特定情境下成为阻碍。需要保持自我觉察。",
                "专属建议": f"尝试在相反场景中练习，拓展舒适区。记录每次突破带来的感受和成长。",
            })
    return results


def _gen_personality(dimensions: list, topic: str, llm, ip_info: str = "") -> dict:
    dim_names = ", ".join([d.get("name", d.get("id", "?")) for d in dimensions])
    prompt = PERSONALITY_PROMPT.replace("{dimensions}", dim_names).replace("{topic}", topic)
    if ip_info:
        # Override the entire prompt for IP tests — force character names
        prompt = (
            f"这是角色匹配测试: {topic}\n\n"
            f"角色信息: {ip_info}\n\n"
            f"任务: 将{len(dimensions)}个维度的得分映射到具体角色名。\n"
            f"规则:\n"
            f"1. possible_tags必须直接填角色名（如Jett/Phoenix/贤者），禁止填抽象描述（如\"决斗先锋\"）\n"
            f"2. primary_tag填最典型的角色名\n"
            f"3. dominant_dim填最能区分角色的维度ID\n"
            f"4. classification_type填\"descriptive\"\n"
            f"5. community_description解释为什么这个角色匹配你\n\n"
            f"维度定义: {dim_names}\n\n"
            f"只输出JSON: {{\"classification_type\":\"descriptive\",\"primary_tag\":\"角色名\",\"possible_tags\":[\"角色1\",\"角色2\"],\"dominant_dim\":\"D1\",\"community_description\":\"...\"}}"
        )
    try:
        resp = llm.invoke([HumanMessage(content=prompt)])
        add_from_response("packager_personality", resp)
        save_prompt("packager/personality", prompt + "\n\n---\n\n" + resp.content)
        return _parse_json(resp.content)
    except Exception as e:
        logger.warning(f"Personality gen failed: {e}")
        return {
            "personality_tag": "ENFP", "tag_name": "竞选者",
            "community_description": "你属于人群中约8%的ENFP类型——热情、富有创造力、擅长连接看似无关的点子。",
            "rules": {},
        }


def _extract_recommended(raw: str) -> str | None:
    """从【首推版本】块提取完整文案(契约:文案在块首,直到下一个【标记)。

    返回 None 的情况:无【首推版本】块、文案不足20字、或无话题标签
    (质量清单要求文案必含3-5个#标签;无标签说明块内容不是文案)。
    """
    if "【首推版本】" not in raw:
        return None
    rec_block = raw.split("【首推版本】")[-1]

    # 截断到下一个【标记(如【推荐理由】)
    end = _re.search(r"【[^】]+】", rec_block)
    if end:
        rec_block = rec_block[: end.start()]

    lines = [line.strip() for line in rec_block.strip().split("\n") if line.strip()]
    # 去掉首行版本选择器(如 "B. 好奇心驱动型")
    if lines and _re.match(
        r"^[A-F][.、]?\s*(痛点共鸣型|好奇心驱动型|挑战/反直觉型|专业背书型|结果剧透型|社交互动型)$",
        lines[0],
    ):
        lines = lines[1:]

    copy = "\n".join(lines).strip()
    if len(copy) >= 20 and "#" in copy:
        return copy
    return None


def _gen_copy(state: dict, llm) -> str:
    prompt = (COPY_PROMPT
        .replace("{title}", state.get("selected_topic", "性格测试"))
        .replace("{question_count}", str(state.get("target_question_count", 50)))
        .replace("{price}", str(state.get("suggested_price", 3.99))))
    try:
        resp = llm.invoke([HumanMessage(content=prompt)])
        add_from_response("packager_copy", resp)
        save_prompt("packager/copy", prompt + "\n\n---\n\n" + resp.content)
        raw = resp.content.strip()

        # 契约:【首推版本】=完整文案,【推荐理由】=理由(见 skills/copy.md 输出格式)
        if "【首推版本】" in raw:
            recommended = _extract_recommended(raw)
            if recommended:
                logger.info("Packager: extracted recommended copy variant")
                return recommended
            logger.warning("Packager: 首推版本 block invalid (no copy/tags) — using fallback copy")
            return FALLBACK_COPY

        # Fallback: old single-variant format, return as-is
        return raw
    except Exception:
        return FALLBACK_COPY


# ═══ Main node ═══

def packager_node(state: dict) -> dict:
    llm = packager_llm()
    topic = state.get("selected_topic", "MBTI职场性格测试")
    dimensions = state.get("dimension_defs", [])
    questions_json = state.get("questions_json", {})
    questions = questions_json.get("questions", [])

    # 1. Style
    logger.info("Packager: style...")
    style = _gen_style(topic, llm)
    save("packager", "style.json", style)

    # 2. Rich analysis
    logger.info("Packager: analysis...")
    analysis = _gen_analysis(topic, dimensions, llm)
    save("packager", "analysis.json", analysis)

    # 3. Personality
    logger.info("Packager: personality...")
    # IP info for character-matching tests
    ip_info = state.get("_ip_info", "")
    personality = _gen_personality(dimensions, topic, llm, ip_info)
    save("packager", "personality.json", personality)

    # 4. Copywriting — forbidden words handled at prompt level (copy.md)
    logger.info("Packager: copy...")
    copy_text = _gen_copy(state, llm)
    save("packager", "copy.txt", copy_text)

    # 5. Render HTML
    logger.info("Packager: rendering...")
    template_path = Path(__file__).resolve().parent.parent.parent.parent / "templates" / "test_template.html"
    template = Template(template_path.read_text(encoding="utf-8"))

    # Compute max_score for JS normalization: round(100 / question_count)
    question_count = len(questions) or 1
    max_score = max(1, round(100 / question_count))

    html = template.render(
        title=topic,
        icon_emoji=style.get("icon_emoji", "🧠"),
        tagline=style.get("tagline", ""),
        accent_color=style.get("accent_color", "#6c5ce7"),
        accent_light=style.get("accent_light", "#a29bfe"),
        accent_glass=style.get("accent_glass", "rgba(108,92,231,0.12)"),
        theme=style.get("theme", "light"),
        default_personality=personality.get("personality_tag", "ENFP"),
        questions_json=json.dumps(questions, ensure_ascii=False),
        dimension_defs=json.dumps(dimensions, ensure_ascii=False),
        personality_mapping=json.dumps(personality, ensure_ascii=False),
        theme_config=json.dumps(style, ensure_ascii=False),
        analysis_data=json.dumps(analysis, ensure_ascii=False),
        max_score_per_question=max_score,
    )

    # 6. Save
    output_dir = Path(__file__).resolve().parent.parent.parent / "output"
    output_dir.mkdir(exist_ok=True)
    safe_name = topic.replace("/", "_").replace(" ", "_")
    filename = f"test_{safe_name}.html"
    (output_dir / filename).write_text(html, encoding="utf-8")
    save("packager", "test.html", html)
    logger.info(f"Packager: {len(html)} chars → output/{filename}")

    return {
        "generated_html": html,
        "packaging_text": copy_text,
        "html_url": f"output/{filename}",
        "_analysis_data": analysis,
        "_personality_data": personality,
    }
