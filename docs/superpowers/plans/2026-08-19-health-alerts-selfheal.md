# 运行健康告警 + 自愈一期 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 全链路 12 处降级点接入 `utils/health` 健康登记,降级时逐条实时推送钉钉;致命错误增加错误分类与 REVIEW_MODE 下 Git 留痕。

**Architecture:** 新模块 `utils/health.py`(note/reset/summary/classify_error/build_alert_message);各 agent 现有 except/兜底分支加一行 `health.note(...)` 不改变行为;main.py 运行开始 reset、崩溃时分类+条件留痕。

**Tech Stack:** Python 3.13(conda env `redbook_agent_company`)、pytest、loguru、GitPython(仅 REVIEW_MODE 留痕路径)。

**Spec:** `docs/superpowers/specs/2026-08-19-health-alerts-selfheal-design.md`

## Global Constraints

- ⚠️ **用户规则:git commit 前展示变更摘要并征得同意。** 本会话用户已批准"按计划逐任务提交"(commit message 英文)——各任务 Commit 步骤照此执行。
- **Git 留痕仅 REVIEW_MODE=true 时自动执行**(用户明确豁免该场景);生产模式严禁自动 commit。
- 精准修改:各接线点**只加一行 health.note 调用与必要 import**,不得改变现有降级行为/返回值/日志格式;packager 路径 bug 等无关代码不碰。
- 测试运行:优先 `"C:/Users/26063/miniconda3/envs/redbook_agent_company/python.exe" -m pytest <文件> -q`(conda run 在此环境偶发 plugin 错误,二选一,报错时换直连)。
- 中文注释/文档,英文标识符;loguru 日志。
- 推送标题必须含"小红书"(钉钉过滤器);降级提醒 level="warning",致命 level="fatal"。

---

### Task 1: `utils/health.py` 核心(TDD)

**Files:**
- Create: `utils/health.py`
- Create: `tests/test_health.py`
- Create: `tests/test_classify_error.py`

**Interfaces:**
- Produces:
  - `note(node: str, kind: str, detail: str = "") -> None`(记录+立即推送;同 (node,kind) 每运行一次;每运行上限 10 条;推送失败仅日志)
  - `reset() -> None` / `summary() -> list[dict]`
  - `build_alert_message(node, kind, detail) -> str`(纯函数,detail 截断 300)
  - `classify_error(error: BaseException) -> str`("environmental" | "code" | "unknown")

- [ ] **Step 1: 写失败测试**

`tests/test_health.py`(完整内容):

```python
"""Tests for utils.health — note/dedup/cap/reset/message building."""

from utils import health


class TestBuildAlertMessage:
    def test_contains_node_kind_detail(self):
        msg = health.build_alert_message("navigator", "topic_pool_hardcoded", "文件缺失")
        assert "navigator" in msg
        assert "topic_pool_hardcoded" in msg
        assert "文件缺失" in msg

    def test_detail_truncated(self):
        msg = health.build_alert_message("x", "y", "长" * 500)
        assert len(msg) < 400


class TestNoteDedupAndCap:
    def test_same_node_kind_pushes_once_per_run(self, monkeypatch):
        health.reset()
        calls = {"v": 0}
        monkeypatch.setattr(health.notifier, "send", lambda **kw: calls.update(v=calls["v"] + 1))
        health.note("navigator", "llm_parse_failed", "a")
        health.note("navigator", "llm_parse_failed", "b")
        assert calls["v"] == 1
        assert len(health.summary()) == 1

    def test_cap_at_ten_per_run(self, monkeypatch):
        health.reset()
        calls = {"v": 0}
        monkeypatch.setattr(health.notifier, "send", lambda **kw: calls.update(v=calls["v"] + 1))
        for i in range(15):
            health.note(f"node{i}", "kind", "")
        assert calls["v"] == 10

    def test_reset_clears_dedup(self, monkeypatch):
        health.reset()
        calls = {"v": 0}
        monkeypatch.setattr(health.notifier, "send", lambda **kw: calls.update(v=calls["v"] + 1))
        health.note("a", "b", "")
        health.reset()
        health.note("a", "b", "")
        assert calls["v"] == 2

    def test_push_failure_does_not_raise(self, monkeypatch):
        health.reset()
        def boom(**kw):
            raise RuntimeError("webhook down")
        monkeypatch.setattr(health.notifier, "send", boom)
        health.note("a", "b", "")  # 不得抛出
        assert len(health.summary()) == 1
```

`tests/test_classify_error.py`(完整内容):

