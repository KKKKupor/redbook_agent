"""
Quick test generator — on-demand test creation via CLI.

Usage:
    python quick_test.py "无畏契约特工性格测试" 15
    python quick_test.py "恋爱人格" 20 --price 2.99
"""

import json, os, sys, random as _random
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve()))
from dotenv import load_dotenv
load_dotenv()

from agents.generator.src.main import generator_node
from agents.packager.src.main import packager_node
from agents.reviewer.src.main import reviewer_node
from utils.notifier import notifier
from utils.token_tracker import summary as token_summary, reset as token_reset
from langchain_core.messages import HumanMessage, SystemMessage
from loguru import logger


def deploy_vercel(html: str) -> str:
    """部署到 GitHub Pages(函数名保留以最小化改动)。"""
    deploy_dir = Path(__file__).resolve().parent / "output" / "deploy" / "latest"
    deploy_dir.mkdir(parents=True, exist_ok=True)
    (deploy_dir / "index.html").write_text(html, encoding="utf-8")
    try:
        from utils.ghpages_deploy import deploy_to_ghpages
        urls = deploy_to_ghpages(deploy_dir, datetime.now().strftime("%Y-%m-%d"))
        return urls["html_url"]
    except Exception as e:
        logger.error(f"Deploy failed: {e}")
        return str(deploy_dir / "index.html")


def _extract_json(raw: str) -> dict:
    content = raw.strip()
    if content.startswith("```"):
        parts = content.split("```")
        content = parts[1] if len(parts) > 1 else content
        if content.startswith("json"): content = content[4:]
    content = content.strip()
    if content.startswith("{"):
        try: return json.loads(content)
        except: pass
    # brace-count
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


def main():
    if len(sys.argv) < 2:
        print("Usage: python quick_test.py <topic> [question_count] [--price X.XX]")
        sys.exit(1)

    topic = sys.argv[1]
    count = 10
    price = 1.99
    for i, arg in enumerate(sys.argv[2:], 2):
        if arg.isdigit(): count = min(int(arg), 100)
        elif arg == "--price" and i + 1 < len(sys.argv): price = float(sys.argv[i+1])
    count = min(max(count, 5), 100)

    print(f"Generating: '{topic}' x {count} questions, price={price} yuan")
    print("-" * 50)
    token_reset()

    # 1. Navigator — fully autonomous: detects IP, extracts characters, plans dimensions
    from utils.llm_factory import navigator_llm
    dim_count = _random.randint(5, 10)

    nav_llm = navigator_llm()
    nav_prompt = (Path(__file__).resolve().parent / "agents" / "navigator" / "src" / "skills" / "system.md").read_text(encoding="utf-8")

    # Let Navigator research the topic first
    from tools.web_search import web_search
    search_query = f"{topic} 角色 分类 特征"
    logger.info(f"Navigator searching: {search_query}")
    search_result = web_search.invoke({"query": search_query, "max_results": 3})

    dim_context = (
        f"已选定选题: {topic}\n"
        f"任务: 定义 {dim_count} 个评分维度。\n"
        f"如果这是角色/IP匹配测试，必须使用下面的搜索结果提取具体角色名和特征，输出ip_roles和ip_info。\n"
        f"角色名要具体（如Jett/格兰芬多），不要抽象描述。\n\n"
        f"=== 网络搜索结果 ===\n{search_result}\n=== 搜索结果结束 ===\n\n"
        f"直接输出JSON: {{\"dimension_defs\": [...], \"ip_roles\": [...], \"ip_info\": \"...\"}}"
    )

    try:
        resp = nav_llm.invoke([SystemMessage(content=nav_prompt), HumanMessage(content=dim_context)])
        data = _extract_json(resp.content)
        dims = data.get("dimension_defs", [])
        ip_info = data.get("ip_info", "")
    except Exception as e:
        dims = []
        ip_info = ""
        logger.warning(f"Dimension parse failed: {e}")

    if not dims:
        dims = [{"id": f"D{i+1}", "name": f"特质{i+1}", "high_label": "突出", "low_label": "平和"} for i in range(dim_count)]

    print(f"Dimensions: {len(dims)} ({', '.join(d['name'] for d in dims)})")
    if ip_info:
        print(f"IP auto-detected: {ip_info[:80]}...")

    # 2. Generator
    gen = generator_node({
        "selected_topic": topic,
        "target_question_count": count,
        "dimension_defs": dims,
    })
    questions = gen.get("questions_json", {}).get("questions", [])
    print(f"Questions: {len(questions)} generated")

    # 3. Packager — IP info from Navigator's own detection
    pkg = packager_node({
        "selected_topic": topic,
        "target_question_count": count,
        "suggested_price": price,
        "dimension_defs": dims,
        "questions_json": gen.get("questions_json", {}),
        "_ip_info": ip_info,  # Navigator auto-detected, no hardcoding
    })
    html = pkg.get("generated_html", "")
    copy_text = pkg.get("packaging_text", "")
    print(f"HTML: {len(html)} chars")

    # 3.5. Reviewer — quality check (Evaluator-Optimizer feedback loop)
    review_state = {
        "selected_topic": topic,
        "questions_json": gen.get("questions_json", {}),
        "generated_html": html,
        "packaging_text": copy_text,
        "dimension_defs": dims,
        "review_retry_count": 0,       # quick_test starts fresh
        "review_fixes_needed": [],
    }
    review = reviewer_node(review_state)
    review_score = review.get("review_score", "N/A")
    review_verdict = review.get("review_verdict", "")
    review_retries = review.get("review_retry_count", 0)
    fixes_needed = review.get("review_fixes_needed", [])

    # If score < 6, do one retry with fixes (quick_test has no LangGraph loop, manual retry)
    if review_score != "N/A" and float(review_score) < 6 and fixes_needed:
        print(f"  Score {review_score}/10 < 6, retrying generator with {len(fixes_needed)} fixes...")
        gen2_state = {
            "selected_topic": topic,
            "target_question_count": count,
            "dimension_defs": dims,
            "review_retry_count": 1,
            "review_fixes_needed": fixes_needed,
        }
        gen2 = generator_node(gen2_state)
        questions2 = gen2.get("questions_json", {}).get("questions", [])
        pkg2 = packager_node({
            "selected_topic": topic,
            "target_question_count": count,
            "suggested_price": price,
            "dimension_defs": dims,
            "questions_json": gen2.get("questions_json", {}),
            "_ip_info": ip_info,
        })
        html = pkg2.get("generated_html", html)  # keep old if new fails
        copy_text = pkg2.get("packaging_text", copy_text)
        gen = gen2  # use regenerated
        print(f"  Regenerated: {len(questions2)} questions, HTML {len(html)} chars")

    print(f"Review: {review_score}/10 (verdict: {review_verdict})")

    # 4. Deploy
    print("Deploying to Vercel...")
    url = deploy_vercel(html)
    print(f"URL: {url}")

    # 5. DingTalk
    cost = token_summary()
    now = datetime.now().strftime("%m-%d %H:%M")
    report = (
        f"## 按需生成 - {topic}\n\n"
        f"**题量**: {count}题 | **定价**: {price}元\n"
        f"**维度**: {', '.join(d['name'] for d in dims[:6])}{'...' if len(dims)>6 else ''}\n"
        f"**花费**: {cost['total_cost']:.4f}元\n"
        f"**链接**: [打开测试]({url})\n\n小红书"
    )
    notifier.send(title=f"测试生成 - {topic}", content=report, level="info")

    print("-" * 50)
    print(f"Done! Cost: {cost['total_cost']:.4f} yuan | {url}")


if __name__ == "__main__":
    main()
