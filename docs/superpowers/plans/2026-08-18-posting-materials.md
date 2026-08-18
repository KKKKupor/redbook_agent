# 发帖备稿链路 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 每日 workflow 自动产出小红书发帖素材(文案+3张截图+建议发布时间),随日报之后单独推送钉钉消息,人工贴稿+定时发布。

**Architecture:** 两个新的独立 utils 模块——`utils/cover_shots.py`(Playwright sync 截图,产出 cover/result/product 三张 PNG)与 `utils/posting_materials.py`(纯函数组装消息+URL推导,可单测);publisher 在部署前截图、部署后推导图片 URL 写回 state;main.py 在日报后调用 `build_message` 推送素材消息。工作流图结构不变。

**Tech Stack:** Python 3.13(conda env `redbook_agent_company`)、Playwright sync API(已随项目安装)、pytest、loguru。

**Spec:** `docs/superpowers/specs/2026-08-18-posting-materials-design.md`

## Global Constraints

- ⚠️ **用户规则:任何 git commit 前必须先向用户展示变更摘要并征得同意;未获同意不得提交。commit message 用英文。** 各任务的 Commit 步骤仅在用户确认后执行。
- 精准修改:不改与本特性无关的代码。**packager 的 `agents/output/` 路径 bug 不在本计划内,禁止顺手修复。**
- 日志用 `loguru`;注释/文档中文,代码标识符英文。
- 无新增依赖(playwright 已安装且 Chromium 已可用)。
- 测试运行方式:`conda run -n redbook_agent_company python -m pytest <path> -q`(base 环境无 pytest,必须用 conda env)。
- 三图规格(验收硬指标):cover.png 750×1000、result.png 750×1000、product.png 1000×1000。

---

### Task 1: `utils/posting_materials.py` + state 字段(TDD)

**Files:**
- Create: `utils/posting_materials.py`
- Create: `tests/test_posting_materials.py`
- Modify: `graph/state.py`(Publishing 段末尾新增 3 字段)

**Interfaces:**
- Consumes: 无(纯函数模块)
- Produces:
  - `build_message(state: dict) -> str | None` — 组装钉钉 markdown 消息体(不含 title);`packaging_text` 缺失/空白时返回 None
  - `derive_image_urls(base_url: str) -> dict` — 返回 `{"cover_image_url", "result_image_url", "product_image_url"}`;空串输入→三个空串

- [ ] **Step 1: 写失败测试**

`tests/test_posting_materials.py`(完整内容):

```python
"""Tests for utils/posting_materials.py — pure message assembly."""

from datetime import datetime

from utils.posting_materials import build_message, derive_image_urls


def _full_state() -> dict:
    return {
        "selected_topic": "MBTI职场性格测试",
        "packaging_text": "测测你是哪种打工人!",
        "html_url": "https://my-app.vercel.app",
        "scheduled_publish_time": datetime(2026, 8, 18, 21, 7),
        "cover_image_url": "https://my-app.vercel.app/cover.png",
        "result_image_url": "https://my-app.vercel.app/result.png",
        "product_image_url": "https://my-app.vercel.app/product.png",
    }


class TestBuildMessage:
    def test_full_state_includes_all_sections(self):
        msg = build_message(_full_state())
        assert "测测你是哪种打工人!" in msg
        assert "08-18 21:07" in msg
        assert "**商品链接**: https://my-app.vercel.app" in msg
        assert "![封面-起始页](https://my-app.vercel.app/cover.png)" in msg
        assert "![封面-结果页](https://my-app.vercel.app/result.png)" in msg
        assert "![商品主图](https://my-app.vercel.app/product.png)" in msg
        assert "定时发布" in msg  # 操作指引存在

    def test_missing_copy_returns_none(self):
        state = _full_state()
        state["packaging_text"] = "   "
        assert build_message(state) is None

    def test_capture_failure_degrades_with_warning(self):
        state = _full_state()
        state["cover_image_url"] = ""
        state["result_image_url"] = ""
        state["product_image_url"] = ""
        msg = build_message(state)
        assert "封面图生成失败" in msg
        assert "![封面" not in msg

    def test_deploy_failure_degrades_with_warning(self):
        state = _full_state()
        state["html_url"] = r"output\deploy\latest\index.html"
        state["cover_image_url"] = ""
        state["result_image_url"] = ""
        state["product_image_url"] = ""
        msg = build_message(state)
        assert "部署失败" in msg
        assert "![封面" not in msg

    def test_missing_publish_time_shows_undecided(self):
        state = _full_state()
        state["scheduled_publish_time"] = None
        msg = build_message(state)
        assert "未定" in msg


class TestDeriveImageUrls:
    def test_bare_vercel_hostname_gets_scheme(self):
        urls = derive_image_urls("my-app.vercel.app")
        assert urls["cover_image_url"] == "https://my-app.vercel.app/cover.png"
        assert urls["result_image_url"] == "https://my-app.vercel.app/result.png"
        assert urls["product_image_url"] == "https://my-app.vercel.app/product.png"

    def test_existing_https_kept_and_trailing_slash_stripped(self):
        urls = derive_image_urls("https://my-app.vercel.app/")
        assert urls["cover_image_url"] == "https://my-app.vercel.app/cover.png"

    def test_empty_returns_empty(self):
        assert derive_image_urls("") == {
            "cover_image_url": "",
            "result_image_url": "",
            "product_image_url": "",
        }
```