```python
"""Tests for utils.health.classify_error."""

import json

from utils.health import classify_error


class TestClassifyError:
    def test_timeout_is_environmental(self):
        assert classify_error(TimeoutError("timed out")) == "environmental"

    def test_connection_is_environmental(self):
        assert classify_error(ConnectionError("connection reset")) == "environmental"

    def test_oserror_is_environmental(self):
        assert classify_error(OSError("no space left on device")) == "environmental"

    def test_message_pattern_is_environmental(self):
        assert classify_error(RuntimeError("429 Too Many Requests")) == "environmental"
        assert classify_error(RuntimeError("dns resolution failed")) == "environmental"

    def test_keyerror_is_code(self):
        assert classify_error(KeyError("missing")) == "code"

    def test_json_decode_is_code(self):
        try:
            json.loads("{bad")
        except Exception as e:
            assert classify_error(e) == "code"

    def test_valueerror_is_code(self):
        assert classify_error(ValueError("Failed to parse JSON")) == "code"

    def test_unknown(self):
        assert classify_error(RuntimeError("something weird")) == "unknown"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `"C:/Users/26063/miniconda3/envs/redbook_agent_company/python.exe" -m pytest tests/test_health.py tests/test_classify_error.py -q`
Expected: FAIL(ModuleNotFoundError: utils.health)

- [ ] **Step 3: 写实现**

`utils/health.py`(完整内容):

```python
"""运行健康登记与错误分类 — 全链路降级/兜底点统一在此记录,逐条实时推送钉钉提醒。"""

from loguru import logger

from utils.notifier import notifier

_MAX_ALERTS_PER_RUN = 10
_seen: set = set()   # (node, kind) 每运行去重
_count = 0


def reset() -> None:
    """每运行开始调用,清空去重与计数。"""
    global _seen, _count
    _seen = set()
    _count = 0


def build_alert_message(node: str, kind: str, detail: str = "") -> str:
    """组装降级提醒消息体(纯函数)。"""
    return (
        f"**环节**: {node}  \n"
        f"**降级类型**: {kind}  \n"
        f"**详情**: {detail[:300] or '(无详情)'}"
    )


def note(node: str, kind: str, detail: str = "") -> None:
    """记录一次降级并立即推送钉钉提醒。

    同一 (node, kind) 每运行只推一次;每运行最多 _MAX_ALERTS_PER_RUN 条;
    推送失败仅日志,绝不抛出(不得影响业务降级路径)。
    """
    global _count
    key = (node, kind)
    if key in _seen:
        logger.debug(f"health: 重复降级 {node}/{kind} 已提醒,跳过")
        return
    if _count >= _MAX_ALERTS_PER_RUN:
        logger.warning(f"health: 本次运行降级提醒已达上限 {_MAX_ALERTS_PER_RUN} 条")
        return
    _seen.add(key)
    _count += 1
    try:
        notifier.send(
            title="⚠️ 小红书Agent降级提醒",
            content=build_alert_message(node, kind, detail),
            level="warning",
        )
    except Exception as e:
        logger.error(f"health: 提醒推送失败: {e}")


def summary() -> list:
    """本次运行全部降级记录(供日志与测试)。"""
    return [{"node": k[0], "kind": k[1]} for k in sorted(_seen)]


# ═══ 错误分类(自愈一期:环境类 vs 代码逻辑类) ═══

_ENV_TYPES = (TimeoutError, ConnectionError, OSError)
_ENV_MSG_PATTERNS = (
    "timeout", "timed out", "connection", "429", "rate limit",
    "disk full", "no space", "dns", "resolve",
)
_CODE_TYPES = (KeyError, TypeError, ValueError, ImportError, AttributeError, IndexError)


def classify_error(error: BaseException) -> str:
    """分类致命错误:environmental(网络/限流/磁盘,恢复后重跑)| code(代码逻辑,需修复)| unknown。"""
    if isinstance(error, _ENV_TYPES):
        return "environmental"
    msg = str(error).lower()
    if any(p in msg for p in _ENV_MSG_PATTERNS):
        return "environmental"
    if isinstance(error, _CODE_TYPES):
        return "code"
    return "unknown"
