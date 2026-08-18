# Navigator — 领航员（总协调员 + 商业决策大脑）

**角色**: 内容运营总监 + Agent组总协调  
**Temperature**: 0.7  
**模型**: DeepSeek-Chat  

## 职责
- **选题决策**: 代码层70/30利用-探索轮转
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
  → Publisher 自动部署Vercel
  → 钉钉回复链接

钉钉 @bot "发小红书吧"
  → Navigator 收到 → 调 Publisher 发布 → 钉钉确认
```

不需要手动脚本。`bot_server.py` 中 `generate_test()` 函数已内置自动调 Publisher。
DingTalk outgoing webhook 恢复后即可使用：`python bot_server.py` + `ngrok http 8080`。

## 已知局限
- 搜索在中国网络下fallback到训练数据（DuckDuckGo被墙），非实时信息
- IP角色提取依赖LLM训练数据覆盖面，冷门IP可能提取不全
