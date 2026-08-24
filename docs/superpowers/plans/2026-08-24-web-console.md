# Web 控制台 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Linear 风格单页控制台:输入指令 → navigator→generator→packager→publisher 四段链,每 agent 思考过程逐 token 流式呈现;每 IP 每日 1 次访问控制。

**Architecture:** `utils/stream_bus.py`(contextvar 事件总线,无 emitter 时 no-op)+ `llm_factory` 构造期注入流式回调(spike 验证);`utils/command_parser.py`(从 bot_server 抽取)+ `utils/daily_limit.py`(每IP每日1次,json 持久化);`web_console.py`(FastAPI:静态首页 + POST SSE 链,agent 函数依赖注入可测);`templates/web_console.html`(Linear recipe 前端)。

**Tech Stack:** Python 3.13(conda env `redbook_agent_company`)、FastAPI+uvicorn(已装)、LangChain callbacks、pytest、loguru。

**Spec:** `docs/superpowers/specs/2026-08-24-web-console-design.md`

## Global Constraints

- ⚠️ **用户规则:git commit 前展示变更摘要并征得同意。** 本会话用户已批准"按计划逐任务提交"(commit message 英文)——各任务 Commit 步骤照此执行。
- 精准修改:不改任何 agent 主体逻辑;bot_server 只把 parse_command 换成共享 import(行为不变);packager 路径 bug 等无关代码不碰。
- 测试运行:`"C:/Users/26063/miniconda3/envs/redbook_agent_company/python.exe" -m pytest <文件> -q`(conda run 在此环境偶发故障);全量套件须保持 65+ 全绿。
- LLM 调用直接连 DeepSeek(国内可达,无需代理);spike 的 LLM 请求预算 <¥0.1。
- 中文注释/文档,英文标识符;loguru。
- SSE 输出为 `data: <json>\n\n` 帧;不使用新依赖(手写 SSE,不引 sse-starlette)。

---

### Task 1: `utils/stream_bus.py` + llm_factory 流式回调(spike)

**Files:**
- Create: `utils/stream_bus.py`
- Create: `tests/test_stream_bus.py`
- Modify: `utils/llm_factory.py`

**Interfaces:**
- Produces:
  - `stream_bus.emit(event: dict) -> None`(当前 context 无 emitter 时 no-op)
  - `stream_bus.set_emitter(emitter) -> Token`(contextvar 设置器,供 with 使用或手工 reset)
  - `_TokenStreamHandler(agent_key)`(BaseCallbackHandler,on_llm_new_token → emit {"event":"token","agent":agent_key,"text":token})

- [ ] **Step 1: TDD 写 bus 测试**

`tests/test_stream_bus.py`(完整内容):

```python
"""Tests for utils.stream_bus — contextvar event bus."""

from utils import stream_bus


class FakeEmitter:
    def __init__(self):
        self.events = []

    def emit(self, event):
        self.events.append(event)


class TestStreamBus:
    def test_no_emitter_is_noop(self):
        stream_bus.emit({"event": "token", "text": "x"})  # 不得抛出

    def test_emit_reaches_current_emitter(self):
        em = FakeEmitter()
        token = stream_bus.set_emitter(em)
        try:
            stream_bus.emit({"event": "token", "text": "你好"})
            assert em.events == [{"event": "token", "text": "你好"}]
        finally:
            stream_bus.reset_emitter(token)

    def test_reset_restores_noop(self):
        em = FakeEmitter()
        token = stream_bus.set_emitter(em)
        stream_bus.reset_emitter(token)
        stream_bus.emit({"event": "token"})  # no-op,不抛
        assert em.events == []
```

- [ ] **Step 2: 跑测试确认失败**

Run: `"C:/Users/26063/miniconda3/envs/redbook_agent_company/python.exe" -m pytest tests/test_stream_bus.py -q`
Expected: FAIL(ModuleNotFoundError: utils.stream_bus)

- [ ] **Step 3: 写实现 + llm_factory 接线**

`utils/stream_bus.py`(完整内容):