```

注意:`test_json_decode_is_code` 要求 json.JSONDecodeError → code,而 JSONDecodeError 是 ValueError 子类 → _CODE_TYPES 已含 ValueError ✓。

- [ ] **Step 4: 跑测试确认通过**

Run: `"C:/Users/26063/miniconda3/envs/redbook_agent_company/python.exe" -m pytest tests/test_health.py tests/test_classify_error.py -q`
Expected: PASS(4+8=12)

- [ ] **Step 5: 提交(需用户确认,本会话已预先批准)**

```bash
git add utils/health.py tests/test_health.py tests/test_classify_error.py
git commit -m "feat: health registry with realtime degradation alerts and error classification (TDD)"
```

---

### Task 2: 12 处降级点接线

**Files:**
- Modify: `agents/navigator/src/main.py`、`agents/trend_hunter/src/main.py`、`agents/generator/src/main.py`、`agents/packager/src/main.py`、`agents/publisher/src/main.py`、`agents/reviewer/src/main.py`、`agents/data_analyst/src/main.py`、`tools/sales_tools.py`

**Interfaces:**
- Consumes: `utils.health.note(node, kind, detail)`
- Produces: 无新接口;各点行为不变

- [ ] **Step 1: 逐点加一行(先读每个落点上下文再改)**

每个文件顶部 import 区加 `from utils.health import note`(或 `import utils.health as health` 后调用 `health.note`,二选一保持文件内一致),然后在以下落点的现有 except/兜底分支内**加一行**(不得改任何现有逻辑):

1. `agents/navigator/src/main.py` — 话题池加载块:若 `POOL_FILE.exists()` 为假或加载失败/不足6条(即没有真实池可用)加:`note("navigator", "topic_pool_hardcoded", "data/topic_pool.json 缺失或不足,使用硬编码话题池")`(放于加载块之后的判断处,用一个 `pool_loaded` 标志,成功加载置 True,块后 `if not pool_loaded: note(...)`)
2. 同文件 — `except (json.JSONDecodeError, Exception)` 决策解析兜底块内加:`note("navigator", "llm_parse_failed", str(e)[:200])`
3. `agents/trend_hunter/src/main.py` — node 内 `notes = get_search_context(topic)` 之后:`if notes is None: note("trend_hunter", "search_fallback", "cookies过期或网络失败,使用LLM先验")`
4. 同文件 — `except Exception`(insights 解析兜底)内加:`note("trend_hunter", "llm_parse_failed", str(e)[:200])`
5. `agents/generator/src/main.py` — `if not dimensions:` 通用维度兜底内加:`note("generator", "dimension_fallback", "dimension_defs 缺失,使用通用维度")`
6. 同文件 — 找到生成批次 LLM 调用外层 `except Exception as e:`(约 175 行,先读上下文确认它确实包裹批次生成),加:`note("generator", "generation_failed", str(e)[:200])`
7. `agents/packager/src/main.py` — `_gen_copy` 中两处返回 `FALLBACK_COPY` 的分支(首推版本块不合格 + except 兜底)各加:`note("packager", "copy_fallback", "首推版本文案不合格或异常,使用兜底文案")`
8. `agents/publisher/src/main.py` — 截图 except 内(已有 capture_ok=False 与陈旧图清理)加:`note("publisher", "capture_failed", str(e)[:200])`
9. 同文件 — 部署 except 内加:`note("publisher", "deploy_failed", str(e)[:200])`
10. `agents/reviewer/src/main.py` — `except Exception`(评分解析 fallback)内加:`note("reviewer", "llm_parse_failed", str(e)[:200])`
11. `agents/data_analyst/src/main.py` — `except Exception`(LLM 分析调用兜底)内加:`note("data_analyst", "analytics_failed", str(e)[:200])`(先读该处确认是分析 LLM 调用兜底)
12. `tools/sales_tools.py` — `get_competitor_trend` 与 `time_series_forecast` 两个 mock 函数返回前各加:`note("data", "mock_data", "该数据工具为 mock,无真实数据源")`

- [ ] **Step 2: 验证**

1. 全量测试不回归:`"C:/Users/26063/miniconda3/envs/redbook_agent_company/python.exe" -m pytest tests/ -q`(期望 47+12=59 passed;若 sales_tools/agent 模块 import 链触发健康模块副作用,输出须 pristine)
2. 推送验证(真实钉钉,用户可见):`"C:/Users/26063/miniconda3/envs/redbook_agent_company/python.exe" -c "from utils.health import note; note('验证', 'manual_test', '接线验证,收到请忽略')"` → 报告钉钉返回 errcode

- [ ] **Step 3: 提交(需用户确认,本会话已预先批准)**

```bash
git add agents/navigator/src/main.py agents/trend_hunter/src/main.py agents/generator/src/main.py agents/packager/src/main.py agents/publisher/src/main.py agents/reviewer/src/main.py agents/data_analyst/src/main.py tools/sales_tools.py
git commit -m "feat: wire health notes into 12 degradation sites across agents"
```

---

### Task 3: main.py 接线(reset + 分类 + 条件留痕)

**Files:**
- Modify: `main.py`

- [ ] **Step 1: 修改**

1. `run_once` 中 `run_id = start_run()` 之后加:

```python
    from utils.health import reset as health_reset
    health_reset()
