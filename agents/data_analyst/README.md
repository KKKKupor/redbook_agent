# Data Analyst — 数据分析（商业智能参谋）

**角色**: 电商数据分析师  
**Temperature**: 0.2  
**模型**: DeepSeek-Chat  

## 职责
- 查询5个数据Tool：单品销量/排行/竞品趋势/发布时间预测/题材多样性
- 生成结构化业务复盘报告
- 不加入主观猜测，用数字说话

## 输入
- 从Tool查询数据库（暂无真实销售数据）

## 输出
`report.txt` — 结构化JSON业务报告

## MVP临时变更
- **Tools容错**: 三个Tool函数（`get_product_rankings`, `get_sales_analytics`, `get_topic_diversity`）都加了 `try/except`，DB不存在或空表时返回 `"暂无数据"` 而非崩溃。
- **原因**: DB被删除（假数据清理）后不能影响流程。

## 已知局限
- 竞品趋势和发布时间预测仍为mock（`get_competitor_trend`, `time_series_forecast`）。
- 没有自有销售数据时报告基本为空。
- 评论区分析已永久移除（V2.0暂缓）。

## 文件
```
src/
├── main.py      ← Agent 代码
└── skills/
    └── system.md  ← 系统提示词
```
