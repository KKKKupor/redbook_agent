# gh-pages 部署切换 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publisher 的部署从 `npx vercel` 切换为 GitHub Pages(gh-pages 分支),商品链接与素材图片使用国内可达的 github.io 域名。

**Architecture:** 新模块 `utils/ghpages_deploy.py`——纯函数 `derive_pages_urls`(由 origin remote 推导 Pages URL)与 `deploy_to_ghpages`(临时目录 clone gh-pages → 组装根=最新版、`d/日期/`=当天永久版 → commit → push);publisher 截图后调用,失败沿用现有本地路径降级。state/main.py/素材消息零改动。

**Tech Stack:** Python 3.13(conda env `redbook_agent_company`)、subprocess git、pytest、loguru。

**Spec:** `docs/superpowers/specs/2026-08-18-ghpages-deploy-design.md`

## Global Constraints

- ⚠️ **用户规则:git commit 前展示变更摘要并征得同意。** 本会话用户已批准"按计划逐任务提交"(commit message 用英文)——各任务 Commit 步骤照此执行。
- 精准修改:不改与本特性无关的代码;packager 路径 bug 不在本计划内。
- 日志用 `loguru`;注释/文档中文,代码标识符英文。
- 测试运行:`conda run -n redbook_agent_company python -m pytest <文件> -q`。**严禁运行全量套件**(仓库有两个与本计划无关的红色测试文件)。
- 本机访问 GitHub 需代理:主仓库已配置 `git config http.proxy http://127.0.0.1:51926`;**部署逻辑必须把主仓库的代理与 user.name/user.email 继承到临时仓库**。
- 推送 gh-pages **严禁 force**;首次分支不存在时用 orphan 分支推新分支(远端无此分支,普通 push 即可)。
- 手工验证过的正确 git 序列:临时目录 `git init` → 配代理/身份 → `remote add origin` → `fetch --depth 1 origin gh-pages`(失败=分支不存在)→ `checkout FETCH_HEAD` + `switch -c gh-pages` → 组装 → `add -A` → `commit` → `push origin gh-pages`。
- gh-pages 文件结构:根 = index.html + 3 PNG + `.nojekyll`(最新版);`d/{date_str}/` = 同 4 文件(当天永久版)。**只有 index.html 是必需文件**——PNG 存在才复制(截图失败时仍部署 HTML,让素材消息走"封面图生成失败"降级而非"部署失败")。
- Pages 发布有 1-2 分钟生效延迟;验证 HTTP 200 时用代理 curl 且允许 ~2 分钟重试等待。
- `derive_pages_urls` 域名从 remote 动态解析;日期格式 `YYYY-MM-DD`(`datetime.now().strftime("%Y-%m-%d")`)。

---

### Task 1: `derive_pages_urls` 纯函数(TDD)

**Files:**
- Create: `utils/ghpages_deploy.py`(本任务只实现 `derive_pages_urls` + 空串兜底)
- Create: `tests/test_ghpages_deploy.py`

**Interfaces:**
- Consumes: 无
- Produces: `derive_pages_urls(remote_url: str, date_str: str) -> dict` — 返回 `{"html_url", "cover_image_url", "result_image_url", "product_image_url"}`;remote/date 缺失或解析失败 → 四个空串

- [ ] **Step 1: 写失败测试**

`tests/test_ghpages_deploy.py`(完整内容):

```python
"""Tests for utils/ghpages_deploy.derive_pages_urls — pure URL derivation."""

from utils.ghpages_deploy import derive_pages_urls


class TestDerivePagesUrls:
    def test_https_remote_with_git_suffix(self):
        urls = derive_pages_urls("https://github.com/KKKKupor/redbook_agent.git", "2026-08-18")
        assert urls["html_url"] == "https://KKKKupor.github.io/redbook_agent/d/2026-08-18/"
        assert urls["cover_image_url"] == "https://KKKKupor.github.io/redbook_agent/d/2026-08-18/cover.png"
        assert urls["result_image_url"] == "https://KKKKupor.github.io/redbook_agent/d/2026-08-18/result.png"
        assert urls["product_image_url"] == "https://KKKKupor.github.io/redbook_agent/d/2026-08-18/product.png"

    def test_https_remote_without_git_suffix(self):
        urls = derive_pages_urls("https://github.com/KKKKupor/redbook_agent", "2026-08-19")
        assert urls["html_url"] == "https://KKKKupor.github.io/redbook_agent/d/2026-08-19/"

    def test_ssh_remote(self):
        urls = derive_pages_urls("git@github.com:KKKKupor/redbook_agent.git", "2026-08-18")
        assert urls["html_url"] == "https://KKKKupor.github.io/redbook_agent/d/2026-08-18/"

    def test_empty_remote_returns_empty(self):
        assert derive_pages_urls("", "2026-08-18") == {
            "html_url": "",
            "cover_image_url": "",
            "result_image_url": "",
            "product_image_url": "",
        }

    def test_unparseable_remote_returns_empty(self):
        assert derive_pages_urls("not-a-remote", "2026-08-18")["html_url"] == ""
        assert derive_pages_urls("https://example.com/a/b.git", "2026-08-18")["html_url"] == ""

    def test_missing_date_returns_empty(self):
        assert derive_pages_urls("https://github.com/KKKKupor/redbook_agent.git", "")["html_url"] == ""
```

