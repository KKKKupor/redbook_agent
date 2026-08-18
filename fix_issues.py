"""
Targeted fix tool — reads Reviewer's fixes_needed and regenerates only flagged items.

Usage:
    python fix_issues.py              # read latest reviewer scorecard, apply all fixes
    python fix_issues.py --run 21     # fix specific run

Flow: Read fixes_needed → regenerate only flagged sections → re-render HTML → re-review
"""

import json, os, sys, subprocess, re
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve()))
from dotenv import load_dotenv
load_dotenv()

from utils.llm_factory import packager_llm, generator_llm, navigator_llm
from utils.prompt_loader import load_skill
from utils.review import save, REVIEW_MODE
from utils.token_tracker import summary as token_summary, reset as token_reset
from langchain_core.messages import HumanMessage
from loguru import logger
from jinja2 import Template


def _repair_json(raw: str) -> str:
    raw = re.sub(r",(\s*[}\]])", r"\1", raw)
    raw = re.sub(r'"(\w+)":\s*\+(\d+)', r'"\1": \2', raw)
    return raw


def _parse_json(raw: str) -> dict:
    content = raw.strip()
    if content.startswith("```"):
        parts = content.split("```")
        content = parts[1] if len(parts) > 1 else content
        if content.startswith("json"): content = content[4:]
    content = content.strip()
    if content.startswith("{"):
        try: return json.loads(content)
        except: pass
    # Brace-count
    start = content.find("{")
    if start >= 0:
        depth = 0
        for i in range(start, len(content)):
            if content[i] == "{": depth += 1
            elif content[i] == "}":
                depth -= 1
                if depth == 0:
                    try: return json.loads(content[start:i+1])
                    except: pass; break
    return {}


def find_latest_run() -> str:
    output_dir = Path(__file__).resolve().parent / "output"
    runs = sorted([d for d in output_dir.iterdir() if d.is_dir() and d.name.isdigit() and (d / "reviewer").exists()],
                  key=lambda d: int(d.name), reverse=True)
    return runs[0].name if runs else None


def load_state(run: str) -> dict:
    base = Path(__file__).resolve().parent / "output" / run
    state = {"run": run}
    for path, key in [
        ("generator/questions.json", "questions_json"),
        ("generator/dimensions.json", "dimension_defs"),
        ("packager/style.json", "style"),
        ("packager/analysis.json", "analysis"),
        ("packager/personality.json", "personality"),
        ("packager/copy.txt", "copy_text"),
        ("reviewer/scorecard.json", "scorecard"),
    ]:
        p = base / path
        if p.exists():
            state[key] = json.loads(p.read_text(encoding="utf-8")) if path.endswith(".json") else p.read_text(encoding="utf-8")
    return state


def fix_copy(state: dict, llm) -> str:
    """Regenerate copy text only."""
    from agents.packager.src.main import COPY_PROMPT
    topic = state["questions_json"].get("topic", "test")
    count = state["questions_json"].get("total_questions", 10)
    prompt = COPY_PROMPT.replace("{title}", topic).replace("{question_count}", str(count)).replace("{price}", "1.99")
    resp = llm.invoke([HumanMessage(content=prompt)])
    return resp.content.strip()


def fix_analysis_dim(state: dict, dim_id: str, llm) -> dict:
    """Regenerate analysis for one specific dimension."""
    dims = state.get("dimension_defs", [])
    dim = next((d for d in dims if d["id"] == dim_id), None)
    if not dim:
        logger.warning(f"Dimension {dim_id} not found")
        return {}
    topic = state["questions_json"].get("topic", "test")
    dim_prompt = (
        f"为测试题「{topic}」的维度「{dim['name']}」写深度分析。\n\n"
        f"高分端描述: {dim.get('high_label','高')}，低分端描述: {dim.get('low_label','低')}\n\n"
        f"要求:\n"
        f"1. 三个小节: 🔍核心特质、⚠️潜在盲点、💡专属建议\n"
        f"2. 每小节恰好80-120字，三个小节总字数240-360字\n"
        f"3. 用第二人称\"你\"，具体场景，有洞察力\n"
        f"4. 自然融入社群归属感\n\n"
        f"只输出JSON: {{\"dim_id\":\"{dim_id}\",\"核心特质\":\"...\",\"潜在盲点\":\"...\",\"专属建议\":\"...\"}}"
    )
    resp = llm.invoke([HumanMessage(content=dim_prompt)])
    result = _parse_json(resp.content)
    result["dim_id"] = dim_id
    return result


