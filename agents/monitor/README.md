# Monitor — 监控推送

**状态**: V1.0 桩 — 功能已合并到main.py的run_once()中。

## 职责
- 汇总运行结果并推送钉钉日报
- ~~Token成本核算~~ (待实现CallbackHandler)
- ~~ROI计算~~ (无销售数据)

## 已知局限
- 成本核算方式与职责描述不同：日报成本实际来自 `utils.token_tracker.summary()`（main.py run_once内联调用），而非CallbackHandler方式；`callbacks/token_cost_callback.py` 已写但未接入各Agent的LLM调用。
- 日报内容较简单，不含成本拆解饼图。
