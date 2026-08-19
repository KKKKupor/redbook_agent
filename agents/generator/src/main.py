"""测试题生成 Agent (Generator) — 分批生成50+题JSON."""

import json
import re as _re
from langchain_core.messages import HumanMessage, SystemMessage
from loguru import logger

from utils.llm_factory import generator_llm
from utils.review import save, save_prompt, save_response
from utils.prompt_loader import load_skill
from utils.token_tracker import add_from_response
from utils.health import note


GENERATOR_SYSTEM_PROMPT = load_skill(__file__, "system")


# ═══ JSON parsing ═══

def _format_dimension_defs(dimensions: list) -> str:
    lines = []
    for dim in dimensions:
        lines.append(
            f"- **{dim['id']} {dim['name']}**: {dim.get('description', '')} "
            f"(高分->{dim.get('high_label', '高')}, 低分->{dim.get('low_label', '低')})"
        )
    return "\n".join(lines)


def _extract_json_by_brace_count(text: str) -> str:
    start = text.find("{")
    if start == -1:
        return ""
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return ""


def _repair_json(json_str: str) -> str:
    json_str = _re.sub(r",(\s*[}\]])", r"\1", json_str)
    json_str = _re.sub(r'"(\w+)":\s*\+(\d+)', r'"\1": \2', json_str)
    return json_str


def _parse_generated_json(raw: str) -> dict:
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

    extracted = _extract_json_by_brace_count(content)
    if extracted:
        try:
            return json.loads(_repair_json(extracted))
        except json.JSONDecodeError:
            pass

    # Debug
    from pathlib import Path
    Path("data/_generator_debug_last_response.txt").write_text(raw, encoding="utf-8")
    raise ValueError(f"Failed to parse JSON. Raw length: {len(raw)}, start: {raw[:200]}")


def _validate_questions(questions: list, expected_count: int, max_score: int = 10) -> tuple[list, list]:
    errors = []
    if len(questions) < expected_count * 0.9:
        errors.append(f"Count: got {len(questions)}, expected {expected_count}")
    for q in questions:
        qid = q.get("id", "?")
        if "text" not in q:
            errors.append(f"Q{qid}: missing text")
        opts = q.get("options", [])
        if len(opts) != 4:
            errors.append(f"Q{qid}: {len(opts)} options, expected 4")
        for opt in opts:
            scores = opt.get("scores", {})
            if len(scores) < 3:
                errors.append(f"Q{qid} {opt.get('label', '?')}: only {len(scores)} dims (need >= 3)")
            for k, v in scores.items():
                if not (0 <= v <= max_score):
                    errors.append(f"Q{qid} {opt.get('label', '?')} {k}: {v} out of [0,{max_score}]")
    return questions, errors


# ═══ Main node ═══

def generator_node(state: dict) -> dict:
    topic = state.get("selected_topic", "MBTI职场性格")
    question_count = state.get("target_question_count", 10)
    dimensions = state.get("dimension_defs", [])
    review_retries = state.get("review_retry_count", 0)
    fixes_needed = state.get("review_fixes_needed", [])

    if not dimensions:
        logger.warning("No dimension_defs in state — using generic fallback")
        note("generator", "dimension_fallback", "dimension_defs 缺失,使用通用维度")
        dimensions = [
            {"id": "D1", "name": "维度一", "high_label": "高", "low_label": "低"},
            {"id": "D2", "name": "维度二", "high_label": "高", "low_label": "低"},
        ]

    max_score = max(1, round(100 / max(1, question_count)))
    dim_text = _format_dimension_defs(dimensions)
    BATCH_SIZE = 15
    num_batches = max(1, (question_count + BATCH_SIZE - 1) // BATCH_SIZE)

    logger.info(f"Generator: producing {question_count} questions in {num_batches} batches")

    # Build fix instructions from reviewer feedback (Evaluator-Optimizer loop)
    fix_context = ""
    if review_retries > 0 and fixes_needed:
        fix_lines = ["\n## ⚠️ 质量修复指令（评审员反馈，第{}次修复）".format(review_retries)]
        for fix in fixes_needed:
            section = fix.get("section", "unknown")
            detail = fix.get("issue", fix.get("detail", ""))
            action = fix.get("action", "")
            dim_id = fix.get("dim_id", "")
            qid = fix.get("question_id", "")
            loc = f"维度{dim_id}" if dim_id else f"题{qid}" if qid else section
            fix_lines.append(f"- [{loc}] {detail} → {action}")
        fix_context = "\n".join(fix_lines)
        logger.info(f"Generator: applying {len(fixes_needed)} reviewer fixes (retry {review_retries})")

    all_questions = []
    all_errors = []

    for batch_idx in range(num_batches):
        batch_size = min(BATCH_SIZE, question_count - len(all_questions))
        start_id = len(all_questions) + 1

        batch_prompt = (
            GENERATOR_SYSTEM_PROMPT
            .replace("{question_count}", str(batch_size))
            .replace("{max_score}", str(max_score))
            .replace("{dimension_defs_text}", dim_text)
        )

        llm = generator_llm()
        logger.info(f"  Batch {batch_idx+1}/{num_batches}: questions {start_id}-{start_id+batch_size-1}")

        try:
            response = llm.invoke([
                SystemMessage(content=batch_prompt),
                HumanMessage(content=f"选题: {topic}\n本批次生成 {batch_size} 题，题号 {start_id}-{start_id+batch_size-1}{fix_context}\n只输出JSON。"),
            ])
            add_from_response(f"generator_b{batch_idx+1}", response)
            save_prompt(f"generator/batch_{batch_idx+1}", batch_prompt)
            save_response(f"generator/batch_{batch_idx+1}", response.content)
            result = _parse_generated_json(response.content)
            batch_questions = result.get("questions", [])

            for i, q in enumerate(batch_questions):
                q["id"] = start_id + i

            valid_qs, errs = _validate_questions(batch_questions, batch_size, max_score)
            all_questions.extend(valid_qs)
            all_errors.extend(errs)
            logger.info(f"  Batch {batch_idx+1}: got {len(batch_questions)} questions")
        except Exception as e:
            logger.error(f"  Batch {batch_idx+1} failed: {e}")
            note("generator", "generation_failed", str(e)[:200])

    if all_errors:
        logger.warning(f"Quality issues: {all_errors[:5]}")

    result = {
        "topic": topic,
        "total_questions": len(all_questions),
        "dimension_defs": dimensions,
        "questions": all_questions,
    }

    logger.info(f"Generator: produced {len(all_questions)} questions total")
    save("generator", "questions.json", result)
    save("generator", "dimensions.json", dimensions)

    return {"questions_json": result, "generated_html": ""}