- [ ] **Step 2: 运行测试确认失败**

Run: `conda run -n redbook_agent_company python -m pytest tests/test_ghpages_deploy.py -q`
Expected: FAIL(ModuleNotFoundError: utils.ghpages_deploy)

- [ ] **Step 3: 写最小实现**

`utils/ghpages_deploy.py`(本任务仅前两部分):

```python
"""GitHub Pages 部署 — 把生成的 HTML+截图发布到 gh-pages 分支。"""

import re
from pathlib import Path

from loguru import logger

_EMPTY_URLS = {
    "html_url": "",
    "cover_image_url": "",
    "result_image_url": "",
    "product_image_url": "",
}

_REMOTE_PATTERNS = [
    re.compile(r"https?://github\.com/(?P<user>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?/?$"),
    re.compile(r"git@github\.com:(?P<user>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?$"),
]


def derive_pages_urls(remote_url: str, date_str: str) -> dict:
    """由 origin remote URL 推导 GitHub Pages 链接。解析失败返回全空串。"""
    if not remote_url or not date_str:
        return dict(_EMPTY_URLS)
    user = repo = None
    for pat in _REMOTE_PATTERNS:
        m = pat.match(remote_url.strip())
        if m:
            user, repo = m.group("user"), m.group("repo")
            break
    if not user or not repo:
        return dict(_EMPTY_URLS)

    day = f"https://{user}.github.io/{repo}/d/{date_str}"
    return {
        "html_url": day + "/",
        "cover_image_url": f"{day}/cover.png",
        "result_image_url": f"{day}/result.png",
        "product_image_url": f"{day}/product.png",
    }
```

- [ ] **Step 4: 运行测试确认通过**

Run: `conda run -n redbook_agent_company python -m pytest tests/test_ghpages_deploy.py -q`
Expected: PASS(6 个测试全绿)

- [ ] **Step 5: 提交(需用户确认,本会话已预先批准)**

```bash
git add utils/ghpages_deploy.py tests/test_ghpages_deploy.py
git commit -m "feat: derive github pages URLs from origin remote (TDD)"
```

---

### Task 2: `deploy_to_ghpages` 部署函数 + 真实部署验证

**Files:**
- Modify: `utils/ghpages_deploy.py`(追加部署部分)

**Interfaces:**
- Consumes: Task 1 的 `derive_pages_urls`;主仓库配置(`git config http.proxy`、`user.name`、`user.email`、remote origin)
- Produces: `deploy_to_ghpages(deploy_dir: Path, date_str: str) -> dict` — 成功返回 4 个 URL;index.html 缺失/remote 缺失/git 失败抛异常;**PNG 缺失不抛异常(存在才复制)**

- [ ] **Step 1: 追加实现**

在 `utils/ghpages_deploy.py` 中追加(import 头部补充 `shutil`、`subprocess`、`tempfile`):