- [ ] **Step 2: 运行测试确认失败**

Run: `conda run -n redbook_agent_company python -m pytest tests/test_posting_materials.py -q`
Expected: FAIL(ModuleNotFoundError: utils.posting_materials)

- [ ] **Step 3: 写最小实现**

`utils/posting_materials.py`(完整内容):

```python
"""发帖素材消息组装 — 纯函数,便于单测。"""

from datetime import datetime

from loguru import logger


def derive_image_urls(base_url: str) -> dict:
    """由部署 base URL 推导 3 张图片公网 URL。空串输入→三个空串。

    调用方约定:仅部署成功时传入真实 URL(Vercel hostname 或完整 URL),
    部署失败传空串。不会收到本地路径。
    """
    if not base_url:
        return {"cover_image_url": "", "result_image_url": "", "product_image_url": ""}
    base = base_url.strip().rstrip("/")
    if not base.startswith(("http://", "https://")):
        base = "https://" + base
    return {
        "cover_image_url": f"{base}/cover.png",
        "result_image_url": f"{base}/result.png",
        "product_image_url": f"{base}/product.png",
    }


def _format_publish_time(value) -> str:
    if isinstance(value, datetime):
        return value.strftime("%m-%d %H:%M")
    if isinstance(value, str) and value:
        return value[:16].replace("T", " ")
    return "未定"


def build_message(state: dict) -> str | None:
    """组装钉钉「发帖素材」markdown 消息体(不含 title)。

    输入 workflow 结果 state;packaging_text 缺失/空白时返回 None。
    降级规则(spec 第5节):
    - 部署失败(html_url 非 http) → 链接行替换为部署失败提示,无图片行
    - 部署成功但截图失败(图片 URL 缺失) → 保留链接,图片行替换为配图提示
    """
    copy_text = (state.get("packaging_text") or "").strip()
    if not copy_text:
        return None

    html_url = state.get("html_url") or ""
    cover = state.get("cover_image_url") or ""
    result = state.get("result_image_url") or ""
    product = state.get("product_image_url") or ""

    lines = [
        f"**文案**: {copy_text}",
        f"**建议发布时间**: {_format_publish_time(state.get('scheduled_publish_time'))}",
    ]

    deploy_ok = html_url.startswith(("http://", "https://"))
    if deploy_ok:
        lines.append(f"**商品链接**: {html_url}")
    else:
        lines.append(f"⚠️ **部署失败,商品链接与图片无公网 URL**(本地: {html_url or '无'})")

    lines.append(
        "**操作**: App → 发笔记 → 贴文案 → 传2张封面 → 定时发布 → 橱窗传商品主图 → 关联笔记"
    )

    if cover and result and product:
        lines.append(f"![封面-起始页]({cover})")
        lines.append(f"![封面-结果页]({result})")
        lines.append(f"![商品主图]({product})")
    elif deploy_ok:
        lines.append("⚠️ **封面图生成失败,请自行配图**")

    return "\n\n".join(lines)
```

`graph/state.py` 在 Publishing 段(`actual_publish_time` 之后)新增:

```python
    cover_image_url: str
    result_image_url: str
    product_image_url: str
```

- [ ] **Step 4: 运行测试确认通过**

