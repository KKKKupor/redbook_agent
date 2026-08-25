"""
领航员 Agent (Navigator) — 商业决策大脑

职责:
  1. 综合数据分析结果，做选题决策（70%利用 / 30%探索）
  2. 题材多样性监控（单一题材>40%强制切换）
  3. 动态调整题量（50-100题，基于完测率）
  4. 定价建议（0.1-15元区间，薄利多销路线）
  5. 发布时间决策（含±30min随机抖动）
"""

import json
import os
import random
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from langchain_core.messages import HumanMessage, SystemMessage
from loguru import logger

from utils.llm_factory import navigator_llm
from utils.review import save, save_prompt, save_response
from utils.prompt_loader import load_skill
from utils.token_tracker import add_from_response
from utils.health import note
from tools.sales_tools import (
    get_product_rankings,
    get_competitor_trend,
    get_topic_diversity,
)


NAVIGATOR_SYSTEM_PROMPT = load_skill(__file__, "system")
REFUSAL_SYSTEM_PROMPT = load_skill(__file__, "refusal")
GATE_SYSTEM_PROMPT = load_skill(__file__, "gate")

GENERATED_FILE = Path(__file__).resolve().parent.parent.parent.parent / "data" / "generated_topics.json"

# Web 入口约束(仅 user_message 非空的 web 场景生效;钉钉/日常调度不传 user_message)
MAX_QUESTIONS = 60
TOKENS_PER_QUESTION = 325  # 实测 15题≈4871 out tokens;仅作拒绝文案素材
_REFUSAL_FALLBACK = "本网页单次最多生成 60 题测试,请减少题量后重试。"


def select_topic(user_topic: str | None, pool: list, generated: set, roll: float) -> dict:
    """选题决策(纯函数):用户选题优先;否则从池中 70/30 轮转且不重复已生成过的选题。

    roll <= 0.7 → exploit(池第一个未生成过的话题);否则 explore(其余随机)。
    池中全部已生成 → 重置历史,从完整池重新开始。
    返回 {"strategy", "topic", "generated"} — generated 为更新后的集合(池选题才记录)。
    """
    if user_topic:
        return {"strategy": "user", "topic": user_topic, "generated": generated}

    remaining = [t for t in pool if t not in generated]
    if not remaining:
        generated = set()
        remaining = list(pool)
        note("navigator", "pool_cycle_reset", "选题池全部已生成过,重置历史重新循环")
    if roll <= 0.7:
        topic = remaining[0]
        strategy = "exploit"
    else:
        topic = random.choice(remaining[1:]) if len(remaining) > 1 else remaining[0]
        strategy = "explore"
    generated = generated | {topic}
    return {"strategy": strategy, "topic": topic, "generated": generated}


