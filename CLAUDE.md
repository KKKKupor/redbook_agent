# CLAUDE.md — 小红书测试题自动化运营Agent组

## 项目概述

基于 LangChain + LangGraph 的多智能体自动化系统，每日定时从0到上架全自动运营小红书付费测试题。

**7个核心Agent协作**：数据分析 → 领航员(决策) → 热点嗅探 → 测试题生成 → 包装优化 → 内容审核 → 质量评审 → 上传发布

## 技术栈

| 层 | 选型 | 版本 |
|----|------|------|
| 语言 | Python | 3.13.14 (conda: redbook_agent_company) |
| 框架 | LangChain + LangGraph | >=1.3 / >=1.2 |
| 大模型 | DeepSeek-Chat (全场景) | V1.0 纯DeepSeek |
| 数据库 | PostgreSQL (Docker) / SQLite 兜底 | 16-alpine |
| 向量库 | ChromaDB | >=1.5 |
| 调度 | APScheduler | 每日08:00 + 周一07:00抓取 |
| 浏览器 | Playwright + Chromium | 小红书数据抓取 |
| HTML渲染 | Jinja2 + Chart.js | 起始页→逐题→结果 |
| 推送 | 钉钉 Webhook | 日报(含Token成本+收益+ROI) |
| HTML部署 | Vercel CLI | 自动部署到 vercel.app |

## 目录结构

```
agents/{name}/           ← 每个Agent是独立包，可单独调试
  README.md              ← 角色/职责/输入输出/MVP临时变更/恢复条件
  src/
    main.py              ← Agent代码（LangGraph node函数）
    skills/              ← 系统提示词（独立.md文件，方便调优）
      system.md          ← 主提示词（如packager有4个skill文件）
    tools/               ← Agent专属工具（待扩展）

tools/                   ← 共享工具
  sales_tools.py         ← 5个数据Tool（空库时返回"暂无数据"）
  xhs_scraper.py         ← 每周话题抓取（周一07:00自动跑）

utils/
  llm_factory.py         ← 7个LLM工厂（temperature 0.1~0.85）
  prompt_loader.py       ← load_skill(__file__, "skill_name")
  token_tracker.py       ← 全局Token计数（DeepSeek定价: in=1元/1M, out=2元/1M）
  review.py              ← REVIEW_MODE: 输出到output/NN/（自动保留7次）
  xhs_auth.py            ← Playwright cookie认证
  notifier.py            ← 钉钉推送（需含"小红书"关键词）
  git_ops.py / validators.py

graph/
  state.py               ← AgentState TypedDict（含review_score/review_verdict）
  workflow.py            ← 7节点: analyst→navigator→hunter→generator→packager→reviewer→auditor→publisher

models/                  ← SQLAlchemy ORM (products/orders/strategy_logs/user_profiles)
scheduler/               ← APScheduler: 每日08:00 workflow + 周一07:00 scraper
templates/               ← test_template.html (起始页→逐题→结果+深色主题+自动存档)
data/                    ← 不提交Git：topic_pool.json, xhs_cookies.json
output/                  ← 生成HTML + deploy/目录（Vercel部署用）；archive/存早期快照
callbacks/               ← LangGraph回调（token_cost_callback.py）
tests/                   ← 测试目录（目前空壳）
github_example/          ← 外部参考项目（6个clone，不提交Git）
xiaohongshu-ai-workbench-main/  ← 外部参考（AI工作台，不提交Git）
```

## 每个Agent的差异化配置

| Agent | Temperature | LLM | 核心Skill |
|-------|------------|-----|-----------|
| data_analyst | 0.2 | DeepSeek | system.md — 只陈述事实 |
| navigator | 0.7 | DeepSeek | system.md — 选题代码决定(70/30) |
| trend_hunter | 0.5 | DeepSeek | system.md — 提取结构公式 |
| generator | 0.85 | DeepSeek(max 16384) | system.md — 分批15题，维度动态 |
| packager | 0.7 | DeepSeek(max 8192) | 4个skill: style/analysis/personality/copy |
| auditor | 0.1/MVP旁路 | DeepSeek | system.md — 仅静态广告法检测 |
| reviewer | 0.3 | DeepSeek | system.md — 多维评分(含商业价值) |

