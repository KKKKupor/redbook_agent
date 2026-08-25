# Navigator — 领航员（总协调员 + 商业决策大脑）

**角色**: 内容运营总监 + Agent组总协调  
**Temperature**: 0.7  
**模型**: DeepSeek-Chat  

## 职责
- **选题决策**: 用户选题优先(web控制台/钉钉/quick_test);无选题时代码层70/30轮转,池选题不重复(data/generated_topics.json 跨运行记录,耗尽自动重置循环)
- **维度规划**: LLM动态生成3-12维
- **IP角色提取**: 自动识别IP测试→从训练数据提取角色信息→输出`ip_roles`+`ip_info`
- **定价**: 薄利多销¥0.99-1.99
- **协调下游Agent**: 接收钉钉指令→解析意图→调度Generator/Publisher

## 工具
| 工具 | 状态 | 用途 |
|------|------|------|
| `web_search` | ✅ | DuckDuckGo搜索，中国网络fallback到训练数据 |
| `knowledge_lookup` | ✅ | LLM训练数据查询 |
| `get_sales_analytics` | ✅ | 销售数据查询 |
| `get_product_rankings` | ✅ | 排行榜查询 |
| `get_competitor_trend` | ✅ | 竞品分析(mock) |
| `time_series_forecast` | ✅ | 发布时间预测(mock) |
| `get_topic_diversity` | ✅ | 题材分布 |

## 2026-08-25 变更
- **维度切题规则**(skill 第六阶段,响应"你几岁了"结果标签跑偏为"责任担当者"的反馈):年龄类选题("几岁/多大/心理年龄")维度围绕年龄感设计、标签用年龄向表述;通用规则"维度名与标签连读必须能回答选题字面问题"
- **Web 入口校验(仅网页生效)**: `state.user_message` 非空(web 控制台传用户原话;钉钉/日常调度不传,天然不受影响)时启用两条拒绝路径:
  - **题量超限**: 请求 > `MAX_QUESTIONS`(60题)→ LLM 生成拒绝文案(附用户原话+上限+token估算,流式可见),返回 `{"rejected": true, "reply": ...}`,零副作用(不查工具、不写选题历史);LLM 失败用模板兜底,拒绝结论不变。token 估算系数 `TOKENS_PER_QUESTION = 325`(实测 15题≈4871 out tokens),仅作文案素材
  - **无关输入**: 决策 context 追加判定段(不改 system.md,避免日常调度 schema drift),LLM 判定输入非测试题请求 → `{"rejected": true, "reply": "能力边界说明"}` → 早退
- **拒绝文案提示词**: 新 skill `src/skills/refusal.md`(`load_skill(__file__, "refusal")`)
- web 控制台收到 rejected 后直接终止链(不调 generator/packager/publisher),前端显示"本轮未生成测试题"+拒绝说明
- 测试 `tests/test_navigator_rejection.py`(5条)

## 2026-08-24 变更
- **用户选题优先**: `state.selected_topic` 非空(web控制台/钉钉/quick_test 传入)时直接采用,策略标记 `user`,不写入 generated 历史
- **池选题不重复**: 无用户选题时从 `data/topic_pool.json` 70/30 轮转,已生成过的选题写入 `data/generated_topics.json`(跨运行持久化,data/ 不提交 Git);池耗尽自动重置历史重新循环并记录 health note `pool_cycle_reset`
- **实现**: `select_topic` 纯函数 + `_load_generated`/`_save_generated`(缺失/损坏文件回空集);测试 `tests/test_navigator_topic.py` 覆盖四分支(用户优先/exploit/explore/循环重置)

## 2026-08-10 变更
- **IP自主识别**: 不再在quick_test中硬编码IP关键词。Navigator自行判断选题是否为IP测试，从训练数据提取角色信息，输出`ip_roles`和`ip_info`传给Packager
- **搜索工具**: 添加`web_search`和`knowledge_lookup`，自动搜索IP角色信息
- **协调中心**: Navigator成为唯一外部指令入口，解析"发小红书""重新生成"等指令并调度Agent
- **Skill增强**: 选题功能角色+场景路由+IP特别处理

## 全自动链路（Navigator 协调）

```
钉钉 @bot "做分院帽测试"
  → Navigator 自助: 选题→维度→IP角色提取
  → Generator 生成题目
  → Packager 包装HTML+人格标签
  → Publisher 自动部署GitHub Pages
  → 钉钉回复链接

钉钉 @bot "发小红书吧"
  → Navigator 收到 → 调 Publisher 发布 → 钉钉确认
```

不需要手动脚本。`bot_server.py` 中 `generate_test()` 函数已内置自动调 Publisher。
DingTalk outgoing webhook 恢复后即可使用：`python bot_server.py` + `ngrok http 8080`。

Web 控制台: `python web_console.py` → http://localhost:8090/ 发指令即可流式生成(每IP每日1次;回环IP与 env `WHITELIST_IPS` 白名单不限次;单次上限60题,超限/无关输入由 navigator 拒绝)

## 已知局限
- 搜索在中国网络下fallback到训练数据（DuckDuckGo被墙），非实时信息
- IP角色提取依赖LLM训练数据覆盖面，冷门IP可能提取不全
- **选题池已真实产出(2026-08-19)**: `data/topic_pool.json` 由周一抓取任务(xhs_scraper)产出——真实抓取话题(已过滤噪音词与搜索词本身)在前、硬编码默认池去重补后。cookies 过期导致抓取 <3 条时不写文件,回落硬编码兜底。