```python
"""流式事件总线 — 把各 agent 的 LLM token 流与步骤事件推给当前消费者(如 Web 控制台)。

contextvar 保证同一请求线程内可见;无消费者时 emit 为 no-op(日常调度零影响)。
"""

from contextvars import ContextVar, Token
from typing import Optional

from loguru import logger

_emitter: ContextVar = ContextVar("stream_emitter", default=None)


def emit(event: dict) -> None:
    """向当前 context 的 emitter 发送事件;无 emitter 时静默忽略。"""
    em = _emitter.get()
    if em is None:
        return
    try:
        em.emit(event)
    except Exception as e:
        logger.error(f"stream_bus: emitter 处理事件失败: {e}")


def set_emitter(emitter) -> Token:
    """设置当前 context 的 emitter,返回 reset 用的 Token。"""
    return _emitter.set(emitter)


def reset_emitter(token: Token) -> None:
    """恢复之前的 emitter(通常为 None)。"""
    _emitter.reset(token)
```

`utils/llm_factory.py` 接线:在文件顶部加:

```python
from langchain_core.callbacks import BaseCallbackHandler


class _TokenStreamHandler(BaseCallbackHandler):
    """把 LLM 输出 token 转发到 stream_bus(带 agent 标识)。"""

    def __init__(self, agent_key: str):
        self.agent_key = agent_key

    def on_llm_new_token(self, token: str, **kwargs) -> None:
        from utils.stream_bus import emit
        emit({"event": "token", "agent": self.agent_key, "text": token})
```

每个工厂函数构造模型处(如 `ChatOpenAI(...)` / `ChatDeepSeek(...)` 调用)加 `streaming=True, callbacks=[_TokenStreamHandler("<agent_key>")]`;agent_key 对应:navigator_llm→"navigator"、hunter_llm→"trend_hunter"、generator_llm→"generator"、packager_llm→"packager"、reviewer_llm→"reviewer"、auditor_llm→"auditor"、data_analyst_llm→"data_analyst"。先读 llm_factory.py 确认每个工厂的构造方式再改;若某工厂基于非 ChatOpenAI 兼容类,报告 NEEDS_CONTEXT。

- [ ] **Step 4: spike 验证构造期 callbacks 生效**

Run(真实调用一次 DeepSeek,预算 <¥0.1):

```python
"C:/Users/26063/miniconda3/envs/redbook_agent_company/python.exe" -c "
from dotenv import load_dotenv; load_dotenv()
from utils.stream_bus import set_emitter, reset_emitter
from utils.llm_factory import navigator_llm
class E:
    def __init__(self): self.n = 0
    def emit(self, ev): self.n += 1
e = E()
tok = set_emitter(e)
try:
    navigator_llm().invoke('只回复两个字:收到')
finally:
    reset_emitter(tok)
print('tokens_streamed:', e.n)
assert e.n > 0, '构造期 callbacks 未生效,需退路方案'
"
```

Expected: `tokens_streamed: >0`。若为 0 → 报告 NEEDS_CONTEXT(退路方案为逐调用点包裹,另设计)。

- [ ] **Step 5: 全量测试 + 提交(需用户确认,本会话已预先批准)**

Run: 全量 `tests/` 65 passed(既有行为不变)。
```bash
git add utils/stream_bus.py tests/test_stream_bus.py utils/llm_factory.py
git commit -m "feat: stream bus with per-agent token streaming handlers in llm_factory"
```

---

### Task 2: `utils/command_parser.py` 抽取 + bot_server 改用

**Files:**
- Create: `utils/command_parser.py`
- Create: `tests/test_command_parser.py`
- Modify: `bot_server.py`

- [ ] **Step 1: 写测试**

`tests/test_command_parser.py`(完整内容):