Run: `conda run -n redbook_agent_company python -m pytest tests/test_posting_materials.py -q`
Expected: PASS(8 个测试全绿)

- [ ] **Step 5: 提交(需用户确认)**

先展示变更摘要(新增 2 文件、state.py 加 3 行),用户同意后:

```bash
git add utils/posting_materials.py tests/test_posting_materials.py graph/state.py
git commit -m "feat: posting materials message builder with TDD tests"
```

---

### Task 2: `utils/cover_shots.py` 截图模块 + CLI

**Files:**
- Create: `utils/cover_shots.py`

**Interfaces:**
- Consumes: 模板 DOM(`#btn-start-new`、`.option-btn`、`#btn-next`、`#results-section`、`#radarChart`,已存在于 `templates/test_template.html`)
- Produces: `capture_cover_images(html_path: Path, out_dir: Path) -> dict` — 返回 `{"cover": Path, "result": Path, "product": Path}`(写入 out_dir 的 png 路径);任一环节失败抛异常(全有或全无),由调用方降级

- [ ] **Step 1: 写模块**

`utils/cover_shots.py`(完整内容):

```python
"""封面/商品图截图 — Playwright 同步 API。

产出三张图(spec 第2节):
  cover.png   750×1000 (3:4)  起始页 — 笔记封面
  result.png  750×1000 (3:4)  结果页顶部(雷达图+人格标签) — 笔记封面
  product.png 1000×1000 (1:1) 起始页 — 商品主图

CLI 手工验证(输出到当前目录):
    python -m utils.cover_shots path/to/test.html
"""

import sys
from pathlib import Path

from loguru import logger
from playwright.sync_api import sync_playwright

VIEWPORT_COVER = {"width": 750, "height": 1000}
VIEWPORT_PRODUCT = {"width": 1000, "height": 1000}
CHART_TIMEOUT_MS = 15000
MAX_ANSWER_LOOP = 200


def _answer_all_questions(page) -> None:
    """点第一个选项 + 下一题,直到结果区可见。防死循环上限 200 步。"""
    for _ in range(MAX_ANSWER_LOOP):
        if page.is_visible("#results-section"):
            return
        page.click("#q-options .option-btn >> nth=0")
        page.click("#btn-next")
    raise TimeoutError(f"答题循环超过 {MAX_ANSWER_LOOP} 步仍未到达结果页")


def capture_cover_images(html_path: Path, out_dir: Path) -> dict:
    """对给定 HTML 截图,产出 cover/result/product 三张 png。失败抛异常。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    html_uri = html_path.resolve().as_uri()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        context = browser.new_context(viewport=VIEWPORT_COVER, locale="zh-CN")
        page = context.new_page()

        # 1) 起始页封面(3:4)—— wait_until="commit" 避免被 Chart.js CDN 拖慢
        page.goto(html_uri, wait_until="commit", timeout=30000)
        page.wait_for_timeout(800)  # 本地文件渲染无需网络
        page.screenshot(path=str(out_dir / "cover.png"))

        # 2) 答题到结果页,截雷达图(3:4)
        page.click("#btn-start-new")
        _answer_all_questions(page)
        try:
            page.wait_for_function("typeof Chart !== 'undefined'", timeout=CHART_TIMEOUT_MS)
        except Exception:
            logger.warning("cover_shots: Chart.js CDN 15s 超时,照常截图(雷达图可能缺失)")
        page.wait_for_timeout(1500)  # 等 Chart 动画完成
        page.locator("#results-section").scroll_into_view_if_needed()
        page.wait_for_timeout(300)
        page.screenshot(path=str(out_dir / "result.png"))

        # 3) 商品主图(1:1)—— 重新以方形视口加载起始页
        page.set_viewport_size(VIEWPORT_PRODUCT)
        page.goto(html_uri, wait_until="commit", timeout=30000)
        page.wait_for_timeout(800)
        page.screenshot(path=str(out_dir / "product.png"))

        browser.close()

    result = {name: out_dir / f"{name}.png" for name in ("cover", "result", "product")}
    logger.info(f"cover_shots: 3 张图已生成 → {out_dir}")
    return result


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python -m utils.cover_shots <html文件路径> [输出目录]")
        sys.exit(1)
    html = Path(sys.argv[1])
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else Path.cwd()
    images = capture_cover_images(html, out)
    for name, path in images.items():
        print(f"{name}: {path}")
```

