"""Web 控制台 — Claude 风格单页 + SSE 流式生成。

启动: python web_console.py  (端口 8090)
访问: http://localhost:8090/

架构: agent 链在后台 worker 线程执行,事件(含 LLM token)写入线程安全队列;
SSE 生成器实时消费队列,保证 token 逐帧到达前端(而非 agent 完成后一口气发出)。
"""

import json
import os
import queue
import re
import sys
import threading
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger
import uvicorn

load_dotenv()

# web 控制台默认自托管测试页(不依赖 github.io 公网可达性);
# .env 显式设置优先(如服务器上 PUBLIC_BASE_URL=http://62.234.164.182:8090)
os.environ.setdefault("DEPLOY_MODE", "static")
os.environ.setdefault("PUBLIC_BASE_URL", "http://localhost:8090")

sys.path.insert(0, str(Path(__file__).resolve().parent))

from utils.command_parser import parse_command
from utils.daily_limit import DEFAULT_LOOPBACK, DailyLimit
from utils.stream_bus import set_emitter, reset_emitter
from utils.token_tracker import summary as token_summary

app = FastAPI()
TEMPLATE_PATH = Path(__file__).resolve().parent / "templates" / "web_console.html"
# 静态托管生成的测试页与封面图(/quiz/...)— 素材图本地加载,不依赖 github.io 可达性
DEPLOY_DIR = Path(__file__).resolve().parent / "output" / "deploy"
DEPLOY_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/quiz", StaticFiles(directory=str(DEPLOY_DIR), html=True), name="quiz")
# 白名单 = 回环(本机测试)∪ env 配置;白名单 IP 不限次、不消耗配额
LIMIT = DailyLimit(
    Path(__file__).resolve().parent / "data" / "rate_limit.json",
    whitelist=DEFAULT_LOOPBACK | {ip.strip() for ip in os.getenv("WHITELIST_IPS", "").split(",") if ip.strip()},
)
_running: set = set()

AGENTS = {
    "navigator": "领航员 Navigator",
    "generator": "生成器 Generator",
    "packager": "包装师 Packager",
    "reviewer": "评审员 Reviewer",
    "auditor": "审核员 Auditor",
    "publisher": "发布器 Publisher",
}

MAX_REVIEW_RETRIES = 2   # 评审不达标最多重做2次(Evaluator-Optimizer 设计意图)

_SENTINEL = object()


class _QueueEmitter:
    """把事件写入线程安全队列(worker 线程生产,SSE 生成器消费)。"""

    def __init__(self, q: queue.Queue):
        self.q = q

    def emit(self, event: dict) -> None:
        self.q.put(event)


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


