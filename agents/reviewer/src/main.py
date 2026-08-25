"""质量评审员 Agent (Reviewer) — 多维度评分+改进建议."""

import json
import re as _re
from langchain_core.messages import HumanMessage, SystemMessage
from loguru import logger

from utils.llm_factory import reviewer_llm  # reviewer uses moderate temp + streaming
from utils.review import save, save_prompt, save_response
from utils.prompt_loader import load_skill
from utils.token_tracker import add_from_response
from utils.health import note


REVIEWER_SYSTEM_PROMPT = load_skill(__file__, "system")


def _repair_json(raw: str) -> str:
    raw = _re.sub(r",(\s*[}\]])", r"\1", raw)
    raw = _re.sub(r'"(\w+)":\s*\+(\d+)', r'"\1": \2', raw)
    return raw


def _parse_json(raw: str) -> dict:
    content = raw.strip()
    if content.startswith("```"):
        parts = content.split("```")
        content = parts[1] if len(parts) > 1 else content
        if content.startswith("json"):
            content = content[4:]
    content = content.strip()
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass
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
                    try:
                        return json.loads(_repair_json(content[start:i+1]))
                    except json.JSONDecodeError:
                        pass
                    break
    raise ValueError(f"Reviewer JSON parse failed. Start: {content[:200]}")


def _format_score_card(result: dict) -> str:
    """Pretty-print the score card for the review output."""
    lines = ["=" * 60, "  QUALITY REVIEW SCORECARD", "=" * 60, ""]
    lines.append(f"  Overall: {result.get('overall_score', '?')}/10 — {result.get('verdict', '?').upper()}")
    lines.append("")

    scores = result.get("scores", {})
    dim_names = {
        "question_design": "题目设计",
        "copy_commercial": "文案商业价值",
        "analysis_richness": "分析内容丰富度",
        "personality_accuracy": "人格映射",
        "visual_style": "视觉风格",
        "overall_commercial": "整体商业价值",
    }
    for key, cn in dim_names.items():
        s = scores.get(key, {})
        sc = int(s.get("score", 0))
        bar = "█" * sc + "░" * (10 - sc)
        lines.append(f"  {cn:12s}  [{bar}] {s.get('score', '?')}/10 — {s.get('verdict', '?')}")
        if s.get("strengths"):
            lines.append(f"      Strengths:  {s['strengths'][:100]}")
        if s.get("weaknesses"):
            lines.append(f"      Weaknesses: {s['weaknesses'][:100]}")

    lines.append("")
    lines.append("  Top 3 Improvements:")
    for i, imp in enumerate(result.get("top_3_improvements", []), 1):
        lines.append(f"    {i}. {imp}")

    lines.append("")
    lines.append(f"  Summary: {result.get('summary', '')}")
    lines.append("")
    lines.append("=" * 60)
    return "\n".join(lines)


def reviewer_node(state: dict) -> dict:
    """LangGraph node: quality review — scores output + suggests improvements.

    Part of the Evaluator-Optimizer pattern: when score < 6, passes fixes_needed
    back to generator for targeted redo.
    """
    llm = reviewer_llm()  # moderate — objective but insightful

    # Track review retry count for the feedback loop
    current_retries = state.get("review_retry_count", 0)

    # Gather all output for review
    questions_json = state.get("questions_json", {})
    questions = questions_json.get("questions", [])
    copy_text = state.get("packaging_text", "")
    generated_html = state.get("generated_html", "")
    topic = state.get("selected_topic", "unknown")

    # Build review payload — sample key content to avoid token overflow
    sample_qs = questions[:3] + questions[-2:] if len(questions) > 5 else questions

    review_payload = f"""## 测试题产品评审

### 选题
{topic}

### 题目抽样（共{len(questions)}题，展示首3+尾2）
{json.dumps(sample_qs, ensure_ascii=False, indent=2)[:5000]}

### 种草文案
{copy_text[:2000]}

### HTML长度
{len(generated_html)} 字符

### 6维定义
{json.dumps(state.get('dimension_defs', []), ensure_ascii=False, indent=2)[:2000]}

请对以上内容进行6维评分。
"""

    logger.info(f"Reviewer: evaluating {len(questions)} questions + copy + HTML")

    try:
        response = llm.invoke([
            SystemMessage(content=REVIEWER_SYSTEM_PROMPT),
            HumanMessage(content=review_payload),
        ])
        add_from_response("reviewer", response)
        save_prompt("reviewer", REVIEWER_SYSTEM_PROMPT + "\n\n" + review_payload)
        save_response("reviewer", response.content)

        result = _parse_json(response.content)

    except Exception as e:
        logger.warning(f"Reviewer parse failed: {e}, using fallback")
        note("reviewer", "llm_parse_failed", str(e)[:200])
        result = {
            "overall_score": 6.0,
            "verdict": "revise",
            "scores": {},
            "top_3_improvements": [
                "评审JSON解析异常，请查看_reponse.txt原始回复",
            ],
            "summary": f"解析失败: {str(e)[:100]}",
        }

    # Save structured results
    save("reviewer", "scorecard.json", result)
    scorecard_text = _format_score_card(result)
    save("reviewer", "scorecard.txt", scorecard_text)

    score = result.get("overall_score", 0)
    verdict = result.get("verdict", "")
    fixes = result.get("fixes_needed", [])

    # Evaluator-Optimizer: if score < 6, increment retry counter and pass fixes
    if score < 6 and verdict != "approve":
        next_retries = current_retries + 1
        if fixes:
            logger.info(f"Reviewer: score {score}/10 < 6 → {len(fixes)} fixes for generator (retry {next_retries}/2)")
        else:
            logger.info(f"Reviewer: score {score}/10 < 6 but no structured fixes → will regenerate with generic feedback")
            fixes = [{
                "section": "all",
                "issue": f"整体评分{score}/10，top issues: {'; '.join(result.get('top_3_improvements', ['质量不足']))}",
                "action": "请根据评审反馈重新生成，注意提高质量",
            }]
    else:
        next_retries = current_retries  # don't increment if passing

    logger.info(f"Reviewer: overall={score}/10, verdict={verdict}")
    # Scorecard saved to output/NN/reviewer/scorecard.txt — view there

    return {
        "review_score": score,
        "review_verdict": verdict,
        "review_retry_count": next_retries,
        "review_fixes_needed": fixes,
    }