- [ ] **Step 2: 手工验证 CLI**

Run: `conda run -n redbook_agent_company python -m utils.cover_shots output/test_MBTI职场性格测试.html output/deploy/shots_check`
(用已有的历史 HTML 作输入;若该文件不存在,先用任一 `output/test_*.html`)
Expected: 打印 3 个路径;打开 PNG 检查——起始页/结果页/商品图视觉正常,尺寸分别为 750×1000 / 750×1000 / 1000×1000(用 `Read` 查看图片确认);结果图含雷达图(CDN 正常时)

- [ ] **Step 3: 提交(需用户确认)**

展示变更摘要,用户同意后:

```bash
git add utils/cover_shots.py
git commit -m "feat: playwright cover shots for note covers and product image"
```

---

### Task 3: publisher 集成截图与 URL 推导

**Files:**
- Modify: `agents/publisher/src/main.py`(`publisher_node` 函数体)

**Interfaces:**
- Consumes: `utils.cover_shots.capture_cover_images(html_path: Path, out_dir: Path) -> dict`、`utils.posting_materials.derive_image_urls(base_url: str) -> dict`
- Produces: state 新增返回 `cover_image_url` / `result_image_url` / `product_image_url`(部署失败时均为空串)

- [ ] **Step 1: 修改 `publisher_node`**

将 [publisher main.py](agents/publisher/src/main.py) 中 `publisher_node` 的以下段落:

```python
    deploy_dir = Path(__file__).resolve().parent.parent.parent.parent / "output" / "deploy" / "latest"
    deploy_dir.mkdir(parents=True, exist_ok=True)
    (deploy_dir / "index.html").write_text(html_content, encoding="utf-8")
    (deploy_dir / "vercel.json").write_text('{"version": 2}', encoding="utf-8")

    logger.info("Publisher: deploying to Vercel...")
    url = _deploy_to_vercel(str(deploy_dir))

    if not url:
        url = str(deploy_dir / "index.html")
        logger.warning(f"Publisher: using local path: {url}")

    save("publisher", "deploy_result.json", {"url": url, "topic": topic})
    return {"html_url": url, "xhs_note_id": "", "actual_publish_time": scheduled_time}
```

替换为:

```python
    deploy_dir = Path(__file__).resolve().parent.parent.parent.parent / "output" / "deploy" / "latest"
    deploy_dir.mkdir(parents=True, exist_ok=True)
    (deploy_dir / "index.html").write_text(html_content, encoding="utf-8")
    (deploy_dir / "vercel.json").write_text('{"version": 2}', encoding="utf-8")

    # 封面/商品图截图(部署前生成,随站点一起上线;失败不阻塞主流程)
    try:
        from utils.cover_shots import capture_cover_images
        capture_cover_images(deploy_dir / "index.html", deploy_dir)
        logger.info("Publisher: cover images generated")
    except Exception as e:
        logger.warning(f"Publisher: cover capture failed (posting will degrade): {e}")

    logger.info("Publisher: deploying to Vercel...")
    url = _deploy_to_vercel(str(deploy_dir))

    from utils.posting_materials import derive_image_urls
    if url:
        image_urls = derive_image_urls(url)
    else:
        url = str(deploy_dir / "index.html")
        image_urls = {"cover_image_url": "", "result_image_url": "", "product_image_url": ""}
        logger.warning(f"Publisher: using local path: {url}")

    save("publisher", "deploy_result.json", {"url": url, "topic": topic, **image_urls})
    return {"html_url": url, "xhs_note_id": "", "actual_publish_time": scheduled_time, **image_urls}
```

- [ ] **Step 2: 独立验证 publisher_node**

Run(用历史 HTML 做 state,真实部署一次):

```bash
conda run -n redbook_agent_company python -c "from pathlib import Path; from agents.publisher.src.main import publisher_node; html = Path('output/test_MBTI职场性格测试.html').read_text(encoding='utf-8'); r = publisher_node({'generated_html': html, 'selected_topic': 'MBTI职场性格测试'}); print(r)"
```

