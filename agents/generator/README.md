# Generator — 测试题生成

**角色**: 心理测评量表设计师  
**Temperature**: 0.85  
**模型**: DeepSeek-Chat (max_tokens=16384)  

## 2026-08-10 变更
- **动态评分**: `max_score = round(100/question_count)`，每题分值上限随题量自动调整。10题→max=10，50题→max=2。最终得分自然趋近0-100
- **校验自适应**: `_validate_questions` 的合法分值范围从硬编码[0,3]改为传入`max_score`参数
- **Skill增强**: 内容角度分类+质量约束

## MVP临时变更
- 维度数量动态化（>=3）
- JSON修复（`_repair_json`）
