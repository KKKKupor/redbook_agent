# Self Healer — 运维自愈

**状态**: 一期部分实现 — 失败告警(分类+推送)已落地;Git留痕仅 REVIEW_MODE;AI诊断/沙盒验证仍为 V2 桩。

## 职责（规划）
- 致命错误时Git自动留痕
- AI分析堆栈生成补丁
- 沙盒验证
- 推送给运营者确认

## 已知局限
- 一期已部分实现(失败告警+错误分类+REVIEW_MODE条件留痕);AI诊断/沙盒验证仍待实现。
- 递归深度锁、边界控制等安全机制待设计。

## 2026-08-19 — 告警第一步已落地
- 失败告警已实现:`utils/notifier.format_fatal_message` + main.py run_once except 推送 🚨 Fatal 钉钉告警(不吞异常)。
- 错误分类:main.py except 分支用 `utils/health.classify_error` 将异常映射为 environmental/code/unknown(网络/限流/磁盘 → 恢复后重跑;代码逻辑 → 需修复),分类结果进入 Fatal 告警消息。
- Git留痕:仅 `REVIEW_MODE=true` 时执行(`utils/git_ops.git_ops.auto_commit()`,提交当前工作区脏文件,排除.env/__pycache__/data/),生产模式不自动提交;提交hash附在告警消息。AI诊断/沙盒验证仍为 V2 桩。
