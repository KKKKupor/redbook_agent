# 搜索实现 + 部署统一 + 失败告警 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 `tools/xhs_search.py`(含筛选排序)、trend_hunter 接真实搜索、topic_pool.json 真实产出、quick_test/fix_issues 部署统一到 gh-pages、主流程失败时推送 Fatal 告警。

**Architecture:** 新模块 `tools/xhs_search.py`(解析/缓存/筛选纯函数 + Playwright live 搜索 + CLI);trend_hunter 三级回退接入(缓存→live→LLM先验);xhs_scraper 阈值降至3并与默认池合并写 topic_pool.json;quick_test/fix_issues 的 inline Vercel 部署替换为 `deploy_to_ghpages`;`utils/notifier.format_fatal_message` 纯函数 + main.py except 推送告警。

**Tech Stack:** Python 3.13(conda env `redbook_agent_company`)、Playwright、pytest、loguru。

**Spec:** 本计划即规格(用户已批准设计,2026-08-19);搜索筛选需求:关键词搜索 + 点赞热度排序(本地可靠)+ 一周内(尽力而为,见 Task 1/2 说明)。

## Global Constraints

- ⚠️ **用户规则:git commit 前展示变更摘要并征得同意。** 本会话用户已批准"按计划逐任务提交"(commit message 英文)——各任务 Commit 步骤照此执行。
- 精准修改:只改各任务列出的文件;packager 路径 bug 等无关代码不碰。
- 测试运行:`conda run -n redbook_agent_company python -m pytest <文件> -q`。Task 3 完成后(旧红色测试转绿)才可运行全量 `tests/`;此前只跑聚焦文件。
- 本机 GitHub 需代理:`git config http.proxy http://127.0.0.1:51926`(repo-local,已配置)。
- 中文注释/文档,英文标识符;loguru 日志。
- xhs_search 的 live 部分依赖 `data/xhs_cookies.json`(2026-08-08 导出,可能过期)——过期时走降级路径同样算验证通过,如实记录。

---

### Task 1: `tools/xhs_search.py` 核心纯函数(TDD)

**Files:**
- Create: `tools/xhs_search.py`(parse_notes / parse_likes / filter_notes / read_cache / write_cache + LIKE_RE/UI_BLACKLIST/CACHE_FILE 常量)
- Create: `tests/test_xhs_search_filter.py`(新函数测试)

**Interfaces:**
- Consumes: 现有红色测试 `tests/test_xhs_search.py` 的契约(parse_notes 两测、read_cache 四测、write_cache 两测)
- Produces: `parse_notes(text, max_results=10) -> list[{"title","likes",可选"days_ago"}]`、`parse_likes(raw) -> int`、`filter_notes(notes, min_likes=0, max_age_days=None, top_n=10) -> list(附加 likes_num 字段)`、`read_cache(keyword) -> list|None`、`write_cache(keyword, notes) -> None`

- [ ] **Step 1: 写测试**

`tests/test_xhs_search_filter.py`(完整内容):

```python
"""Tests for xhs_search filtering: parse_likes / filter_notes / time attachment."""

from tools.xhs_search import parse_likes, filter_notes, parse_notes


class TestParseLikes:
    def test_wan(self):
        assert parse_likes("2.3万") == 23000
        assert parse_likes("1万") == 10000

    def test_plain(self):
        assert parse_likes("3924") == 3924
        assert parse_likes("300") == 300

    def test_invalid(self):
        assert parse_likes("") == 0
        assert parse_likes("abc") == 0


class TestFilterNotes:
    def _notes(self):
        return [
            {"title": "冷门", "likes": "300"},
            {"title": "爆款", "likes": "2.3万"},
            {"title": "中等", "likes": "3924"},
        ]

    def test_sorts_by_likes_desc(self):
        out = filter_notes(self._notes())
        assert [n["title"] for n in out] == ["爆款", "中等", "冷门"]
        assert out[0]["likes_num"] == 23000

    def test_min_likes(self):
        out = filter_notes(self._notes(), min_likes=1000)
        assert [n["title"] for n in out] == ["爆款", "中等"]

    def test_top_n(self):
        out = filter_notes(self._notes(), top_n=1)
        assert [n["title"] for n in out] == ["爆款"]

    def test_age_filter_drops_unknown_when_active(self):
        notes = [{"title": "无日期", "likes": "1万"}, {"title": "三天前", "likes": "1万", "days_ago": 3}]
        out = filter_notes(notes, max_age_days=7)
        assert [n["title"] for n in out] == ["三天前"]

    def test_age_filter_keeps_all_when_inactive(self):
        notes = [{"title": "无日期", "likes": "1万"}, {"title": "十天前", "likes": "1万", "days_ago": 10}]
        out = filter_notes(notes)
        assert len(out) == 2


class TestParseNotesTimeAttachment:
    def test_attaches_days_ago_when_time_line_follows_likes(self):
        text = "标题甲\n作者名\n1.2万\n3天前\n下一段内容"
        notes = parse_notes(text)
        assert notes[0]["days_ago"] == 3
```

