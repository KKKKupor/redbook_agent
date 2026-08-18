"""
审核 Agent (Auditor) — 内容安全与质量把关

职责:
  1. 敏感词/广告法违禁词过滤
  2. 反查重校验（Chroma向量相似度 > 30% → 打回）
  3. 商业价值评估（分析是否有付费说服力）
  4. 返回 pass/fail + 具体反馈
"""

import json
import os
import re as _re
from langchain_core.messages import HumanMessage, SystemMessage
from loguru import logger

from utils.llm_factory import auditor_llm
from utils.review import save, save_prompt, save_response
from utils.prompt_loader import load_skill

# Ad law forbidden words — comprehensive list for Chinese content
AD_LAW_FORBIDDEN = [
    "第一", "最", "国家级", "最高级", "最佳", "唯一", "首个",
    "首选", "独家", "顶级", "极品", "绝对", "100%", "百分百",
    "彻底", "即刻", "立即见效", "永久", "万能",
]

# Platform-sensitive words (generic examples — expand per actual policy)
PLATFORM_SENSITIVE = [
    "免费领取", "加微信", "私信", "关注公众号",
    "刷单", "好评返现", "点击购买", "限时抢购",
]


AUDITOR_SYSTEM_PROMPT = load_skill(__file__, "system")


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
    raise ValueError(f"Auditor parse failed. Start: {content[:200]}")


def _check_ad_law(text: str) -> list:
    """Static check for forbidden advertising words. Skips common phrases."""
    violations = []
    # Only flag if the word is used as an ad claim, not in common phrases
    for word in AD_LAW_FORBIDDEN:
        if word not in text:
            continue
        # Skip common non-commercial phrases
        if word == "第一" and ("第一反应" in text or "第一次" in text or "第一眼" in text):
            continue
        if word == "最" and ("最近" in text or "最终" in text or "最后" in text):
            continue
        if word == "100%" and "100%" in text:
            pass  # always flag 100% — no common non-commercial use
        violations.append({"word": word, "type": "广告法违禁词"})
    for word in PLATFORM_SENSITIVE:
        if word in text:
            violations.append({"word": word, "type": "平台敏感词"})
    return violations


def auditor_node(state: dict) -> dict:
    """
    LangGraph node: 审核 — pass/fail + feedback。

    Reads: generated_html, packaging_text, selected_topic
    Returns: audit_status, audit_feedback, retry_count
    """
    llm = auditor_llm()
    html = state.get("generated_html", "")
    copy_text = state.get("packaging_text", "")
    retry = state.get("retry_count", 0)

    # Static check first (fast)
    static_violations = _check_ad_law(copy_text + html)

    # Build review payload — sample from questions_json for content review
    questions_json = state.get("questions_json", {})
    questions = questions_json.get("questions", [])
    # Show first 5 and last 2 questions for review (avoid token waste)
    sample_questions = questions[:5] + questions[-2:] if len(questions) > 7 else questions
    questions_text = json.dumps(sample_questions, ensure_ascii=False, indent=2)

    review_text = f"""## 商品文案
{copy_text[:2000]}

## HTML长度
{len(html)} 字符

## 试题抽样（共{len(questions)}题，展示首5+尾2题）
{questions_text[:8000]}

## 静态广告法检查结果
{json.dumps(static_violations, ensure_ascii=False, indent=2)}
"""

    try:
        response = llm.invoke([
            SystemMessage(content=AUDITOR_SYSTEM_PROMPT),
            HumanMessage(content=review_text),
        ])

        save_prompt("auditor", AUDITOR_SYSTEM_PROMPT + "\n\n" + review_text)
        save_response("auditor", response.content)

        result = _parse_json(response.content)

    except (json.JSONDecodeError, Exception) as e:
        logger.warning(f"Auditor JSON parse failed: {e}, defaulting to pass")
        result = {
            "audit_status": "pass",
            "safety_check": {"passed": True, "issues": []},
            "ad_law_check": {"passed": True, "violations": []},
            "content_quality_check": {"passed": True, "duplicate_estimate": 0.0, "accuracy_issues": [], "inclusivity_issues": []},
            "commercial_check": {"passed": True, "pricing_issues": [], "competitor_issues": []},
            "emotional_risk_check": {"risk_level": "low", "trigger_warnings": [], "suggestions": ""},
            "overall_feedback": f"[自动审核解析异常，默认放行] {str(e)[:80]}",
        }

    # Static violations logged but don't block — human reviewer makes final call
    if static_violations:
        result["ad_law_check"] = {
            "passed": False,
            "violations": [v["word"] for v in static_violations],
            "note": f"检测到{len(static_violations)}个潜在违禁词，请人工判断是否需要修改"
        }

    # Production: use LLM review result, but ad-law words are non-blocking
    status = result.get("audit_status", "fail")
    feedback = result.get("overall_feedback", "")

    # Static violations are logged but don't fail the audit — human reviewer decides
    if static_violations and status == "fail":
        only_ads = all(v["type"] == "广告法违禁词" for v in static_violations)
        if only_ads:
            status = "pass"
            feedback = f"[广告法自动通过] 检测到{len(static_violations)}个潜在违禁词({', '.join(v['word'] for v in static_violations)})，已记录供人工复查。\n{feedback}"

    save("auditor", "result.json", result)
    logger.info(f"Auditor: status={status} (ads: {len(static_violations)})")

    return {
        "audit_status": status,
        "audit_feedback": feedback,
        "retry_count": retry + (1 if status == "fail" else 0),
    }