```

2. `run_once` 的 except 块由当前内容改为:

```python
    except Exception as e:
        logger.error(f"Workflow crashed: {e}")
        # 错误分类 + REVIEW_MODE 下 Git 留痕(生产模式不自动提交,尊重红线)
        from utils.health import classify_error
        error_class = classify_error(e)
        commit_hash = ""
        if REVIEW_MODE:
            try:
                from utils.git_ops import git_ops
                commit_hash = git_ops.auto_commit()
            except Exception as ge:
                logger.error(f"Auto-commit for healing failed: {ge}")
        # 致命错误告警:推送后照常抛出(不吞异常)
        try:
            from utils.notifier import notifier, format_fatal_message
            content = format_fatal_message("daily_workflow", e)
            content += f"\n🧪 错误分类: {error_class}"
            content += f"\n🔐 Git留痕: {commit_hash[:12] if commit_hash else '未执行(REVIEW_MODE=false 或失败)'}"
            notifier.send(
                title="🚨 小红书Agent组致命错误",
                content=content,
                level="fatal",
            )
        except Exception as ne:
            logger.error(f"Fatal alert failed to send: {ne}")
        raise
```

(REVIEW_MODE 已在文件顶部 run_once 的 `from utils.review import start_run, REVIEW_MODE` 导入 ✓)

- [ ] **Step 2: 验证**

1. 导入检查:`"C:/Users/26063/miniconda3/envs/redbook_agent_company/python.exe" -c "import main; print('ok')"`
2. 全量测试:`"C:/Users/26063/miniconda3/envs/redbook_agent_company/python.exe" -m pytest tests/ -q`(不回归)
3. 分类+告警路径冒烟(不触发完整流程,验证 Fatal 组装):`"C:/Users/26063/miniconda3/envs/redbook_agent_company/python.exe" -c "from utils.health import classify_error; from utils.notifier import format_fatal_message; e = KeyError('x'); print(classify_error(e)); print('missing_key' in format_fatal_message('test', e))"` → 输出 code 与 True

- [ ] **Step 3: 提交(需用户确认,本会话已预先批准)**

```bash
git add main.py
git commit -m "feat: health reset and classified fatal alert with review-mode git snapshot"
```

---

### Task 4: 文档同步 + 全量收尾

**Files:**
- Modify: `agents/self_healer/README.md`、`agents/monitor/README.md`(提交)
- Modify: `CLAUDE.md`(本地,不提交)

- [ ] **Step 1: 文档**

- `agents/self_healer/README.md`:状态行改为 `**状态**: 一期部分实现 — 失败告警(分类+推送)已落地;Git留痕仅 REVIEW_MODE;AI诊断/沙盒验证仍为 V2 桩。`;「2026-08-19」节补充分类与留痕说明
- `agents/monitor/README.md`:职责区加 `- 逐条推送降级/兜底提醒(utils.health.note 实时,同键去重+上限10条)`
- `CLAUDE.md`(本地):当前进度加 `[x] 运行健康告警(12处降级点实时提醒)+ 错误分类 + REVIEW_MODE Git留痕`;「自愈闭环」条目更新为 `[ ] 自愈闭环(一期已做:告警+分类+条件留痕;二期:AI补丁+沙盒)`

- [ ] **Step 2: 全量验证**

Run: `"C:/Users/26063/miniconda3/envs/redbook_agent_company/python.exe" -m pytest tests/ -q` → 全绿(59)

- [ ] **Step 3: 提交(需用户确认,本会话已预先批准)**

```bash
git add agents/self_healer/README.md agents/monitor/README.md
git commit -m "docs: sync self_healer and monitor READMEs with health alerts"
```

---

## Self-Review 记录

- **需求覆盖**: 用户三项(自愈闭环一期、全环节异常捕获推送、兜底硬编码提醒)映射为 Task1 机制 + Task2 接线 + Task3 分类留痕 ✓;推送方式(逐条实时+去重+上限)与留痕条件(REVIEW_MODE)按用户决策 ✓
- **占位符扫描**: 无 TBD;Task2 接线点均给出文件与定位线索(先读后改)✓
- **类型一致性**: `note(node,kind,detail)`/`reset()/summary()/classify_error()`/`build_alert_message()` 在 Task1 定义与 Task2/3 使用一致;`format_fatal_message` 沿用现有签名 ✓
- **与现有代码兼容**: health 模块 import notifier(无环:notifier 不 import health);note 的推送失败不抛出(不得破坏降级路径)✓;main.py 的 REVIEW_MODE 已在此处导入 ✓