- [ ] **Step 2: 跑测试确认失败**

Run: `conda run -n redbook_agent_company python -m pytest tests/test_xhs_search.py tests/test_xhs_search_filter.py -q`
Expected: FAIL(ModuleNotFoundError: tools.xhs_search)

- [ ] **Step 3: 写实现**

`tools/xhs_search.py` 核心部分(完整内容,本任务不含 search_notes):

```python
"""小红书搜索结果抓取与缓存。

parse_notes 解析搜索结果页 innerText(标题+点赞,尽力附加时效),
filter_notes 本地筛选排序(点赞热度可靠;一周内为尽力而为——
需笔记带 days_ago 字段,开启时效筛选时无日期笔记被丢弃)。
live 搜索见 search_notes(依赖 data/xhs_cookies.json)。
"""

import json
import re
from datetime import datetime, timedelta
from pathlib import Path

from loguru import logger

CACHE_FILE = Path(__file__).resolve().parent.parent / "data" / "xhs_search_cache.json"
CACHE_TTL_DAYS = 7

LIKE_RE = re.compile(r"^\d+(\.\d+)?万?\+?$")
UI_BLACKLIST = {"首页", "我", "关注", "消息", "评论", "赞", "收藏", "分享", "登录", "更多", "搜索"}
TIME_RE = re.compile(r"^(\d+)\s*(天|小时|分钟|周|月)前$|^昨天$|^刚刚$")

SEARCH_URL = "https://www.xiaohongshu.com/search_result?keyword={kw}&type=51&sort={sort}"


def parse_notes(text: str, max_results: int = 10) -> list:
    """解析搜索结果页 innerText:点赞行向上匹配标题(跳过作者昵称行),黑名单过滤UI词。

    若点赞行下方紧跟时间标记(如"3天前"),尽力附加 days_ago 字段。
    """
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    notes = []
    for i, line in enumerate(lines):
        if not LIKE_RE.match(line):
            continue
        title = None
        for back in (2, 1):  # 优先隔一行(标题\n作者名\n点赞),退而求其次紧邻
            if i >= back:
                cand = lines[i - back]
                if not LIKE_RE.match(cand) and cand not in UI_BLACKLIST and len(cand) >= 3:
                    title = cand
                    break
        if title is None:
            continue
        note = {"title": title, "likes": line}
        days = _parse_time_line(lines[i + 1]) if i + 1 < len(lines) else None
        if days is not None:
            note["days_ago"] = days
        notes.append(note)
        if len(notes) >= max_results:
            break
    return notes


def _parse_time_line(line: str) -> int | None:
    """'3天前'->3,'2小时前'->0,'1周前'->7,'昨天'->1,'刚刚'->0;非时间行->None。"""
    if line in ("昨天",):
        return 1
    if line in ("刚刚",):
        return 0
    m = re.match(r"^(\d+)\s*(天|小时|分钟|周|月)前$", line)
    if not m:
        return None
    n, unit = int(m.group(1)), m.group(2)
    return {"分钟": 0, "小时": 0, "天": n, "周": n * 7, "月": n * 30}[unit]


def parse_likes(raw: str) -> int:
    """'2.3万' -> 23000,'3924' -> 3924;无法解析返回 0。"""
    if not raw:
        return 0
    m = re.match(r"^(\d+(?:\.\d+)?)(万)?\+?$", raw.strip())
    if not m:
        return 0
    num = float(m.group(1))
    if m.group(2):
        num *= 10000
    return int(num)


def filter_notes(notes: list, min_likes: int = 0, max_age_days: int | None = None, top_n: int = 10) -> list:
    """本地筛选排序:按点赞降序(热度),可选点赞下限/时效上限/条数,附加 likes_num 字段。

    时效筛选为尽力而为:仅对带 days_ago 的笔记生效;
    开启 max_age_days 时,无日期笔记被丢弃(时效需求下未知时间不可信)。
    """
    out = []
    for n in notes:
        likes = parse_likes(n.get("likes", ""))
        if likes < min_likes:
            continue
        if max_age_days is not None:
            days = n.get("days_ago")
            if days is None or days > max_age_days:
                continue
        out.append({**n, "likes_num": likes})
    out.sort(key=lambda n: n["likes_num"], reverse=True)
    return out[:top_n]


def read_cache(keyword: str) -> list | None:
    """缓存命中(<7天)返回笔记列表,否则 None。"""
    if not CACHE_FILE.exists():
        return None
    try:
        data = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        entry = data.get(keyword)
        if not entry:
            return None
        scraped = datetime.fromisoformat(entry["scraped_at"])
        if datetime.now() - scraped > timedelta(days=CACHE_TTL_DAYS):
            return None
        return entry["notes"]
    except Exception:
        return None


def write_cache(keyword: str, notes: list) -> None:
    """写入缓存(保留其他关键词条目)。"""
    data = {}
    if CACHE_FILE.exists():
        try:
            data = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    data[keyword] = {"scraped_at": datetime.now().isoformat(), "notes": notes}
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    CACHE_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
```

