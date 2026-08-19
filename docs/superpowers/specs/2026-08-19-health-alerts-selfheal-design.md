# 运行健康告警 + 自愈一期 设计

**日期**: 2026-08-19
**状态**: 已获用户批准(逐条实时推送 + 仅 REVIEW_MODE 自动留痕)
**范围**: 全链路降级/兜底点统一健康登记与实时提醒;错误分类;REVIEW_MODE 下崩溃 Git 留痕。AI 补丁生成/沙盒验证为下期。

## 1. 目标

1. 所有"因缺真实数据/解析失败/网络失败等原因走兜底或硬编码"的环节,降级发生时**逐条实时推送钉钉提醒**
2. 致命错误在现有 🚨 告警基础上增加**错误分类**(环境类 vs 代码逻辑类)与 **REVIEW_MODE 下 Git 留痕**
3. 机制不退化:新增降级点只需一行 `health.note(...)`

## 2. 架构

```
utils/health.py(新模块,纯函数部分可单测)
  note(node, kind, detail)  → 记录 + 立即推送「⚠️ 小红书Agent降级提醒」
                              同 (node,kind) 每运行去重;每运行上限10条;推送失败仅日志
  reset()                   → 每运行开始清零
  summary()                 → 本次运行全部降级记录
  classify_error(error)     → environmental | code | unknown(类型表+消息模式)
  build_alert_message(...)  → 纯函数组装消息体

各 agent 现有 except/兜底分支 → 加一行 health.note(不改变现有降级行为)
main.py:
  run_once 开始 → health.reset()
  崩溃 except → classify_error + REVIEW_MODE 时 git_ops.auto_commit()(留痕 hash 进 Fatal 消息)
```

推送渠道复用 `utils.notifier`(标题含"小红书"过钉钉过滤器,level="warning")。

## 3. 接线清单(12 处,均为一行动作)

| Agent | 降级点 | kind |
|---|---|---|
| navigator | topic_pool.json 缺失/不足→硬编码池 | topic_pool_hardcoded |
| navigator | LLM 决策 JSON 解析失败→安全默认值 | llm_parse_failed |
| trend_hunter | get_search_context 返回 None→LLM先验 | search_fallback |
| trend_hunter | insights JSON 解析失败→默认值 | llm_parse_failed |
| generator | dimension_defs 缺失→通用维度 | dimension_fallback |
| generator | 生成批次 LLM 调用异常(现有 except 处) | generation_failed |
| packager | 首推版本文案提取不合格→FALLBACK_COPY | copy_fallback |
| publisher | 截图失败→降级无图 | capture_failed |
| publisher | gh-pages 部署失败→本地路径 | deploy_failed |
| reviewer | 评分 JSON 解析失败→fallback | llm_parse_failed |
| data_analyst | 分析 LLM 调用异常(现有 except 处) | analytics_failed |
| sales_tools | 竞品趋势/发布时间预测为 mock | mock_data |

## 4. 错误分类规则

- environmental: TimeoutError/ConnectionError/OSError 类,或消息含 timeout/timed out/connection/429/rate limit/disk full/no space/dns/resolve → 恢复后重跑
- code: KeyError/TypeError/ValueError(含 JSONDecodeError)/ImportError/AttributeError/IndexError → 需修复
- unknown: 其余

## 5. Git 留痕

仅 REVIEW_MODE=true 时:`git_ops.auto_commit()`(GitPython,排除 .env/__pycache__/data/,已实现),hash 附入 Fatal 消息;生产(REVIEW_MODE=false)不自动提交(尊重红线)。

## 6. 测试

- test_health.py:build_alert_message 格式与截断;同键去重(monkeypatch 计数);10 条上限;reset 清空;推送失败不抛
- test_classify_error.py:类型表逐类 + 消息模式 + unknown
- 全量套件不回归

## 7. 范围外(下期)

AI 诊断堆栈生成补丁、.temp_fix 沙盒验证、递归深度锁——依赖本期的分类结果,另行设计。
