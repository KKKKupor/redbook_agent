# Monitor — 监控推送

**状态**: V1.0 桩 — 功能已合并到main.py的run_once()中。

## 职责
- 汇总运行结果并推送钉钉日报
- ~~Token成本核算~~ (待实现CallbackHandler)
- ~~ROI计算~~ (无销售数据)

## 已知局限
- 成本核算未实现：Token计费回调已写但未接入各Agent的LLM调用。
- 日报内容较简单，不含成本拆解饼图。
