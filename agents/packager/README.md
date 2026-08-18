# Packager — 包装优化

**角色**: 视觉设计师 + 分析专家 + 文案写手  
**Temperature**: 0.7  
**模型**: DeepSeek-Chat (max_tokens=8192)  

## 2026-08-10 变更
- **分析逐维生成**: `_gen_analysis` 改为每维单独调LLM，强制均等字数（最长/最短≈1.1x）
- **人格IP覆盖**: `_gen_personality` 收到`ip_info`时完全替换prompt，强制输出角色名而非抽象标签
- **评分传参**: 计算并传递`max_score_per_question`给HTML模板
- **Skill全面增强**: copy/style/analysis/personality四个skill全部重写

## MVP临时变更
- 人格映射动态化（非强制MBTI）
- 所有prompt用`.replace()`
