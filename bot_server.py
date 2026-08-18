"""
DingTalk Bot Server — receive @bot messages, generate tests on demand.

Start: python bot_server.py
Expose: ngrok http 8080
Configure DingTalk outgoing webhook → ngrok_url/dingtalk/webhook
"""

import json, re, os, sys, asyncio, subprocess
from datetime import datetime
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import uvicorn

sys.path.insert(0, str(Path(__file__).resolve()))
from dotenv import load_dotenv
load_dotenv()

from agents.navigator.src.main import navigator_node
from agents.generator.src.main import generator_node
from agents.packager.src.main import packager_node
from utils.token_tracker import add_from_response, summary as token_summary, reset as token_reset

app = FastAPI()

DINGTALK_URL = os.getenv("DINGTALK_WEBHOOK_URL", "")
REVIEW_MODE = os.getenv("REVIEW_MODE", "false").lower() == "true"


def parse_command(text: str) -> dict:
    """Parse user message — detects both 'generate' and 'coordinate' commands."""
    text = re.sub(r'@\S+', '', text).strip()

    # Coordination commands (Navigator handles these)
    if any(kw in text for kw in ["发小红书", "发布", "上传", "publish"]):
        return {"type": "publish", "text": text}
    if any(kw in text for kw in ["重新生成", "重做", "再来", "redo", "regenerate"]):
        return {"type": "regenerate", "text": text}
    if any(kw in text for kw in ["改", "调整", "换成"]):
        count_match = re.search(r'(\d+)\s*题', text)
        return {"type": "modify", "text": text, "new_count": int(count_match.group(1)) if count_match else None}
    if any(kw in text for kw in ["挺好", "不错", "可以", "ok", "行", "好"]):
        return {"type": "approve_publish", "text": text}

    # Generate command
    topic_match = re.search(r'(?:关于|做.*?|想要.*?|要.*?)(.+?)(?:的测试|测试题|测试|$)', text)
    topic = topic_match.group(1).strip() if topic_match else text[:30]
    count_match = re.search(r'(\d+)\s*题', text)
    count = int(count_match.group(1)) if count_match else 15
    return {"type": "generate", "text": text, "topic": topic, "question_count": min(count, 100)}


def send_dingtalk(title: str, content: str):
    """Send markdown message to DingTalk."""
    if not DINGTALK_URL:
        return
    import httpx
    payload = {
        "msgtype": "markdown",
        "markdown": {"title": title[:256], "text": content},
    }
    httpx.post(DINGTALK_URL, json=payload, timeout=10)


async def generate_test(topic: str, question_count: int) -> dict:
    """Navigator → Generator → Packager → Publisher (full auto chain)."""
    global _last_topic, _last_count
    _last_topic = topic
    _last_count = question_count
    token_reset()

    # 1. Navigator
    state = {"selected_topic": topic, "target_question_count": question_count, "suggested_price": 1.99}
    nav = navigator_node(state)

    # 2. Generator
    gen = generator_node({"selected_topic": topic, "target_question_count": question_count, "dimension_defs": nav.get("dimension_defs", [])})

    # 3. Packager
    pkg = packager_node({
        "selected_topic": topic, "target_question_count": question_count,
        "suggested_price": 1.99, "dimension_defs": nav.get("dimension_defs", []),
        "questions_json": gen.get("questions_json", {}),
    })

    # 4. Publisher (Navigator auto-calls it — no manual step)
    from agents.publisher.src.main import publisher_node
    pub = publisher_node({"generated_html": pkg.get("generated_html", ""), "selected_topic": topic})

    return {
        "topic": topic, "questions": question_count,
        "url": pub.get("html_url", ""), "cost": token_summary()["total_cost"],
    }


@app.post("/dingtalk/webhook")
async def dingtalk_webhook(request: Request):
    """Receive DingTalk outgoing webhook POST."""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid json"}, 400)

    text = body.get("text", {}).get("content", "")
    sender = body.get("senderNick", "unknown")

    print(f"[BOT] Received from {sender}: {text}")

    # Route through Navigator (central coordinator)
    cmd = parse_command(text)
    cmd_type = cmd["type"]

    if cmd_type == "generate":
        topic = cmd["topic"]
        count = cmd["question_count"]
        send_dingtalk(
            f"收到 - {topic}",
            f"## 🤖 收到 @{sender}\n\n**选题**: {topic}\n**题量**: {count}题\n\n⏳ Navigator 正在规划中...\n\n小红书"
        )
        try:
            result = await generate_test(topic, count)
            reply = (
                f"## ✅ Navigator 已完成 - {topic}\n\n"
                f"**题量**: {result['questions']}题 | 花费: ¥{result['cost']:.4f}\n"
                f"**链接**: [打开测试]({result['url']})\n\n"
                f"审核后回复\"发小红书\"即可发布\n\n小红书"
            )
        except Exception as e:
            reply = f"## ❌ 生成失败\n\n{str(e)[:200]}\n\n小红书"

    elif cmd_type in ("approve_publish", "publish"):
        send_dingtalk("发布中", f"## 🚀 Navigator → Publisher 部署中...\n\n小红书")
        try:
            from agents.publisher.src.main import publisher_node
            # Get latest HTML from state or file
            deploy_dir = Path(__file__).resolve().parent / "output" / "deploy" / "latest"
            html_files = list(deploy_dir.glob("*.html")) if deploy_dir.exists() else []
            html = html_files[0].read_text(encoding="utf-8") if html_files else ""
            pub_result = publisher_node({
                "generated_html": html,
                "selected_topic": "用户审核通过",
            })
            url = pub_result.get("html_url", "https://xhs-mbti-test.vercel.app")
            reply = f"## ✅ Navigator → Publisher 已发布\n\n**链接**: {url}\n\n小红书"
        except Exception as e:
            reply = f"## ❌ Publisher 发布失败\n\n{str(e)[:200]}\n\n小红书"

    elif cmd_type == "regenerate":
        send_dingtalk("重新生成中", f"## 🔄 Navigator → Generator 重新生成...\n\n小红书")
        try:
            from agents.generator.src.main import generator_node
            gen_result = generator_node({
                "selected_topic": _last_topic if '_last_topic' in dir() else "test",
                "target_question_count": _last_count if '_last_count' in dir() else 10,
                "dimension_defs": [],
            })
            reply = f"## ✅ 已重新生成 {len(gen_result.get('questions_json',{}).get('questions',[]))} 题\n\n小红书"
        except Exception as e:
            reply = f"## ❌ 重新生成失败\n\n{str(e)[:200]}\n\n小红书"

    else:
        reply = f"## ❓ 未知指令\n\n收到: {text[:100]}\n\n小红书"

    send_dingtalk(f"Navigator 响应", reply)
    return JSONResponse({"status": "ok"})


if __name__ == "__main__":
    print("DingTalk Bot Server starting on port 8080...")
    print("Expose: ngrok http 8080")
    uvicorn.run(app, host="0.0.0.0", port=8080, log_level="info")