def fix_personality(state: dict, llm) -> dict:
    """Regenerate personality mapping only."""
    from agents.packager.src.main import PERSONALITY_PROMPT
    dims = state.get("dimension_defs", [])
    topic = state["questions_json"].get("topic", "test")
    dim_names = ", ".join([d.get("name", d.get("id", "?")) for d in dims])
    prompt = PERSONALITY_PROMPT.replace("{dimensions}", dim_names).replace("{topic}", topic)
    resp = llm.invoke([HumanMessage(content=prompt)])
    return _parse_json(resp.content)


def fix_question(state: dict, question_id: int, issue: str, action: str, llm) -> dict:
    """Regenerate one specific question based on reviewer feedback."""
    qjson = state["questions_json"]
    questions = qjson.get("questions", [])
    dims = state.get("dimension_defs", [])
    topic = qjson.get("topic", "test")

    # Find the broken question
    old_q = next((q for q in questions if q.get("id") == question_id), None)
    if not old_q:
        logger.warning(f"Question {question_id} not found")
        return None

    dim_names = ", ".join([f"{d['id']}={d['name']}" for d in dims])
    old_text = json.dumps(old_q, ensure_ascii=False, indent=2)

    prompt = (
        f"修复一道测试题。选题: {topic}\n"
        f"维度定义: {dim_names}\n\n"
        f"原题目:\n{old_text}\n\n"
        f"Reviewer反馈: {issue}\n"
        f"修改要求: {action}\n\n"
        f"规则:\n"
        f"1. 保持题目id={question_id}和type不变\n"
        f"2. 所有分值必须≥0且≤3\n"
        f"3. 每个选项对2-4个维度给正分，其余为0\n"
        f"4. 消除社会赞许性偏差\n"
        f"5. 只输出修复后的JSON: {{\"id\":{question_id},\"text\":\"...\",\"type\":\"...\",\"options\":[{{\"label\":\"A\",\"text\":\"...\",\"scores\":{{...}}}}]}}"
    )
    resp = llm.invoke([HumanMessage(content=prompt)])
    result = _parse_json(resp.content)
    result["id"] = question_id
    return result


def fix_style(state: dict, llm) -> dict:
    """Regenerate visual style only."""
    from agents.packager.src.main import STYLE_PROMPT
    topic = state["questions_json"].get("topic", "test")
    prompt = STYLE_PROMPT.replace("{topic}", topic)
    resp = llm.invoke([HumanMessage(content=prompt)])
    return _parse_json(resp.content)


def re_render(state: dict) -> str:
    """Re-render HTML with updated data."""
    template_path = Path(__file__).resolve().parent / "templates" / "test_template.html"
    template = Template(template_path.read_text(encoding="utf-8"))
    qjson = state["questions_json"]
    questions = qjson.get("questions", [])
    style = state.get("style", {})
    personality = state.get("personality", {})
    dims = state.get("dimension_defs", [])
    analysis = state.get("analysis", [])

    qcount = len(questions) or 1
    max_score = max(1, round(100 / qcount))
    return template.render(
        title=qjson.get("topic", "Test"),
        icon_emoji=style.get("icon_emoji", "🧠"),
        tagline=style.get("tagline", ""),
        accent_color=style.get("accent_color", "#6c5ce7"),
        accent_light=style.get("accent_light", "#a29bfe"),
        accent_glass=style.get("accent_glass", "rgba(108,92,231,0.12)"),
        theme=style.get("theme", "light"),
        default_personality=personality.get("primary_tag", personality.get("personality_tag", "N/A")),
        questions_json=json.dumps(questions, ensure_ascii=False),
        dimension_defs=json.dumps(dims, ensure_ascii=False),
        personality_mapping=json.dumps(personality, ensure_ascii=False),
        theme_config=json.dumps(style, ensure_ascii=False),
        analysis_data=json.dumps(analysis, ensure_ascii=False),
        max_score_per_question=max_score,
    )