- [ ] **Step 4: 跑测试确认通过**

Run: `conda run -n redbook_agent_company python -m pytest tests/test_xhs_search.py tests/test_xhs_search_filter.py -q`
Expected: PASS(8 旧 + 10 新)

- [ ] **Step 5: 提交(需用户确认,本会话已预先批准)**

```bash
git add tools/xhs_search.py tests/test_xhs_search_filter.py
git commit -m "feat: xhs search parsing, caching and filtering primitives (TDD)"
```

---

### Task 2: `search_notes` live 搜索 + CLI(手工验证)

**Files:**
- Modify: `tools/xhs_search.py`(追加 search_notes/_search_async/CLI)

**Interfaces:**
- Consumes: Task 1 的 parse_notes;`utils.xhs_auth.XHSBrowser`
- Produces: `search_notes(keyword, sort="popularity_descending", max_results=20) -> list`(失败抛异常);CLI `python -m tools.xhs_search <关键词> [--sort] [--min-likes] [--days] [--top]`

- [ ] **Step 1: 追加实现**

```python
def search_notes(keyword: str, sort: str = "popularity_descending", max_results: int = 20) -> list:
    """Playwright 实时搜索,返回 parse_notes 结果。失败抛异常(调用方降级)。"""
    import asyncio
    return asyncio.run(_search_async(keyword, sort, max_results))


async def _search_async(keyword: str, sort: str, max_results: int) -> list:
    from utils.xhs_auth import XHSBrowser
    async with XHSBrowser(headless=True) as (browser, context, page):
        url = SEARCH_URL.format(kw=keyword, sort=sort)
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(2)
        for _ in range(2):
            await page.evaluate("window.scrollBy(0, 600)")
            await asyncio.sleep(1)
        text = await page.evaluate("() => document.body.innerText")
    notes = parse_notes(text, max_results=max_results)
    logger.info(f"xhs_search: '{keyword}' sort={sort} -> {len(notes)} notes")
    return notes


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="小红书搜索(测试题关键词)")
    ap.add_argument("keyword")
    ap.add_argument("--sort", default="popularity_descending",
                    choices=["general", "popularity_descending", "time_descending"])
    ap.add_argument("--min-likes", type=int, default=0)
    ap.add_argument("--days", type=int, default=None, help="时效上限(天,尽力而为:依赖页面时间标记)")
    ap.add_argument("--top", type=int, default=10)
    args = ap.parse_args()
    notes = search_notes(args.keyword, sort=args.sort)
    filtered = filter_notes(notes, min_likes=args.min_likes, max_age_days=args.days, top_n=args.top)
    print(f"共抓取 {len(notes)} 条,筛选后 {len(filtered)} 条:")
    for n in filtered:
        print(f"  {n['likes_num']:>7}  {n['title']}  (原始: {n['likes']})")
```

- [ ] **Step 2: 手工验证 CLI**

Run: `conda run -n redbook_agent_company python -m tools.xhs_search 测试题 --top 5`
Expected 二选一(都算通过):
- cookies 有效 → 打印若干条标题+点赞,按热度降序
- cookies 过期/被登录墙拦 → 抛异常(记录完整报错),同时用 `--top` 前无输出——如实报告,降级路径有效性由 trend_hunter 测试保证

- [ ] **Step 3: 提交(需用户确认,本会话已预先批准)**

