# Reviewer — 质量评审员

**角色**: 付费内容质量评审专家  
**Temperature**: 0.3  

## 2026-08-10 变更
- **量化检查A-E**: 分析长度均衡/评分制度/人格标签/维度数量/文案广告法，逐项pass/fail
- **fixes_needed输出**: 评分卡新增`fixes_needed`数组，每项含`section/dim_id/issue/action`四个字段，机器可读
- **定向修复接入**: `fix_issues.py`读取`fixes_needed`，仅重新生成标记fail的模块（copy/personality/analysis/questions/style）
- **Evaluator-Optimizer**: main.py workflow中score<6时自动回generator重修

## 评分维度
1. 题目设计质量 | 2. 文案商业价值 | 3. 分析内容丰富度
4. 人格映射准确性 | 5. 视觉风格匹配度 | 6. 整体商业价值