def deploy(html: str) -> str:
    deploy_dir = Path(__file__).resolve().parent / "output" / "deploy" / "latest"
    deploy_dir.mkdir(parents=True, exist_ok=True)
    (deploy_dir / "index.html").write_text(html, encoding="utf-8")
    (deploy_dir / "vercel.json").write_text('{"version": 2}', encoding="utf-8")
    try:
        result = subprocess.run(
            f'npx vercel "{deploy_dir}" --prod --yes',
            capture_output=True, text=True, timeout=60,
            cwd=str(deploy_dir), shell=True,
            encoding="utf-8", errors="replace",
        )
        output = result.stdout or ""
        data = json.loads(output) if output.strip().startswith("{") else {}
        url = data.get("deployment", {}).get("url", "") or data.get("url", "")
        if not url:
            for line in output.split("\n"):
                if "vercel.app" in line and "https://" in line:
                    m = re.search(r'https://[^\s"]+', line)
                    if m: url = m.group()
        return url or str(deploy_dir / "index.html")
    except Exception as e:
        logger.error(f"Deploy failed: {e}")
        return str(deploy_dir / "index.html")


def main():
    run = sys.argv[2] if len(sys.argv) > 2 and sys.argv[1] == "--run" else find_latest_run()
    if not run:
        print("No run with reviewer scorecard found. Run quick_test.py first.")
        sys.exit(1)

    print(f"Loading state from run {run}...")
    state = load_state(run)
    fixes = state.get("scorecard", {}).get("fixes_needed", [])
    if not fixes:
        print("No fixes needed — all checks passed!")
        sys.exit(0)

    print(f"Found {len(fixes)} items to fix:\n")
    for f in fixes:
        print(f"  [{f['section']}] {f['issue'][:80]}")
    print()

    token_reset()
    llm = packager_llm()
    topic = state["questions_json"].get("topic", "test")
    fixed_count = 0

    for fix in fixes:
        section = fix["section"]
        dim_id = fix.get("dim_id", "")

        try:
            if section == "copy":
                state["copy_text"] = fix_copy(state, llm)
                fixed_count += 1
                print(f"  Fixed: copy regenerated")

            elif section == "analysis" and dim_id:
                new_analysis = fix_analysis_dim(state, dim_id, llm)
                if new_analysis:
                    # Replace in analysis array
                    for i, a in enumerate(state.get("analysis", [])):
                        if a.get("dim_id") == dim_id:
                            state["analysis"][i] = new_analysis
                            break
                    fixed_count += 1
                    print(f"  Fixed: analysis {dim_id} regenerated")

            elif section == "personality":
                state["personality"] = fix_personality(state, llm)
                fixed_count += 1
                print(f"  Fixed: personality regenerated")

            elif section == "questions":
                qid = fix.get("question_id", 0)
                if qid:
                    gen_llm = generator_llm()
                    new_q = fix_question(state, qid, fix["issue"], fix["action"], gen_llm)
                    if new_q:
                        questions = state["questions_json"].get("questions", [])
                        for i, q in enumerate(questions):
                            if q.get("id") == qid:
                                questions[i] = new_q
                                fixed_count += 1
                                print(f"  Fixed: question {qid} regenerated")
                                break
                    else:
                        print(f"  Skipped: question {qid} not found")
                else:
                    print(f"  Skipped: question fix missing question_id — {fix['issue'][:60]}")

            elif section == "visual_style":
                state["style"] = fix_style(state, llm)
                fixed_count += 1
                print(f"  Fixed: style regenerated")

        except Exception as e:
            print(f"  Failed: [{section}] {e}")

    if fixed_count == 0:
        print("\nNo fixes applied.")
        return

    # Re-render
    print(f"\nApplied {fixed_count} fixes. Re-rendering HTML...")
    html = re_render(state)
    print(f"HTML: {len(html)} chars")

    # Deploy
    print("Deploying...")
    url = deploy(html)

    # Cost
    cost = token_summary()
    print(f"Done! Cost: {cost['total_cost']:.4f} yuan")
    print(f"URL: {url}")

    # Re-review
    print("\nRe-reviewing after fixes...")
    from agents.reviewer.src.main import reviewer_node
    review = reviewer_node({
        "selected_topic": topic,
        "questions_json": state["questions_json"],
        "generated_html": html,
        "packaging_text": state.get("copy_text", ""),
        "dimension_defs": state.get("dimension_defs", []),
    })
    new_score = review.get("review_score", "N/A")
    print(f"New score: {new_score}/10")

    # Save fixed state
    save("fix_results", "fixed_state.json", {
        "fixed_at": datetime.now().isoformat(),
        "run": run,
        "fixes_applied": fixed_count,
        "cost": cost["total_cost"],
        "score_before": state.get("scorecard", {}).get("overall_score"),
        "score_after": new_score,
    })


if __name__ == "__main__":
    main()