def _local_quiz_url(url: str) -> str:
    """gh-pages 素材 URL → 本服务静态路径 /quiz/d/...(本地加载,不依赖 github.io)。"""
    if not url:
        return ""
    m = re.search(r"/d/(.*)", url)
    return "/quiz/d/" + m.group(1) if m else url


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

    # 提前占位:防止两个同 IP 请求在流首次迭代前同时通过 _running 检查
    _running.add(ip)
    return StreamingResponse(
        generate_stream(cmd, ip),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _run_chain(q: queue.Queue, agents: dict, cmd: dict, stop_event: threading.Event) -> None:
    """六段链(含评审闭环)在 worker 线程内执行;事件(含 LLM token)实时入队。"""
    topic = cmd["topic"]
    count = cmd["question_count"]
    user_message = cmd.get("text", "")

    q.put({"event": "agent_start", "agent": "navigator", "name": AGENTS["navigator"]})
    nav = agents["navigator"]({
        "selected_topic": topic,
        "target_question_count": count,
        "suggested_price": 1.99,
        "user_message": user_message,
        "entry_web": True,
    })
    if nav.get("rejected"):
        # 网页入口拒绝(题量超限/无关输入):navigator 已流式输出说明,链终止
        q.put({"event": "agent_done", "agent": "navigator", "summary": {"状态": "已拒绝"}})
        q.put({"event": "done", "url": "", "rejected": True, "reply": nav.get("reply", ""),
               "cost": round(token_summary()["total_cost"], 4)})
        return
    # navigator 已判读用户意图:选题(用户指定或池)与题量(LLM 判读)均以返回值为准
    effective_topic = (nav.get("selected_topic") or topic or "").strip()
    count = int(nav.get("target_question_count") or count)
    q.put({"event": "agent_done", "agent": "navigator",
           "summary": {"选题": effective_topic,
                        "维度数": len(nav.get("dimension_defs", [])),
                        "定价": nav.get("suggested_price")}})
    if stop_event.is_set():
        return

    # ═══ 评审闭环: generator → packager → reviewer;不达标时按 fixes_needed 定向修复(最多2次)═══
    # 定向修复复用 fix_issues 的 fix_* 函数(内存 state,只改评审点名的部分,不从头生成)
    from fix_issues import (
        fix_analysis_dim, fix_copy, fix_personality, fix_question, fix_style, re_render,
    )
    from utils.llm_factory import generator_llm, packager_llm as _fix_packager_llm

    review_retry_count = 0
    review_fixes_needed: list = []
    need_full_redo = False
    pkg: dict = {}
    q_count = 0
    fix_state: dict = {}

    def build_fix_state() -> dict:
        return {
            "questions_json": {
                "topic": effective_topic,
                "total_questions": q_count,
                "questions": list(gen.get("questions_json", {}).get("questions", [])),
            },
            "dimension_defs": list(nav.get("dimension_defs", [])),
            "style": dict(pkg.get("style") or {}),
            "analysis": list(pkg.get("_analysis_data") or []),
            "personality": dict(pkg.get("_personality_data") or {}),
            "copy_text": pkg.get("packaging_text") or "",
        }

    def apply_targeted_fixes(state: dict, fixes: list):
        """按 fixes 的 section 定向修复;返回 (need_full_redo, desc)。"""
        need_full = False
        desc = []
        for fix in fixes or []:
            section = (fix.get("section") or "").strip()
            try:
                if section == "personality":
                    state["personality"] = fix_personality(state, _fix_packager_llm())
                    desc.append("结果标签")
                elif section == "copy":
                    state["copy_text"] = fix_copy(state, _fix_packager_llm())
                    desc.append("文案")
                elif section in ("visual_style", "style"):
                    state["style"] = fix_style(state, _fix_packager_llm())
                    desc.append("视觉风格")
                elif section == "analysis":
                    dim_id = fix.get("dim_id")
                    if not dim_id:
                        need_full = True
                        continue
                    new_dim = fix_analysis_dim(state, dim_id, _fix_packager_llm())
                    if not new_dim:
                        need_full = True
                        continue
                    state["analysis"] = [d for d in state["analysis"] if d.get("dim_id") != dim_id] + [new_dim]
                    desc.append(f"维度{dim_id}分析")
                elif section == "questions":
                    qid = fix.get("question_id")
                    if not qid:
                        need_full = True
                        continue
                    new_q = fix_question(state, qid, fix.get("issue", ""), fix.get("action", ""), generator_llm())
                    if not new_q:
                        need_full = True
                        continue
                    state["questions_json"]["questions"] = [
                        new_q if x.get("id") == qid else x for x in state["questions_json"]["questions"]
                    ]
                    desc.append(f"第{qid}题")
                else:
                    # 未知 section(如 "all"):定向修不了 → 全量重做
                    need_full = True
            except Exception as e:
                logger.warning(f"web console targeted fix failed ({section}): {e}")
                need_full = True
        return need_full, desc

    for attempt in range(1 + MAX_REVIEW_RETRIES):
        if attempt == 0 or need_full_redo:
            # ── 全量生成(首轮,或定向修复无法覆盖时回退)──
            q.put({"event": "agent_start", "agent": "generator", "name": AGENTS["generator"]})
            gen = agents["generator"]({
                "selected_topic": effective_topic,
                "target_question_count": count,
                "dimension_defs": nav.get("dimension_defs", []),
                "review_retry_count": review_retry_count,
                "review_fixes_needed": review_fixes_needed,
            })
            q_count = len(gen.get("questions_json", {}).get("questions", []))
            q.put({"event": "agent_done", "agent": "generator", "summary": {"题目数": q_count}})
            if stop_event.is_set():
                return

            q.put({"event": "agent_start", "agent": "packager", "name": AGENTS["packager"]})
            pkg = agents["packager"]({
                "selected_topic": effective_topic,
                "target_question_count": count,
                "suggested_price": 1.99,
                "dimension_defs": nav.get("dimension_defs", []),
                "questions_json": gen.get("questions_json", {}),
            })
            q.put({"event": "agent_done", "agent": "packager",
                   "summary": {"文案": (pkg.get("packaging_text") or "")[:60]}})
            if stop_event.is_set():
                return
        else:
            # ── 定向修复轮:只改评审点名的部分 ──
            sections = [f.get("section") or "?" for f in review_fixes_needed]
            q.put({"event": "step",
                   "message": f"评审未达标,正在按评审意见定向修复(第 {review_retry_count} 次):{'、'.join(sections)}…"})
            q.put({"event": "agent_start", "agent": "packager", "name": AGENTS["packager"]})
            need_full_redo, desc = apply_targeted_fixes(fix_state, review_fixes_needed)
            if need_full_redo:
                q.put({"event": "agent_done", "agent": "packager",
                       "summary": {"定向修复": "部分完成,剩余问题需全量重做"}})
                if stop_event.is_set():
                    return
                q.put({"event": "agent_start", "agent": "generator", "name": AGENTS["generator"]})
                gen = agents["generator"]({
                    "selected_topic": effective_topic,
                    "target_question_count": count,
                    "dimension_defs": nav.get("dimension_defs", []),
                    "review_retry_count": review_retry_count,
                    "review_fixes_needed": review_fixes_needed,
                })
                q_count = len(gen.get("questions_json", {}).get("questions", []))
                q.put({"event": "agent_done", "agent": "generator", "summary": {"题目数": q_count}})
                if stop_event.is_set():
                    return
                q.put({"event": "agent_start", "agent": "packager", "name": AGENTS["packager"]})
                pkg = agents["packager"]({
                    "selected_topic": effective_topic,
                    "target_question_count": count,
                    "suggested_price": 1.99,
                    "dimension_defs": nav.get("dimension_defs", []),
                    "questions_json": gen.get("questions_json", {}),
                })
                q.put({"event": "agent_done", "agent": "packager",
                       "summary": {"文案": (pkg.get("packaging_text") or "")[:60]}})
                if stop_event.is_set():
                    return
            else:
                # 重新渲染 HTML(修复后的 style/personality/analysis/题目)
                pkg["generated_html"] = re_render(fix_state)
                pkg["packaging_text"] = fix_state["copy_text"]
                q.put({"event": "agent_done", "agent": "packager",
                       "summary": {"定向修复": "、".join(desc) or "完成"}})
                if stop_event.is_set():
                    return

        fix_state = build_fix_state()

        q.put({"event": "agent_start", "agent": "reviewer", "name": AGENTS["reviewer"]})
        rev = agents["reviewer"]({
            "selected_topic": effective_topic,
            "questions_json": fix_state["questions_json"],
            "generated_html": pkg.get("generated_html", ""),
            "packaging_text": fix_state["copy_text"],
            "dimension_defs": fix_state["dimension_defs"],
            "_personality_data": fix_state["personality"],
            "style": fix_state["style"],
            "review_retry_count": review_retry_count,
            "review_fixes_needed": review_fixes_needed,
        })
        score = rev.get("review_score", 0)
        q.put({"event": "agent_done", "agent": "reviewer",
               "summary": {"评分": score, "结论": rev.get("review_verdict", ""),
                            "重做次数": rev.get("review_retry_count", 0)}})
        if stop_event.is_set():
            return

        review_retry_count = rev.get("review_retry_count", review_retry_count)  # reviewer 判不过时自增
        review_fixes_needed = rev.get("review_fixes_needed") or []
        if score >= 6 or rev.get("review_verdict") == "approve" or review_retry_count > MAX_REVIEW_RETRIES:
            break
        if attempt >= MAX_REVIEW_RETRIES:
            break  # 防御:重做次数用尽(attempt 硬上限)

    # ═══ 审核: 展示结果;fail 不回退(web 交互场景,反馈非结构化无法消费)═══
    q.put({"event": "agent_start", "agent": "auditor", "name": AGENTS["auditor"]})
    aud = agents["auditor"]({
        "generated_html": pkg.get("generated_html", ""),
        "packaging_text": pkg.get("packaging_text", ""),
        "questions_json": gen.get("questions_json", {}),
        "retry_count": 0,
    })
    audit_status = aud.get("audit_status", "pass")
    audit_feedback = aud.get("audit_feedback", "")
    q.put({"event": "agent_done", "agent": "auditor",
           "summary": {"审核": audit_status, "反馈": audit_feedback[:120]}})
    if stop_event.is_set():
        return

    q.put({"event": "step", "message": "正在生成封面图并部署到 GitHub Pages…"})
    q.put({"event": "agent_start", "agent": "publisher", "name": AGENTS["publisher"]})
    pub = agents["publisher"]({"generated_html": pkg.get("generated_html", ""), "selected_topic": effective_topic})
    url = pub.get("html_url", "")
    images = [im for im in [
        {"url": _local_quiz_url(pub.get("cover_image_url", "")), "label": "封面-起始页"},
        {"url": _local_quiz_url(pub.get("result_image_url", "")), "label": "封面-结果页"},
        {"url": _local_quiz_url(pub.get("product_image_url", "")), "label": "商品主图"},
    ] if im["url"]]  # 截图失败(publisher 置空)时过滤
    q.put({"event": "agent_done", "agent": "publisher",
           "summary": {"链接": url, "图片数": len(images)}})
    q.put({"event": "done",
           "url": url,
           "cost": round(token_summary()["total_cost"], 4),
           "post_materials": {"copy": (pkg.get("packaging_text") or "").strip(), "images": images},
           "audit_warning": audit_feedback if audit_status != "pass" else ""})


def generate_stream(cmd: dict, ip: str, agents: dict | None = None, heartbeat_timeout: float = 15):
    """四段链 SSE 生成器:worker 线程跑链,本生成器实时消费队列。

    agents 可注入(测试用);heartbeat_timeout 为无事件时的心跳间隔(秒)。
    """
    # 真实 agent 延迟导入,避免测试环境初始化重资产
    if agents is None:
        from agents.navigator.src.main import navigator_node
        from agents.generator.src.main import generator_node
        from agents.packager.src.main import packager_node
        from agents.reviewer.src.main import reviewer_node
        from agents.auditor.src.main import auditor_node
        from agents.publisher.src.main import publisher_node
        agents = {
            "navigator": navigator_node,
            "generator": generator_node,
            "packager": packager_node,
            "reviewer": reviewer_node,
            "auditor": auditor_node,
            "publisher": publisher_node,
        }

    q = queue.Queue()
    stop_event = threading.Event()

    def worker():
        # emitter 只在本线程内 set:LLM callback 与链调用同线程,contextvar 稳定可见
        tok = set_emitter(_QueueEmitter(q))
        try:
            try:
                _run_chain(q, agents, cmd, stop_event)
            except Exception as e:
                # 服务端日志保留完整细节;SSE 帧对外屏蔽内部异常信息
                logger.error(f"Web console generation failed: {e}")
                q.put({"event": "error", "message": "生成失败,请稍后再试"})
        finally:
            reset_emitter(tok)
            q.put(_SENTINEL)
            _running.discard(ip)

    threading.Thread(target=worker, daemon=True, name=f"gen-{ip}").start()
    try:
        while True:
            try:
                ev = q.get(timeout=heartbeat_timeout)
            except queue.Empty:
                yield ": ping\n\n"
                continue
            if ev is _SENTINEL:
                break
            yield _sse(ev)
    except GeneratorExit:
        # 客户端断开 → 通知 worker 停止(正在进行的 LLM invoke 无法中断,后续 agent 不再启动)
        stop_event.set()
        raise
    finally:
        stop_event.set()


if __name__ == "__main__":
    print("Web console: http://localhost:8090/")
    uvicorn.run(app, host="0.0.0.0", port=8090, log_level="info")