```bash
git add tools/xhs_search.py
git commit -m "feat: live xhs search with sort and cli filters"
```

---

### Task 3: trend_hunter 接真实搜索(红色测试转绿)

**Files:**
- Modify: `agents/trend_hunter/src/main.py`
- Modify: `agents/trend_hunter/README.md`

**Interfaces:**
- Consumes: `tools.xhs_search`(模块级引用!必须 `import tools.xhs_search as xhs_search` 形式——测试通过 monkeypatch 模块属性注入)
- Produces: `get_search_context(topic, max_results=10) -> list|None`、`format_search_context(notes) -> str`、`build_human_message(topic, notes) -> str`;trend_hunter_node 接入

- [ ] **Step 1: 写/跑失败测试**

已有 `tests/test_trend_hunter_search.py`(6 个测试,当前红色)。Run: `conda run -n redbook_agent_company python -m pytest tests/test_trend_hunter_search.py -q`
Expected: FAIL(ImportError: 函数不存在)

- [ ] **Step 2: 写实现**

`agents/trend_hunter/src/main.py` 追加(注意模块级引用):

```python
import tools.xhs_search as xhs_search


def get_search_context(topic: str, max_results: int = 10) -> list | None:
    """三级回退:缓存(7天内)→实时搜索(成功写缓存)→None(LLM先验兜底)。"""
    cached = xhs_search.read_cache(topic)
    if cached:
        logger.info(f"Trend Hunter: cache hit for '{topic}' ({len(cached)} notes)")
        return cached
    try:
        notes = xhs_search.search_notes(topic, sort="popularity_descending", max_results=max_results)
        notes = xhs_search.filter_notes(notes, top_n=max_results)
        if notes:
            xhs_search.write_cache(topic, notes)
            logger.info(f"Trend Hunter: live search '{topic}' -> {len(notes)} notes (cached)")
            return notes
    except Exception as e:
        logger.warning(f"Trend Hunter: live search failed ({e}) — falling back to LLM prior")
    return None


def format_search_context(notes: list) -> str:
    """格式化搜索结果供 prompt 使用,标注为推测性参考。"""
    if not notes:
        return ""
    lines = ["以下为小红书搜索结果中的标题与点赞数(仅供推测性参考,非官方数据):"]
    for n in notes:
        lines.append(f"- {n['title']} (点赞 {n['likes']})")
    return "\n".join(lines)


def build_human_message(topic: str, notes: list | None) -> str:
    """组装 human message:有真实数据时注入,无则仅用选题。"""
    base = f"请分析小红书上关于「{topic}」类付费测试题的爆款结构公式。注意: 只输出JSON。"
    if notes:
        return f"{base}\n\n{format_search_context(notes)}"
    return base
```

`trend_hunter_node` 中,把:

```python
    llm = hunter_llm()
    topic = state.get("selected_topic", "MBTI性格测试")

    logger.info(f"Trend Hunter: analyzing hot patterns for '{topic}'")

    try:
        response = llm.invoke([
            SystemMessage(content=HUNTER_SYSTEM_PROMPT),
            HumanMessage(content=f"请分析小红书上关于「{topic}」类付费测试题的爆款结构公式。注意: 只输出JSON。"),
        ])
```

替换为:

```python
    llm = hunter_llm()
    topic = state.get("selected_topic", "MBTI性格测试")

    logger.info(f"Trend Hunter: analyzing hot patterns for '{topic}'")

    # 三级回退获取真实搜索数据(缓存→live→None),注入 prompt
    notes = get_search_context(topic)
    save("trend_hunter", "search_context.json", {"topic": topic, "notes": notes or []})

    try:
        response = llm.invoke([
            SystemMessage(content=HUNTER_SYSTEM_PROMPT),
            HumanMessage(content=build_human_message(topic, notes)),
        ])
```

其余(save_prompt/save_response/解析/兜底)不动。

`agents/trend_hunter/README.md`:
- 「MVP临时变更」段的"无真实搜索"改为:`- **真实搜索已接入(2026-08-19)**: 三级回退(缓存7天→Playwright live→LLM先验);cookies过期时自动走先验兜底`
- 「已知局限」删去"无真实搜索"相关行(其余保留)

- [ ] **Step 3: 跑测试确认通过**

Run: `conda run -n redbook_agent_company python -m pytest tests/test_trend_hunter_search.py tests/test_xhs_search.py tests/test_xhs_search_filter.py -q`
Expected: PASS(6+8+10)

- [ ] **Step 4: 提交(需用户确认,本会话已预先批准)**