def _load_generated() -> set:
    """加载已生成选题集合(generated_topics.json);缺失/损坏/非列表 → 空集。"""
    try:
        if GENERATED_FILE.exists():
            data = json.loads(GENERATED_FILE.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return set(data)
    except Exception:
        pass
    return set()


def _save_generated(generated: set) -> None:
    """持久化已生成选题集合(仅池选题记录;data/ 不提交 Git)。失败仅告警,不阻断流程。"""
    try:
        GENERATED_FILE.parent.mkdir(parents=True, exist_ok=True)
        GENERATED_FILE.write_text(json.dumps(sorted(generated), ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        logger.warning(f"navigator: 保存 generated_topics 失败: {e}")


def _calculate_jitter() -> int:
    """Generate random jitter in ±PUBLISH_JITTER_MINUTES range."""
    max_jitter = int(os.getenv("PUBLISH_JITTER_MINUTES", "30"))
    return random.randint(-max_jitter, max_jitter)


def _compute_diversity_ok(topic: str, diversity: dict) -> bool:
    """Check if the selected topic keeps diversity within 40% limit."""
    for t, pct in diversity.items():
        pct_val = float(pct.replace("%", ""))
        if t == topic and pct_val > 35:  # warning zone
            logger.warning(f"Topic '{topic}' at {pct_val}% — approaching 40% threshold")
        if pct_val > 40:
            return False
    return True


def _request_refusal_copy(req_count: int, user_message: str) -> str:
    """题量超限时让 LLM 生成拒绝文案(流式可见);失败用模板兜底,拒绝结论不变。"""
    llm = navigator_llm()
    est_tokens = req_count * TOKENS_PER_QUESTION
    human = (
        f"用户请求: {user_message or '(未提供)'}\n"
        f"请求题数: {req_count} 题\n"
        f"本网页上限: {MAX_QUESTIONS} 题\n"
        f"按请求题数估算将消耗约 {est_tokens} 输出 token,超出本网页预算。\n"
        "请生成礼貌的拒绝文案:说明单次上限 60 题并建议减少题量,"
        '严格输出 JSON: {"reply": "..."}'
    )
    try:
        resp = llm.invoke([SystemMessage(content=REFUSAL_SYSTEM_PROMPT), HumanMessage(content=human)])
        add_from_response("navigator", resp)
        content = resp.content.strip()
        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
        try:
            reply = str(json.loads(content).get("reply", "")).strip()
        except json.JSONDecodeError:
            reply = content.strip()
        return reply or _REFUSAL_FALLBACK
    except Exception as e:
        logger.warning(f"Navigator refusal copy failed, using fallback: {e}")
        return _REFUSAL_FALLBACK


def navigator_node(state: dict) -> dict:
    """
    LangGraph node: 领航员决策。

    Called at step 2 of the daily workflow.
    Reads sales data from state, outputs decisions.

    Args:
        state: AgentState dict

    Returns:
        Partial state dict with decision fields
    """
    user_message = (state.get("user_message") or "").strip()
    entry_web = bool(state.get("entry_web"))

    llm = navigator_llm()

    # Gather data for the decision (returns empty on first run — no DB)
    rankings = get_product_rankings.invoke({"time_range": "7d"})
    diversity = get_topic_diversity.invoke({})
    # If no data, still proceed with real topic pool (below)

    # ═══ Topic pool — loaded from scraped data (falls back to hardcoded) ═══
    POOL_FILE = Path(__file__).resolve().parent.parent.parent.parent / "data" / "topic_pool.json"
    REAL_TOPIC_POOL = [
        "人格阴影测试", "童年创伤程度测试", "恋爱人格匹配测试",
        "危险人格类型测试", "职场性格测试", "MBTI深度解析",
        "动物塑测试", "去性别化人格测试", "心理压力指数测试",
        "情商测试", "社交人格测试", "抑郁倾向筛查",
    ]
    pool_loaded = False
    if POOL_FILE.exists():
        try:
            pool_data = json.loads(POOL_FILE.read_text(encoding="utf-8"))
            scraped = pool_data.get("topics", [])
            if len(scraped) >= 6:
                REAL_TOPIC_POOL = scraped
                pool_loaded = True
                logger.debug(f"Loaded {len(scraped)} topics from {POOL_FILE}")
        except Exception:
            pass
    if not pool_loaded:
        note("navigator", "topic_pool_hardcoded", "data/topic_pool.json 缺失或不足,使用硬编码话题池")

    requested_topic = ""
    requested_count = 15

    # ═══ 入口判定 + 用户意图解析(LLM 判读,句式不限)—— user_message 非空时生效 ═══
    if user_message:
        try:
            gate_resp = llm.invoke([
                SystemMessage(content=GATE_SYSTEM_PROMPT),
                HumanMessage(content=user_message),
            ])
            add_from_response("navigator", gate_resp)
            save_prompt("navigator", GATE_SYSTEM_PROMPT + "\n\n" + user_message)
            save_response("navigator", gate_resp.content)
            gate_content = gate_resp.content.strip()
            if gate_content.startswith("```"):
                gate_content = gate_content.split("```")[1]
                if gate_content.startswith("json"):
                    gate_content = gate_content[4:]
            gate = json.loads(gate_content)
        except Exception as e:
            logger.warning(f"Navigator gate parse failed: {e}, assuming related input")
            gate = {}

        if gate.get("rejected"):
            return {"rejected": True, "reply": str(gate.get("reply") or _REFUSAL_FALLBACK).strip()}

        requested_topic = (gate.get("user_requested_topic") or "").strip()
        if requested_topic and len(requested_topic) <= 2:
            requested_topic = ""
        try:
            requested_count = int(gate.get("user_requested_count") or 15)
        except (TypeError, ValueError):
            requested_count = 15

        # 题量超限(仅网页入口):LLM 生成拒绝文案,零副作用
        if entry_web and requested_count > MAX_QUESTIONS:
            reply = _request_refusal_copy(requested_count, user_message)
            return {"rejected": True, "reply": reply}

    # ═══ 选题决策: 用户选题优先;否则池 70/30 轮转且不重复已生成选题 ═══
    user_topic = requested_topic or (state.get("selected_topic") or "").strip() or None
    sel = select_topic(user_topic, REAL_TOPIC_POOL, _load_generated(), random.random())
    if sel["strategy"] != "user":
        _save_generated(sel["generated"])
    selected_topic_name = sel["topic"]
    strategy = sel["strategy"]

    logger.info(f"Topic selection: strategy={strategy}, topic={selected_topic_name}")

    # Build context for LLM (creative parts only: dimensions, pricing, reasoning)
    context = f"""## 已选定选题（不用再选，已由系统决策）
选题: {selected_topic_name}
决策策略: {strategy}

## 当前商品榜排名（供定价参考）
{json.dumps(rankings, ensure_ascii=False, indent=2)}

## 题材多样性分布
{json.dumps(diversity, ensure_ascii=False, indent=2)}

## 你的任务
基于已选定的选题「{selected_topic_name}」:
1. 定义多个评分维度（根据选题特点自定义维度名称和描述）
2. 给出定价建议（薄利多销，0.1-15元，默认2-6元）
3. 给出发布时间建议
4. 写决策依据摘要

注意: 不要在JSON中更改selected_topic——使用给定的「{selected_topic_name}」。
"""

    try:
        response = llm.invoke([
            SystemMessage(content=NAVIGATOR_SYSTEM_PROMPT),
            HumanMessage(content=context),
        ])

        add_from_response("navigator", response)
        save_prompt("navigator", NAVIGATOR_SYSTEM_PROMPT + "\n\n" + context)
        save_response("navigator", response.content)

        # Parse JSON from response
        content = response.content.strip()
        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
        decision = json.loads(content)

    except (json.JSONDecodeError, Exception) as e:
        logger.error(f"Navigator JSON parse failed: {e}")
        note("navigator", "llm_parse_failed", str(e)[:200])
        # Fallback: safe defaults
        decision = {
            "strategy": "exploit",
            "selected_topic": "MBTI职场",
            "topic_reasoning": "JSON解析失败，使用默认选题",
            "dimension_defs": [
                {"id": "D1", "name": "维度一", "high_label": "高", "low_label": "低"},
            ],
            "target_question_count": 10,
            "suggested_price": 1.99,
            "pricing_reasoning": "薄利多销——市场主流0.99-1.99，新品类低价切入",
            "best_publish_hour": 21,
            "jitter_minutes": 15,
            "scheduled_publish_time": (datetime.now() + timedelta(days=1)).replace(hour=21, minute=15).isoformat(),
            "decision_reasoning": "JSON解析失败，使用安全默认值",
        }

    # Web 入口判定:LLM 判定输入与测试题无关 → 早退拒绝(不进入 jitter/选题保存)
    if isinstance(decision, dict) and decision.get("rejected"):
        return {"rejected": True, "reply": str(decision.get("reply") or _REFUSAL_FALLBACK).strip()}

    # 语义判读的题量覆盖:用户明确说了题数(含中文数字)则以此为准
    if user_message:
        decision["target_question_count"] = requested_count

    # Apply jitter
    jitter = _calculate_jitter()
    best_hour = decision.get("best_publish_hour", 21)
    scheduled_time = datetime.now().replace(
        hour=best_hour, minute=0, second=0, microsecond=0
    ) + timedelta(minutes=jitter)
    # If best_hour is in the past for today, schedule tomorrow
    if scheduled_time < datetime.now():
        scheduled_time += timedelta(days=1)

    # Production: topic enforced by code (avoids MBTI bias); pricing/question_count by LLM
    decision["selected_topic"] = selected_topic_name
    decision["strategy"] = strategy
    decision["jitter_minutes"] = jitter
    decision["scheduled_publish_time"] = scheduled_time.isoformat()

    logger.info(
        f"Navigator decision: topic={decision['selected_topic']}, "
        f"questions={decision['target_question_count']}, "
        f"price=¥{decision['suggested_price']}, "
        f"publish={scheduled_time.strftime('%Y-%m-%d %H:%M')} "
        f"(jitter={jitter:+d}min)"
    )

    # Review output
    save("navigator", "decision.json", decision)
    save("navigator", "input_rankings.json", rankings)
    save("navigator", "input_diversity.json", diversity)

    return {
        "selected_topic": decision["selected_topic"],
        "target_question_count": decision["target_question_count"],
        "suggested_price": decision["suggested_price"],
        "scheduled_publish_time": scheduled_time,
        "decision_reasoning": decision.get("decision_reasoning", ""),
        "dimension_defs": decision.get("dimension_defs", []),
    }
