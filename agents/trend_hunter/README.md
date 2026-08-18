# Trend Hunter — 热点嗅探（市场调研员）

**角色**: 社交媒体内容分析师  
**Temperature**: 0.5  
**模型**: DeepSeek-Chat  

## 职责
- 搜索小红书同类爆款测试题的结构公式
- 提取标题公式、题型结构、视觉风格、卖点钩子
- 不搬运内容，只提取文本特征

## 输入
- 选题（selected_topic）

## 输出
`insights.json` — 标题公式/关键词/卖点/视觉风格建议

## MVP临时变更
- **无真实搜索**: MVP未接入Playwright搜索。所有分析基于LLM先验知识。
- **恢复条件**: Playwright cookie可用的前提下，将真实搜索结果注入prompt。

## 2026-08-10 — prompt增强+JSON修复（已完成）

**问题诊断**: JSON解析不稳定的根因不是缺`_repair_json`（已经加了），而是prompt对输出格式的约束不够强。原prompt只说"必须只输出JSON"，但没有给出具体的格式自检指令。

**为什么改**: DeepSeek在宽松的格式约束下容易输出markdown报告而非纯JSON。参考generator/auditor的修复经验，在prompt中加入"只输出JSON，不要markdown代码块"+"输出前自检"可以显著降低解析失败率。

**具体改动**（已完成）:
1. `skills/system.md` — 增强：① 输出格式说明加"不要输出markdown代码块标记"；② 加入质量自检清单（关键词是否和选题匹配/公式是否具体/是否标注了推测来源）；③ 加入幻觉防护：无真实搜索数据时，基于通用知识推断并明确标注为"推测"
2. `main.py` — 小修：日志中区分"JSON解析失败"和"LLM返回空"两种情况
3. `README.md` — 移除"需要加_repair_json"（已经加了），更新为"prompt约束已增强"

**恢复条件**: 无需恢复。

## 已知局限
- **JSON解析不稳定**: DeepSeek偶发返回纯文本而非JSON，触发fallback默认值。已通过prompt格式约束增强+`_repair_json`兜底缓解。
- **默认值固化**: fallback的关键词"性格/测试/人格"几乎每次相同。
- **LLM先验知识可能过时**: DeepSeek训练数据截止时间不确定，可能与小红书当前热点脱节。

## 调优指南
- ~~在 `main.py` 中添加 `_repair_json`~~（已添加）— 如仍解析失败，继续增强 `skills/system.md` 的格式约束
- Playwright可用后，将搜索结果注入prompt
- 更新 `skills/system.md` 添加更多分析维度

## 文件
```
src/
├── main.py      ← Agent 代码
└── skills/
    └── system.md  ← 系统提示词
```