```bash
git add agents/trend_hunter/src/main.py agents/trend_hunter/README.md
git commit -m "feat: trend hunter real search integration with three-level fallback"
```

---

### Task 4: xhs_scraper 阈值降低 + 合并默认池产出 topic_pool.json

**Files:**
- Modify: `tools/xhs_scraper.py`

- [ ] **Step 1: 修改**

1. 顶部追加常量(与 navigator 硬编码池一致):

```python
DEFAULT_TOPIC_POOL = [
    "人格阴影测试", "童年创伤程度测试", "恋爱人格匹配测试",
    "危险人格类型测试", "职场性格测试", "MBTI深度解析",
    "动物塑测试", "去性别化人格测试", "心理压力指数测试",
    "情商测试", "社交人格测试", "抑郁倾向筛查",
]
MIN_TOPICS = 3  # 原为6,过严导致文件从未产出
```

2. `run_scrape` 中 `if len(topics) >= 6:` 改为 `if len(topics) >= MIN_TOPICS:`,保存段改为:

```python
        if len(topics) >= MIN_TOPICS:
            merged = topics + [t for t in DEFAULT_TOPIC_POOL if t not in set(topics)]
            data = {
                "updated_at": datetime.now().isoformat(),
                "topics": merged,
                "scraped_count": len(topics),
            }
```

(merged:真实抓取的排前面,navigator 的 exploit 会优先选中)

- [ ] **Step 2: 手工验证**

Run: `conda run -n redbook_agent_company python -c "from tools.xhs_scraper import run_scrape; run_scrape()"`
Expected: `data/topic_pool.json` 产出(scraped>=3 时);日志如实记录结果。cookies 过期导致 <3 条时文件不产出——同样如实报告,不强行造数据。

- [ ] **Step 3: 提交(需用户确认,本会话已预先批准)**

```bash
git add tools/xhs_scraper.py
git commit -m "feat: lower scraper threshold and merge default pool into topic_pool.json"
```

---

### Task 5: quick_test / fix_issues 部署统一到 gh-pages

**Files:**
- Modify: `quick_test.py`(`deploy_vercel` 函数)
- Modify: `fix_issues.py`(`deploy` 函数)

- [ ] **Step 1: 修改两个函数**

两个文件各有一段相同的 inline Vercel 部署(quick_test.py:26-49 `deploy_vercel`、fix_issues.py:203-226 `deploy`),都替换为:

```python
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
```

(fix_issues.py 的函数名保持 `deploy`,函数体同上,仅 def 行不同。若替换后 `subprocess`/`json`/`re` 在该文件无其他使用处,同步删除相应 import——仅删除因本次改动变无用的。)

- [ ] **Step 2: 验证**

Run: `conda run -n redbook_agent_company python -c "import quick_test; print('quick_test ok')"` 与 `conda run -n redbook_agent_company python -c "import fix_issues; print('fix_issues ok')"`
Expected: 两个 ok(不触发 LLM,仅验证导入与语法)。不跑完整流程(耗 LLM token;deploy_to_ghpages 已在 publisher 链路 E2E 验证过)。

- [ ] **Step 3: 提交(需用户确认,本会话已预先批准)**

```bash
git add quick_test.py fix_issues.py
git commit -m "feat: unify quick_test and fix_issues deploy to github pages"
```

---

### Task 6: 失败告警(TDD)

**Files:**
- Modify: `utils/notifier.py`(追加 `format_fatal_message` 纯函数;头部 import 补 `from datetime import datetime`)
- Modify: `main.py`(`run_once` 的 except 块)
- Create: `tests/test_notifier_fatal.py`

- [ ] **Step 1: 写失败测试**

```python
"""Tests for utils.notifier.format_fatal_message — pure fatal-alert formatting."""

from utils.notifier import format_fatal_message


def _raise_error():
    raise ValueError("模拟失败" * 50)  # 超长信息,验证截断


def test_contains_stage_type_and_info():
    try:
        _raise_error()
    except Exception as e:
        msg = format_fatal_message("daily_workflow", e)
    assert "daily_workflow" in msg
    assert "ValueError" in msg
    assert "模拟失败" in msg
    assert len(msg) < 1500  # 长信息被截断


def test_handles_exception_without_traceback():
    err = ValueError("裸异常")
    msg = format_fatal_message("test_stage", err)
    assert "test_stage" in msg
    assert "ValueError" in msg
    assert "裸异常" in msg
```

- [ ] **Step 2: 跑测试确认失败**

