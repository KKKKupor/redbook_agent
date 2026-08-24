"""Web 控制台 — Linear 风格单页 + SSE 流式生成。

启动: python web_console.py  (端口 8090)
访问: http://localhost:8090/
"""

import json
import sys
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from loguru import logger
import uvicorn

load_dotenv()

sys.path.insert(0, str(Path(__file__).resolve().parent))

from utils.command_parser import parse_command
from utils.daily_limit import DailyLimit
from utils.stream_bus import set_emitter, reset_emitter
from utils.token_tracker import summary as token_summary, reset as token_reset

app = FastAPI()
TEMPLATE_PATH = Path(__file__).resolve().parent / "templates" / "web_console.html"
LIMIT = DailyLimit(Path(__file__).resolve().parent / "data" / "rate_limit.json")
_running: set = set()

AGENTS = {
    "navigator": "领航员 Navigator",
    "generator": "生成器 Generator",
    "packager": "包装师 Packager",
    "publisher": "发布器 Publisher",
}


class _Emitter:
    """把事件写入生成器的中间缓冲(生成器在后台线程逐帧消费)。"""

    def __init__(self):
        self.queue = []

    def emit(self, event: dict) -> None:
        self.queue.append(event)


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


@app.get("/", response_class=HTMLResponse)
async def index():
    return HTMLResponse(TEMPLATE_PATH.read_text(encoding="utf-8"))


@app.post("/api/generate")
async def generate(request: Request):
    ip = _client_ip(request)
    if ip in _running:
        return JSONResponse({"error": "已有生成进行中,请稍候"}, status_code=429)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "请求格式错误"}, status_code=400)
    if not isinstance(body, dict):
        return JSONResponse({"error": "请求格式错误"}, status_code=400)
    message = (body.get("message") or "").strip()
    if not message:
        return JSONResponse({"error": "消息为空"}, status_code=400)

    cmd = parse_command(message)
    if cmd["type"] != "generate":
        return JSONResponse({"error": "当前仅支持生成指令,例如「做一个人格阴影测试,15题」"}, status_code=400)

    # 限额放行放在全部校验之后:400 请求不消耗当日配额
    if not LIMIT.allow(ip):
        return JSONResponse({"error": "今日生成次数已用完,明天再来吧"}, status_code=429)

    return StreamingResponse(
        generate_stream(cmd, ip),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def generate_stream(cmd: dict, ip: str, agents: dict | None = None):
    """四段链生成器,逐事件产出 SSE 帧。agents 可注入(测试用)。

    agents 形如 {"navigator": fn, "generator": fn, "packager": fn, "publisher": fn}。
    """
    # 真实 agent 延迟导入,避免测试环境初始化重资产
    if agents is None:
        from agents.navigator.src.main import navigator_node
        from agents.generator.src.main import generator_node
        from agents.packager.src.main import packager_node
        from agents.publisher.src.main import publisher_node
        agents = {
            "navigator": navigator_node,
            "generator": generator_node,
            "packager": packager_node,
            "publisher": publisher_node,
        }

    topic = cmd["topic"]
    count = cmd["question_count"]
    emitter = _Emitter()

    def drain(agent_key: str):
        """把缓冲中的 token 事件逐帧发出并清空。"""
        for ev in emitter.queue:
            if ev.get("event") == "token" and ev.get("agent") == agent_key:
                yield _sse(ev)
        emitter.queue = []

    def run_agent(fn, **state):
        """在同一个 next() 内设置 emitter 再调用 agent(线程池逐项迭代会换 context)。"""
        tok = set_emitter(emitter)
        try:
            return fn(state)
        finally:
            reset_emitter(tok)

    try:
        _running.add(ip)
        token_reset()
        yield _sse({"event": "agent_start", "agent": "navigator", "name": AGENTS["navigator"]})
        nav = run_agent(agents["navigator"], selected_topic=topic, target_question_count=count, suggested_price=1.99)
        yield from drain("navigator")
        yield _sse({"event": "agent_done", "agent": "navigator",
                    "summary": {"维度数": len(nav.get("dimension_defs", [])), "定价": nav.get("suggested_price")}})

        yield _sse({"event": "agent_start", "agent": "generator", "name": AGENTS["generator"]})
        gen = run_agent(agents["generator"], selected_topic=topic, target_question_count=count,
                        dimension_defs=nav.get("dimension_defs", []))
        yield from drain("generator")
        q_count = len(gen.get("questions_json", {}).get("questions", []))
        yield _sse({"event": "agent_done", "agent": "generator", "summary": {"题目数": q_count}})

        yield _sse({"event": "agent_start", "agent": "packager", "name": AGENTS["packager"]})
        pkg = run_agent(agents["packager"], selected_topic=topic, target_question_count=count,
                        suggested_price=1.99, dimension_defs=nav.get("dimension_defs", []),
                        questions_json=gen.get("questions_json", {}))
        yield from drain("packager")
        yield _sse({"event": "agent_done", "agent": "packager", "summary": {"文案": (pkg.get("packaging_text") or "")[:60]}})

        yield _sse({"event": "step", "message": "正在生成封面图并部署到 GitHub Pages…"})
        yield _sse({"event": "agent_start", "agent": "publisher", "name": AGENTS["publisher"]})
        pub = run_agent(agents["publisher"], generated_html=pkg.get("generated_html", ""), selected_topic=topic)
        yield from drain("publisher")
        url = pub.get("html_url", "")
        yield _sse({"event": "agent_done", "agent": "publisher", "summary": {"链接": url}})

        cost = token_summary()["total_cost"]
        yield _sse({"event": "done", "url": url, "cost": round(cost, 4)})

    except Exception as e:
        # 服务端日志保留完整细节;SSE 帧对外屏蔽内部异常信息
        logger.error(f"Web console generation failed: {e}")
        yield _sse({"event": "error", "message": "生成失败,请稍后再试"})
    finally:
        _running.discard(ip)


if __name__ == "__main__":
    print("Web console: http://localhost:8090/")
    uvicorn.run(app, host="0.0.0.0", port=8090, log_level="info")