```python
REPO_ROOT = Path(__file__).resolve().parent.parent


def _git(repo_dir: Path, *args: str) -> str:
    """在指定仓库目录执行 git 命令,返回 stdout。失败抛异常。"""
    result = subprocess.run(
        ["git", "-C", str(repo_dir), *args],
        capture_output=True, text=True, timeout=180,
        encoding="utf-8", errors="replace",
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()[:300]}")
    return result.stdout.strip()


def _git_config(key: str) -> str:
    """读取主仓库配置(proxy/user.name/user.email),缺失返回空串。"""
    try:
        return _git(REPO_ROOT, "config", "--get", key)
    except RuntimeError:
        return ""


def deploy_to_ghpages(deploy_dir: Path, date_str: str) -> dict:
    """部署 deploy_dir(HTML+截图)到 gh-pages:根=最新版,d/{date}=当天永久版。

    仅 index.html 必需;3 张 PNG 存在才复制(截图失败时仍部署 HTML,
    由调用方把图片 URL 置空走"封面图生成失败"降级)。失败抛异常。
    """
    index = deploy_dir / "index.html"
    if not index.exists():
        raise FileNotFoundError(f"{index} 不存在,无法部署")

    origin = _git_config("remote.origin.url") or _git(REPO_ROOT, "remote", "get-url", "origin")
    if not origin:
        raise RuntimeError("未配置 git remote origin")

    tmp = Path(tempfile.mkdtemp(prefix="ghpages_"))
    try:
        _git(tmp, "init")
        proxy = _git_config("http.proxy")
        if proxy:
            _git(tmp, "config", "http.proxy", proxy)
        _git(tmp, "config", "user.name", _git_config("user.name") or "Kiran")
        _git(tmp, "config", "user.email", _git_config("user.email") or "kuporlink@gmail.com")
        _git(tmp, "remote", "add", "origin", origin)

        # 分支存在 → 在其上追加提交;不存在(首次)→ orphan 分支直接推
        try:
            _git(tmp, "fetch", "--depth", "1", "origin", "gh-pages")
            _git(tmp, "checkout", "-q", "FETCH_HEAD")
            _git(tmp, "switch", "-q", "-c", "gh-pages")
        except RuntimeError:
            _git(tmp, "checkout", "-q", "--orphan", "gh-pages")

        # 组装:根=最新版,d/{date}/=当天永久版
        day = tmp / "d" / date_str
        day.mkdir(parents=True, exist_ok=True)
        for name in ("index.html", "cover.png", "result.png", "product.png"):
            src = deploy_dir / name
            if not src.exists():
                continue
            shutil.copy(src, tmp / name)
            shutil.copy(src, day / name)
        (tmp / ".nojekyll").touch()

        _git(tmp, "add", "-A")
        _git(tmp, "commit", "-m", f"deploy {date_str}")
        _git(tmp, "push", "origin", "gh-pages")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    urls = derive_pages_urls(origin, date_str)
    logger.info(f"ghpages_deploy: {date_str} -> {urls['html_url']}")
    return urls
```

- [ ] **Step 2: 真实部署验证**

Run:

```bash
conda run -n redbook_agent_company python -c "from pathlib import Path; from utils.ghpages_deploy import deploy_to_ghpages; print(deploy_to_ghpages(Path('output/deploy/latest'), '2026-08-18'))"
```

Expected: 打印 4 个 URL 且无异常;随后用代理 curl 验证(允许 ~2 分钟重试等待 Pages 生效):

```bash
curl -sS -o /dev/null -w "%{http_code}\n" -x http://127.0.0.1:51926 "https://KKKKupor.github.io/redbook_agent/d/2026-08-18/"
curl -sS -o /dev/null -w "%{http_code}\n" -x http://127.0.0.1:51926 "https://KKKKupor.github.io/redbook_agent/"
```

Expected: 两个 200;`git ls-remote origin gh-pages` 可见新提交(分支存在时历史是追加,无 force)

- [ ] **Step 3: 提交(需用户确认,本会话已预先批准)**

```bash
git add utils/ghpages_deploy.py
git commit -m "feat: deploy to gh-pages branch with daily permanent directory"
```

---

### Task 3: publisher 切换部署调用

**Files:**
- Modify: `agents/publisher/src/main.py`

**Interfaces:**
- Consumes: `utils.ghpages_deploy.deploy_to_ghpages(deploy_dir: Path, date_str: str) -> dict`
- Produces: state 返回不变(`html_url` + 3 图片 URL);失败降级不变(本地路径 + 3 空串)

- [ ] **Step 1: 修改 `publisher_node` 与模块头部**

1. 删除函数 `_deploy_to_vercel`(整段,含其内部 `import time/json/re` 与文件顶部 `import subprocess`——删除后无其他使用处)
2. 删除写 `vercel.json` 的两行(部署段与 `_deploy_to_vercel` 内部)
3. 部署段替换为:

```python
    logger.info("Publisher: deploying to GitHub Pages...")
    from datetime import datetime
    date_str = datetime.now().strftime("%Y-%m-%d")
    try:
        from utils.ghpages_deploy import deploy_to_ghpages
        urls = deploy_to_ghpages(deploy_dir, date_str)
        url = urls["html_url"]
        if capture_ok:
            image_urls = {k: urls[k] for k in ("cover_image_url", "result_image_url", "product_image_url")}
        else:
            image_urls = {"cover_image_url": "", "result_image_url": "", "product_image_url": ""}
            logger.warning("Publisher: deploy ok but capture failed — image URLs left empty for message degradation")
    except Exception as e:
        logger.warning(f"Publisher: deploy failed ({e}) — using local path")
        url = str(deploy_dir / "index.html")
        image_urls = {"cover_image_url": "", "result_image_url": "", "product_image_url": ""}

    save("publisher", "deploy_result.json", {"url": url, "topic": topic, **image_urls})
    return {"html_url": url, "xhs_note_id": "", "actual_publish_time": scheduled_time, **image_urls}
```