Run: `conda run -n redbook_agent_company python -m pytest tests/test_notifier_fatal.py -q`
Expected: FAIL(ImportError: format_fatal_message 不存在)

- [ ] **Step 3: 写实现**

`utils/notifier.py` 头部:`import os` 后加 `import traceback` 与 `from datetime import datetime`(放在现有 import 区,与 os/httpx 同风格)。

文件末尾追加:

```python
def format_fatal_message(stage: str, error: BaseException) -> str:
    """组装致命错误告警消息体(纯函数,便于单测)。"""
    tb_lines = traceback.format_exception(type(error), error, error.__traceback__)
    tail = "".join(tb_lines).strip().split("\n")[-5:]
    msg = str(error)[:300]
    return (
        f"⏰ 时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"📍 阶段: {stage}\n"
        f"❌ 错误类型: {type(error).__name__}\n"
        f"📝 信息: {msg or '(无信息)'}\n"
        f"```\n{''.join(tail)[:800]}\n```\n"
        f"👉 请查看 logs/app.log;环境类错误(网络/限流)恢复后重跑,代码类错误修复后重启调度。"
    )
```

`main.py` 的 except 块由:

```python
    except Exception as e:
        logger.error(f"Workflow crashed: {e}")
        raise
```

改为:

```python
    except Exception as e:
        logger.error(f"Workflow crashed: {e}")
        # 致命错误告警:推送后照常抛出(不吞异常)
        try:
            from utils.notifier import notifier, format_fatal_message
            notifier.send(
                title="🚨 小红书Agent组致命错误",
                content=format_fatal_message("daily_workflow", e),
                level="fatal",
            )
        except Exception as ne:
            logger.error(f"Fatal alert failed to send: {ne}")
        raise
```

(告警标题含"小红书"关键词,过钉钉过滤器)

- [ ] **Step 4: 跑测试确认通过**

Run: `conda run -n redbook_agent_company python -m pytest tests/test_notifier_fatal.py tests/test_posting_materials.py -q`
Expected: PASS(2+6)

- [ ] **Step 5: 提交(需用户确认,本会话已预先批准)**

```bash
git add utils/notifier.py main.py tests/test_notifier_fatal.py
git commit -m "feat: push fatal alert to dingtalk on workflow crash"
```

---

### Task 7: 收尾验证 + 文档

**Files:**
- Modify: `CLAUDE.md`(本地文件,已 gitignore——更新内容不随 git 提交)

- [ ] **Step 1: 全量测试**

Run: `conda run -n redbook_agent_company python -m pytest tests/ -q`
Expected: **全绿**(此前两个红色文件已于 Task 1/3 转绿;总数约 44 个)。若有失败,报告具体输出,不得声称通过。

- [ ] **Step 2: CLAUDE.md 本地更新(不提交)**

「当前进度」追加已勾选项:`[x] xhs_search 真实搜索(三级回退+筛选)+ topic_pool.json 产出`、`[x] quick_test/fix_issues 部署统一 gh-pages`、`[x] 失败告警(Fatal 推送)`;
「已知全局问题」第4条"无真实数据源"标注:Trend Hunter 已接真实搜索(cookies 有效时),竞品/销售数据仍 mock。

- [ ] **Step 3: 提交(需用户确认,本会话已预先批准)**

CLAUDE.md 不提交(已 gitignore)。本任务无 git 提交;向 controller 报告全量测试结果与文档更新内容。

---

## Self-Review 记录

- **需求覆盖**:用户四项需求(2 搜索+筛选、3 部署统一、4 失败告警)全部映射到任务 ✓;搜索筛选"一周内"为尽力而为,设计已明确并在 CLI 帮助与代码 docstring 说明 ✓
- **占位符扫描**:无 TBD/TODO;代码块完整 ✓
- **类型一致性**:`parse_notes/parse_likes/filter_notes/read_cache/write_cache/search_notes` 签名在 Task1/2 定义、Task3 使用一致;`get_search_context/format_search_context/build_human_message` 签名与现有红色测试的 monkeypatch 预期一致(模块级引用)✓;`format_fatal_message(stage, error)` 与 main.py 使用一致 ✓
- **与现有测试的兼容核对**:test_xhs_search.py 的 SAMPLE_TEXT 在 parse_notes 算法下逐例推演通过(2.3万→也是神了、1745→心理治疗师…、呀嘿/首页被过滤)✓;trend_hunter 测试的 monkeypatch 方式要求模块级 import ✓