```python
"""Tests for utils.command_parser — message intent parsing."""

from utils.command_parser import parse_command


class TestParseCommand:
    def test_generate_with_topic_and_count(self):
        cmd = parse_command("做一个人格阴影测试，20题")
        assert cmd["type"] == "generate"
        assert cmd["topic"] == "人格阴影测试"
        assert cmd["question_count"] == 20

    def test_generate_default_count(self):
        cmd = parse_command("做一个恋爱人格测试")
        assert cmd["type"] == "generate"
        assert cmd["question_count"] == 15

    def test_generate_plain_topic_falls_back(self):
        cmd = parse_command("随便来一个测试")
        assert cmd["type"] == "generate"
        assert cmd["topic"]

    def test_count_capped_at_100(self):
        assert parse_command("做一个测试，200题")["question_count"] == 100

    def test_publish_intent(self):
        assert parse_command("发小红书吧")["type"] == "publish"

    def test_regenerate_intent(self):
        assert parse_command("重新生成")["type"] == "regenerate"

    def test_modify_intent(self):
        cmd = parse_command("改成30题")
        assert cmd["type"] == "modify"
        assert cmd["new_count"] == 30

    def test_approve_intent(self):
        assert parse_command("不错，就这样")["type"] == "approve_publish"
```

- [ ] **Step 2: 跑测试确认失败** → FAIL(ModuleNotFoundError)

- [ ] **Step 3: 抽取实现**

`utils/command_parser.py`:把 `bot_server.py` 的 `parse_command` 函数原文搬入(含 import re),模块 docstring 说明共享用途。`bot_server.py`:删除内联 `parse_command`,改为 `from utils.command_parser import parse_command`(其余不动)。

- [ ] **Step 4: 验证 + 提交**

Run: `pytest tests/test_command_parser.py -q` 8 passed;`python -c "import bot_server; print('ok')"`。
```bash
git add utils/command_parser.py tests/test_command_parser.py bot_server.py
git commit -m "feat: extract shared command parser used by dingtalk bot and web console"
```

---

### Task 3: `utils/daily_limit.py` + `web_console.py` 后端

**Files:**
- Create: `utils/daily_limit.py`
- Create: `tests/test_daily_limit.py`
- Create: `web_console.py`

- [ ] **Step 1: TDD daily_limit**

`tests/test_daily_limit.py`(完整内容):

```python
"""Tests for utils.daily_limit — one generation per IP per day."""

from utils.daily_limit import DailyLimit


class TestDailyLimit:
    def test_first_allow_then_deny_same_day(self, tmp_path):
        lim = DailyLimit(tmp_path / "rl.json")
        assert lim.allow("1.2.3.4", today="2026-08-24") is True
        assert lim.allow("1.2.3.4", today="2026-08-24") is False

    def test_new_day_allows_again(self, tmp_path):
        lim = DailyLimit(tmp_path / "rl.json")
        assert lim.allow("1.2.3.4", today="2026-08-24") is True
        assert lim.allow("1.2.3.4", today="2026-08-25") is True

    def test_different_ips_independent(self, tmp_path):
        lim = DailyLimit(tmp_path / "rl.json")
        assert lim.allow("1.1.1.1", today="2026-08-24") is True
        assert lim.allow("2.2.2.2", today="2026-08-24") is True

    def test_persists_across_instances(self, tmp_path):
        p = tmp_path / "rl.json"
        DailyLimit(p).allow("9.9.9.9", today="2026-08-24")
        lim2 = DailyLimit(p)
        assert lim2.allow("9.9.9.9", today="2026-08-24") is False
```

- [ ] **Step 2: RED → 实现**

`utils/daily_limit.py`:

```python
"""每 IP 每日一次的生成限额,json 文件持久化(重启不清)。"""

import json
import threading
from datetime import datetime
from pathlib import Path

from loguru import logger


class DailyLimit:
    """{ip: 'YYYY-MM-DD'} 记录;同 IP 同日只放行一次。"""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.Lock()
        self._data: dict = self._load()

    def _load(self) -> dict:
        if self.path.exists():
            try:
                return json.loads(self.path.read_text(encoding="utf-8"))
            except Exception:
                logger.warning(f"daily_limit: 限额文件损坏,重新开始: {self.path}")
        return {}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._data, ensure_ascii=False), encoding="utf-8")

    def allow(self, ip: str, today: str | None = None) -> bool:
        """同 IP 同日首次返回 True 并记录;否则 False。today 可注入便于测试。"""
        today = today or datetime.now().strftime("%Y-%m-%d")
        with self._lock:
            if self._data.get(ip) == today:
                return False
            self._data[ip] = today
            self._save()
            return True
```