## LangGraph 全局 State

所有Agent通过 `AgentState(TypedDict)` 共享状态，关键字段：

- **决策**: selected_topic, target_question_count, suggested_price, scheduled_publish_time
- **生产**: dimension_defs, questions_json, generated_html, packaging_text
- **审核**: audit_status, audit_feedback, retry_count
- **评分**: review_score, review_verdict
- **发布**: html_url, xhs_note_id, actual_publish_time
- **成本**: total_token_cost, cost_breakdown
- **错误**: error_occurred, error_trace, heal_attempted, heal_depth

## 变更记录规范

**所有对单个Agent的局部临时改动（如MVP绕过、参数硬编码、功能降级）必须写进该Agent的 `README.md`**，包含：
- 改了什么
- 为什么改
- 什么时候恢复 / 恢复条件是什么

## 编码规范

- Agent节点签名: `def xxx_node(state: dict) -> dict`
- Agent间通过State传递，不直接调用
- 日志: `from loguru import logger`
- LLM: `from utils.llm_factory import xxx_llm` 获取预配置实例
- 提示词: `load_skill(__file__, "system")` 从同目录skills/加载
- Token追踪: `from utils.token_tracker import add_from_response` — 每次LLM调用后记录
- HTML模板路径: `Path(__file__).parent.parent.parent.parent / "templates"` (4级回根目录)
- 数据库: `from models.base import get_session` — 自动读DATABASE_URL
- 审查输出: `from utils.review import save, save_prompt, save_response`

## 质量审查模式

`.env` 中 `REVIEW_MODE=true` → 每次运行输出到 `output/NN/`（自增编号，最多保留7次）。

每个Agent输出:
- `_prompt.txt` / `_response.txt` — LLM原始输入输出
- 结构化结果JSON — 决策/题目/分析/评分
- Reviewer 额外输出 `scorecard.txt` — 可视化6维评分卡

确认质量后 `REVIEW_MODE=false` 关闭。

## 调度系统

`python main.py --schedule` 启动两个定时任务:

| 任务 | 时间 | 功能 |
|------|------|------|
| 每日workflow | 每天 08:00 | 全流程→Vercel部署→钉钉日报(含成本/收益/ROI) |
| 每周抓取 | 周一 07:00 | 搜XHS"测试题"→更新话题池→存入 `data/topic_pool.json` |

## Git 规范

- 不提交: `.env`, `data/`, `__pycache__/`, `.temp_fix/`, `output/`, `github_example/`, `xiaohongshu-ai-workbench-main/`
- commit message 用英文
- 不自动push

## MVP模式约定

- **题量**: 固定10题，代码层强制覆盖（`navigator/main.py`）。生产时删除覆盖行。
- **定价**: ¥0.99-1.99薄利多销，代码层强制覆盖。基于XHS实际竞品观察。
- **选题**: 代码层从话题池70/30轮转，非LLM决定（避免MBTI偏见）。话题池文件: `data/topic_pool.json`。
- **维度**: 3-12维动态，不写死6维。阴影测试类型不再套用MBTI。
- **人格标签**: 按选题类型动态决定分类体系（MBTI/shadow_level/trauma_type等）。
- **审查**: REVIEW_MODE=true → output/NN/（自动保留最近7次）。
- **模型**: 纯DeepSeek（GPT-4o预留但未启用）。
- **DB**: PostgreSQL(Docker)主库，SQLite兜底。空表时Tool返回"暂无数据"。
- **Auditor**: MVP旁路LLM审核，仅做静态广告法检测+默认放行。

## 已知全局问题

1. **选题池需持续更新**: 话题来自每周一抓取+硬编码兜底。exploit模式始终选第一个。
2. **Prompt写死在skill文件**: 决策逻辑是固定规则而非数据驱动的动态策略。后续需根据运营数据迭代。
3. **Auditor / Reviewer JSON解析不稳定**: DeepSeek有时不遵守output format。已通过`_repair_json`缓解但未根除。Trend Hunter已通过prompt增强改善。
4. **无真实数据源**: 自有销售=0，竞品价格/销量无法从搜索页获取，Tool返回空或mock。
5. **Publisher Vercel**: 已修复(shell=True)。偶有输出格式变化需要适配。
6. **所有Agent的MVP临时变更已记录在各README.md中**，含恢复条件。