注意:截图 try/except(含 `capture_ok` 与陈旧 PNG 清理)保持原样不动;`from utils.posting_materials import derive_image_urls` 相关旧部署段全部由上述代码替换。

- [ ] **Step 2: 独立验证 publisher_node**

Run(真实部署一次,与 Task 2 同日期会追加 gh-pages 提交,无妨):

```bash
conda run -n redbook_agent_company python -c "from pathlib import Path; from agents.publisher.src.main import publisher_node; html = Path('output/deploy/latest/index.html').read_text(encoding='utf-8'); r = publisher_node({'generated_html': html, 'selected_topic': '人格阴影测试'}); print(r)"
```

Expected: 返回 `html_url` 为 `https://KKKKupor.github.io/redbook_agent/d/<今日>/`、3 个图片 URL 同域名;代理 curl 验证 html_url 与 cover.png 返回 200。若代理关闭导致 push 失败 → 降级为本地路径 + 3 空串,同样符合预期(记录观察到的行为)。

- [ ] **Step 3: 提交(需用户确认,本会话已预先批准)**

```bash
git add agents/publisher/src/main.py
git commit -m "feat: publisher deploys to github pages instead of vercel"
```

---

### Task 4: 端到端验收 + README 同步

**Files:**
- Modify: `agents/publisher/README.md`

- [ ] **Step 1: 端到端运行**

Run: `conda run -n redbook_agent_company python main.py`
Expected:
1. 全流程跑完;日志中 Publisher 显示 `deploying to GitHub Pages` 与 github.io URL
2. 钉钉两条消息;素材消息含 github.io 商品链接与 3 张图 URL
3. 代理 curl 当天专属 URL 与根 URL 均 200(Pages 生效后)
4. 手机流量打开当天专属链接正常、点"开始测试"题目在顶部(模板滚动修复已验证)

- [ ] **Step 2: 降级路径抽查**

Run(模拟 push 失败:临时把主仓库代理指向不可达端口,跑完恢复):

```bash
git config http.proxy http://127.0.0.1:9 && conda run -n redbook_agent_company python -c "from pathlib import Path; from agents.publisher.src.main import publisher_node; html = Path('output/deploy/latest/index.html').read_text(encoding='utf-8'); print(publisher_node({'generated_html': html, 'selected_topic': '降级测试'}))"; git config http.proxy http://127.0.0.1:51926
```

Expected: 返回本地路径 html_url + 3 空图片 URL,无崩溃。(注意末尾恢复代理配置,勿遗漏。)

- [ ] **Step 3: README 同步**

`agents/publisher/README.md`:
- 「状态」行改为:`**状态**: V1.0 部分实现 — GitHub Pages 部署已接入 workflow(gh-pages 分支:根=最新版,d/日期/=当天永久版);~~小红书橱窗上架~~ (V2.0)`
- 「职责」增加:`- 部署HTML+3张截图到GitHub Pages(gh-pages分支),URL写入state`
- 「已知局限」增加:`- 部署依赖本机代理可用(git http.proxy)与GitHub凭据;失败时降级本地路径、素材消息提示"部署失败"` 和 `- GitHub Pages发布有1-2分钟生效延迟`
- 保留原 Vercel 相关段落,但加一行标注:`> Vercel 部署已于 2026-08-18 移除(vercel.app 域名国内不可达)。恢复路径:git revert <移除commit> 并还原 _deploy_to_vercel(见 git 历史)。`

- [ ] **Step 4: 提交(需用户确认,本会话已预先批准)**

```bash
git add agents/publisher/README.md
git commit -m "docs: sync publisher README with github pages deployment"
```

---

## Self-Review 记录

- **Spec 覆盖**:spec 4.1 derive_pages_urls/deploy_to_ghpages→Task1/2;4.2 publisher 修改(删 _deploy_to_vercel、不写 vercel.json)→Task3;4.3 README→Task4;第5节错误矩阵→Task2(PNG可选复制)+Task3(降级)+Task4 Step2(降级抽查);第6节测试→Task1 TDD+Task2/4 真实验证;第7节用户操作已在前置手工环节完成 ✓
- **占位符扫描**:无 TBD/TODO;所有代码块完整 ✓
- **类型一致性**:`derive_pages_urls(str,str)->dict`、`deploy_to_ghpages(Path,str)->dict` 在 Task1/2 定义与 Task3 使用一致;`capture_ok`/`image_urls` 字段名与现有代码一致 ✓