- [ ] **Step 3: web_console.py**

完整内容(照抄实现,注意细节):

```python
"""Web 控制台 — Linear 风格单页 + SSE 流式生成。

启动: python web_console.py  (端口 8090)
访问: http://localhost:8090/
"""

import json
import os
import sys
from datetime import datetime
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
    if not LIMIT.allow(ip):
        return JSONResponse({"error": "今日生成次数已用完,明天再来吧"}, status_code=429)
    if ip in _running:
        return JSONResponse({"error": "已有生成进行中,请稍候"}, status_code=429)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "请求格式错误"}, status_code=400)
    message = (body.get("message") or "").strip()
    if not message:
        return JSONResponse({"error": "消息为空"}, status_code=400)

    cmd = parse_command(message)
    if cmd["type"] != "generate":
        return JSONResponse({"error": "当前仅支持生成指令,例如「做一个人格阴影测试,15题」"}, status_code=400)

    _running.add(ip)
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
    token = set_emitter(emitter)

    def drain(agent_key: str):
        """把缓冲中的 token 事件逐帧发出并清空。"""
        for ev in emitter.queue:
            if ev.get("event") == "token" and ev.get("agent") == agent_key:
                yield _sse(ev)
        emitter.queue = []

    try:
        token_reset()
        yield _sse({"event": "agent_start", "agent": "navigator", "name": AGENTS["navigator"]})
        nav = agents["navigator"]({"selected_topic": topic, "target_question_count": count, "suggested_price": 1.99})
        yield from drain("navigator")
        yield _sse({"event": "agent_done", "agent": "navigator",
                    "summary": {"维度数": len(nav.get("dimension_defs", [])), "定价": nav.get("suggested_price")}})

        yield _sse({"event": "agent_start", "agent": "generator", "name": AGENTS["generator"]})
        gen = agents["generator"]({"selected_topic": topic, "target_question_count": count,
                                   "dimension_defs": nav.get("dimension_defs", [])})
        yield from drain("generator")
        q_count = len(gen.get("questions_json", {}).get("questions", []))
        yield _sse({"event": "agent_done", "agent": "generator", "summary": {"题目数": q_count}})

        yield _sse({"event": "agent_start", "agent": "packager", "name": AGENTS["packager"]})
        pkg = agents["packager"]({"selected_topic": topic, "target_question_count": count,
                                  "suggested_price": 1.99, "dimension_defs": nav.get("dimension_defs", []),
                                  "questions_json": gen.get("questions_json", {})})
        yield from drain("packager")
        yield _sse({"event": "agent_done", "agent": "packager", "summary": {"文案": (pkg.get("packaging_text") or "")[:60]}})

        yield _sse({"event": "step", "message": "正在生成封面图并部署到 GitHub Pages…"})
        yield _sse({"event": "agent_start", "agent": "publisher", "name": AGENTS["publisher"]})
        pub = agents["publisher"]({"generated_html": pkg.get("generated_html", ""), "selected_topic": topic})
        yield from drain("publisher")
        url = pub.get("html_url", "")
        yield _sse({"event": "agent_done", "agent": "publisher", "summary": {"链接": url}})

        cost = token_summary()["total_cost"]
        yield _sse({"event": "done", "url": url, "cost": round(cost, 4)})

    except Exception as e:
        logger.error(f"Web console generation failed: {e}")
        yield _sse({"event": "error", "message": f"{type(e).__name__}: {str(e)[:300]}"})
    finally:
        reset_emitter(token)
        _running.discard(ip)


if __name__ == "__main__":
    print("Web console: http://localhost:8090/")
    uvicorn.run(app, host="0.0.0.0", port=8090, log_level="info")
```