Expected: 返回 dict 含 `html_url`(https://...vercel.app)与 3 个图片 URL;手工在浏览器打开 `{html_url}/cover.png`、`{html_url}/result.png`、`{html_url}/product.png` 均能显示(部署目录里 3 张 png 已随站上线)。若部署失败则 3 个 URL 为空串且 html_url 为本地路径——同样符合预期。

- [ ] **Step 3: 提交(需用户确认)**

展示变更摘要,用户同意后:

```bash
git add agents/publisher/src/main.py
git commit -m "feat: publisher generates cover images and exposes image URLs in state"
```

---

### Task 4: main.py 集成素材推送

**Files:**
- Modify: `main.py`(`run_once` 内日报推送之后)

**Interfaces:**
- Consumes: `utils.posting_materials.build_message(state: dict) -> str | None`、`utils.notifier.notifier.send(title, content, level)`

- [ ] **Step 1: 修改 `run_once`**

在 [main.py:130-134](main.py#L130-L134) 的现有日报推送块之后、`return result` 之前插入:

```python
        # Posting material message — separate push after the daily report
        try:
            from utils.posting_materials import build_message
            msg = build_message(result)
            if msg:
                notifier.send(title=f"小红书发帖素材 - {topic}", content=msg, level="info")
        except Exception as e:
            logger.warning(f"Posting material push failed: {e}")
```

(`topic` 变量已在前面 summary 段定义,`notifier` 已在日报段 import——直接复用,不加新 import 到文件头部)

- [ ] **Step 2: 语法与导入检查**

Run: `conda run -n redbook_agent_company python -c "import main; print('ok')"`
Expected: 输出 ok(不触发 run_once,仅验证模块可导入)

- [ ] **Step 3: 提交(需用户确认)**

展示变更摘要,用户同意后:

```bash
git add main.py
git commit -m "feat: push posting material message after daily report"
```

---

### Task 5: 端到端验收 + README 同步

**Files:**
- Modify: `agents/publisher/README.md`(职责与已知局限)
- Modify: `agents/monitor/README.md`(main.py 内联推送的描述)

- [ ] **Step 1: 端到端运行**

Run: `conda run -n redbook_agent_company python main.py`
Expected:
1. 全流程跑完(与改动前一致,含日报推送)
2. 钉钉收到**两条**消息:日报(照旧)+ 「小红书发帖素材」(含文案、建议发布时间、商品链接、3 张图)
3. `output/deploy/latest/` 下存在 cover.png / result.png / product.png
4. 浏览器打开素材消息里的 3 个图片 URL 均正常显示

- [ ] **Step 2: 降级路径抽查(任选其一)**

- 断网/关代理后运行 `python -c` 只调 publisher_node(同 Task 3 Step 2)→ 截图或部署失败时,消息降级提示正确、主流程不中断
- 或直接调 `build_message`(Task 1 测试已覆盖四态,可跳过实际断网)

- [ ] **Step 3: README 同步**

`agents/publisher/README.md`:
- 「职责」增加一行:`- 生成3张截图(笔记封面×2 + 商品主图×1),随站点部署,URL写入state`
- 「状态」行更新为:`**状态**: V1.0 部分实现 — Vercel部署+封面截图已接入workflow;~~小红书橱窗上架~~ (V2.0)`

`agents/monitor/README.md`:
- 「职责」增加:`- 推送「发帖素材」消息(文案+3图+建议发布时间;由 main.py run_once 内联调用 utils/posting_materials)`(该 README 已说明日报由 main.py 内联实现,素材消息同机制)

- [ ] **Step 4: 提交(需用户确认)**

展示变更摘要,用户同意后:

```bash
git add agents/publisher/README.md agents/monitor/README.md
git commit -m "docs: sync publisher and monitor READMEs with posting material feature"
```

---

## Self-Review 记录

- **Spec 覆盖**:spec 第2节三图规格→Task2;第3节 state 字段→Task1;4.1 cover_shots→Task2;4.2 posting_materials→Task1;4.3 publisher→Task3;4.4 main.py→Task4;第5节错误矩阵→Task1 测试(四态)+Task3 降级;第6节测试策略→Task1 TDD + Task2 CLI;第7节验收→Task5;第8节附带项→Global Constraints 明令不实施 ✓
- **占位符扫描**:无 TBD/TODO,所有代码块为完整内容 ✓
- **类型一致性**:`build_message(dict)->str|None`、`derive_image_urls(str)->dict`、`capture_cover_images(Path,Path)->dict` 在 Task1/2 定义与 Task3/4 使用处签名一致;state 字段名 `cover_image_url` 等三处一致 ✓