## 2026-08-10 — Evaluator-Optimizer 闭环 + 外部参考项目

### Evaluator-Optimizer 质量闭环
借鉴 Anthropic "Building Effective Agents" 的 Evaluator-Optimizer 模式，实现 reviewer → generator 自动重做回路：
- **review_gate**: reviewer 评分 < 6 分 → 自动回退 generator，附带 `fixes_needed` 结构化修复指令
- **最多2次评审重修**，超过则放行（避免死循环）
- **generator 接受修复指令**: 当 `review_retry_count > 0` 时，在生成 prompt 中注入 reviewer 的具体修复要求
- 改动文件: `graph/workflow.py`, `graph/state.py`, `reviewer/main.py`, `generator/main.py`

### Agent-Panorama 可观测性
- 一行 import 接入 `PanoramaCallbackHandler`，实时追踪每个 agent 的运行状态
- 可选安装: `pip install agent-panorama[gemini]`
- 改动文件: `main.py`, `requirements.txt`

### 外部参考项目 (`github_example/`)
从 GitHub 克隆了 6 个优质 AI Agent 工程参考项目：
1. `ai-agent-handbook` — 30+框架源码分析的工程指南
2. `agentic-workflow-patterns` — 4个 LangGraph 设计模式（含代码）
3. `better-agents` — Agent 项目标准化脚手架
4. `awesome-prompt-optimization` — Prompt 优化资源索引
5. `awesome-evals` — 443+ Agent 评估资源 + PATTERNS.md 代码
6. `agent-panorama` — Agent 全景报告 + Live Dashboard

### Trend Hunter prompt 增强 + quick_test 修复 + Publisher 重试
- **Trend Hunter**: skill.md 重写（加幻觉防护+格式约束+质量自检），根因修复 JSON 解析不稳定
- **quick_test.py**: 接入 Evaluator-Optimizer 手动重试（score<6 自动重做）、修复 state 字段不匹配 bug
- **Publisher**: `_deploy_to_vercel` 加 1 次重试（网络超时容错）

### Skill 全面增强
借鉴《小红书运营手册 · AI工作台》的 skill 设计方法论（详见各 Agent README）：
- packager: 4个 skill 全部重写/增强（copy/style/personality/analysis）
- navigator: 选题功能分类+场景路由
- generator: 内容角度元信息+质量约束
- reviewer: 诊断先行+量化检查清单+fixes_needed 输出
- auditor: 4层审核维度+情绪风险检测

## 当前进度

- [x] 项目初始化、conda环境、目录结构
- [x] Agent独立包结构（README + src/main.py + skills/ + tools/）
- [x] 提示词提取为skills文件
- [x] 质量审查模式（含自动清理+可视化评分卡）
- [x] Reviewer Agent：6维评分+改进建议
- [x] HTML模板：起始页→逐题→结果+深色主题+主题切换+自动存档
- [x] 全流程跑通（10题/60题，25-59KB HTML）
- [x] Docker PostgreSQL 启动+切换
- [x] 定时调度（每日08:00 + 周一07:00抓取）
- [x] 钉钉日报推送（含Token成本拆解+收益+ROI+亏损警告）
- [x] Vercel自动部署
- [x] 选题池动态加载（从 `data/topic_pool.json`）
- [x] 动态维度（3-12维）+ 动态人格分类（非强制MBTI）
- [x] Token成本追踪（每个LLM调用精确到0.0001元）
- [x] **Evaluator-Optimizer 闭环**（reviewer评分<6自动回退generator重做）
- [x] **Skill全面增强**（7个agent的skill借鉴小红书AI工作台重写）
- [x] **外部参考项目**（github_example/ 6个项目）
- [x] **Trend Hunter prompt增强**（幻觉防护+格式约束+质量自检，修复JSON解析）
- [x] **quick_test.py 修复**（Evaluator-Optimizer手动重试+state字段修复）
- [x] **Publisher 部署重试**（Vercel CLI网络超时自动重试1次）
- [ ] Auditor JSON解析稳定化
- [ ] 小红书上传（待Playwright可用）
- [ ] 自愈闭环