- [ ] **Step 4: SSE 链测试(注入 fake agents)**

`tests/test_web_console_sse.py`(完整内容):

```python
"""Tests for web_console.generate_stream — event sequence with injected fake agents."""

from web_console import generate_stream


def _frames(gen) -> list:
    import json
    events = []
    for frame in gen:
        assert frame.startswith("data: ")
        events.append(json.loads(frame[6:].strip()))
    return events


def _fake_agents():
    def nav(state):
        return {"dimension_defs": [{"id": "D1"}], "suggested_price": 1.99}

    def gen(state):
        return {"questions_json": {"questions": [{"id": 1}] * 3}}

    def pkg(state):
        return {"generated_html": "<html>x</html>", "packaging_text": "测测你"}

    def pub(state):
        return {"html_url": "https://example.test/d/2026-08-24/"}

    return {"navigator": nav, "generator": gen, "packager": pkg, "publisher": pub}


class TestGenerateStream:
    def test_event_sequence_and_done(self):
        cmd = {"type": "generate", "topic": "测试", "question_count": 5}
        events = _frames(generate_stream(cmd, "test-ip", agents=_fake_agents()))
        kinds = [e["event"] for e in events]
        assert kinds == ["agent_start", "agent_done", "agent_start", "agent_done",
                         "agent_start", "agent_done", "step", "agent_start", "agent_done", "done"]
        assert kinds.count("agent_start") == 4
        done = events[-1]
        assert done["url"] == "https://example.test/d/2026-08-24/"
        assert done["cost"] >= 0

    def test_error_event_on_agent_failure(self):
        cmd = {"type": "generate", "topic": "测试", "question_count": 5}
        agents = _fake_agents()
        def boom(state):
            raise ValueError("模拟失败")
        agents["generator"] = boom
        events = _frames(generate_stream(cmd, "test-ip", agents=agents))
        assert events[-1]["event"] == "error"
        assert "模拟失败" in events[-1]["message"]
```

注意:`generate_stream` 的 finally 里 `_running.discard(ip)` 直接操作模块级 set——测试传入 "test-ip" 会往真实 set 加删,无害。若 import web_console 因缺依赖失败,先装/检查 FastAPI(requirements 已有)。

- [ ] **Step 5: 验证 + 提交**

Run: 两个新测试文件 + 全量套件。
```bash
git add utils/daily_limit.py tests/test_daily_limit.py web_console.py tests/test_web_console_sse.py
git commit -m "feat: web console backend with sse streaming chain and daily ip limit"
```

---

### Task 4: 前端单页 `templates/web_console.html`(Linear 风格)

**Files:**
- Create: `templates/web_console.html`

- [ ] **Step 1: 写前端**

单文件 HTML(内嵌 CSS/JS,无构建)。必须包含:

1. **Linear recipe 视觉**(照抄以下值):Ground #08090A、Surface1 #16171C、Surface2 #1E1F25、发丝边框 rgba(255,255,255,0.06)、正文 #F7F8F8、次文 #9CA3AF、静默文 #6B7280、强调紫 #5E6AD2(仅激活态/状态灯/链接,<5% 像素)、字体栈 Inter/-apple-system(标题 600、-0.02em)、等宽 JetBrains Mono 渲染 agent 流式文本(暗底 #1E1F25、字色 #A78BFA)、圆角 6/12 不超 16、阴影 `0 1px 2px rgba(0,0,0,0.3)`、ease-out 150ms;无弹跳动画、无多彩渐变
2. **布局**:顶部品牌条("小红书 Agent 工作台" + 状态点);主区对话流;底部输入区(输入框 + 生成按钮);空状态三枚示例 chips("做一个人格阴影测试,15题"/"做一个恋爱人格测试"/"做一个MBTI职场测试,20题"),点击填入
3. **回合渲染**:用户消息气泡(右对齐);生成回合块 = 四张 agent 卡片(顺序:navigator→generator→packager→publisher):卡头 = 名称 + 状态灯(灰=等待 / 紫脉冲=运行 / 绿=完成 / 红=失败)+ 耗时;流式文本区(等宽,逐 token append,运行中光标闪烁);agent_done 后附可折叠「结果摘要」JSON(details/summary 原生元素);step 事件渲染为一条细提示行
4. **SSE 消费**:POST /api/generate,fetch + ReadableStream 逐帧解析 `data: {...}\n\n`(EventSource 不支持 POST,必须用 fetch 流式读);done → 展示商品链接(a 标签)+ 成本;error → 错误条 + 状态灯红;429/400 JSON 响应单独处理提示
5. **滚动行为**:新内容自动滚动到底,除非用户上滚超过 120px(显示"回到底部"浮动按钮,Linear 风格发丝边框)
6. **移动端**:<480px 单列、输入区 sticky、卡片内边距收紧
7. 首屏加载即 `fetch('/api/health')`? 不需要——保持最小,页面本身 200 即健康

