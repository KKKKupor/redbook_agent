# Self Healer — 运维自愈

**状态**: V1.0 桩 — 未实现。

## 职责（规划）
- 致命错误时Git自动留痕
- AI分析堆栈生成补丁
- 沙盒验证
- 推送给运营者确认

## 已知局限
- 完全未实现。reason：MVP阶段错误直接通过loguru记录+console输出足够调试。
- 递归深度锁、边界控制等安全机制待设计。

## 2026-08-19 — 告警第一步已落地
- 失败告警已实现:`utils/notifier.format_fatal_message` + main.py run_once except 推送 🚨 Fatal 钉钉告警(不吞异常)。Git留痕/AI诊断/沙盒验证仍为 V2 桩。