- [ ] **Step 2: 本地验证**

Run: `"C:/Users/26063/miniconda3/envs/redbook_agent_company/python.exe" -c "import web_console; print('ok')"` 确认模板路径可读;起服 `python web_console.py` 后 curl 首页返回 HTML(实现者用后台进程+curl 验证后关掉)。前端 JS 逻辑无法自动测——实现者须用 Playwright 加载本地页面,验证:chips 填入、发送后事件流渲染(fake 后端?直接连真实后端会花钱)——**替代**:写一个临时 fake SSE 端(monkeypatch 不起效于另一个进程,改用 Playwright route 拦截 /api/generate 返回预置 SSE 帧),断言 UI 渲染出 4 张卡片与流式文本。此验证脚本放 `.superpowers/sdd/2026-08-24-web-console/ui_verify.py`(不入库),报告附结果。

- [ ] **Step 3: 提交**

```bash
git add templates/web_console.html
git commit -m "feat: linear-style streaming web console frontend"
```

---

### Task 5: E2E 真实生成 + 文档

**Files:**
- Modify: `agents/navigator/README.md`(全自动链路节加 Web 控制台入口)
- Modify: `CLAUDE.md`(本地,不提交:当前进度加 Web 控制台)

- [ ] **Step 1: E2E 真实生成一次**

启动 `python web_console.py`(后台)→ 用 curl POST `/api/generate` 抓 SSE 流,验证:四段 agent_start/agent_done、token 帧非空(真实 LLM 流式)、done 含 github.io 链接与成本;再发一次同 IP → 429。记录全部输出。完成后关停服务。

- [ ] **Step 2: 文档**

- navigator README「全自动链路」节补:`Web 控制台: python web_console.py → http://localhost:8090/ 发指令即可流式生成(每IP每日1次)`
- CLAUDE.md 当前进度加 `[x] Web 控制台(Linear 风格流式工作台,每IP每日1次)`

- [ ] **Step 3: 全量测试 + 提交**

Run: 全量 `tests/`(65+8+4+2=79 附近,以实际为准全绿)。
```bash
git add agents/navigator/README.md
git commit -m "docs: web console entry in navigator readme"
```

---

## Self-Review 记录

- **需求覆盖**: 用户两项(交互 HTML 像钉钉发消息给 navigator + 每 agent 思考过程流式 + 后续公开)映射 T1 流式机制/T3 后端/T4 前端/T5 E2E ✓;风格 Linear recipe 值已写入 T4 约束 ✓;每IP每日1次按用户决策 ✓
- **占位符扫描**: 无 TBD;spike 失败路径明确(NEEDS_CONTEXT + 退路方案)✓
- **类型一致性**: `stream_bus.emit/set_emitter/reset_emitter`、`parse_command`、`DailyLimit.allow(ip, today=None)`、`generate_stream(cmd, ip, agents=None)` 在定义与使用处一致 ✓
- **与现有代码兼容**: llm_factory 加 callbacks/streaming 对既有 invoke 语义不变(spike 验证);bot_server 行为不变(抽取等价);daily_limit 独立 json,不碰 .env ✓
