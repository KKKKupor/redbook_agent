# Reviewer — 质量评审员

**角色**: 付费内容质量评审专家  
**Temperature**: 0.3  

## 2026-08-25 变更
- **流式化**: LLM 改用 `utils.llm_factory.reviewer_llm()`(新工厂,agent_key="reviewer"),web 控制台的评审卡可逐 token 流式输出评分过程。日常调度/quick_test 不受影响(stream_bus 无消费者时 no-op)
- **web 链接入**: web 控制台六段链 navigator→generator→packager→reviewer→auditor→publisher;评分不达标(score<6 且非 approve)自动重做,最多2次,重做时 generator 注入 review_retry_count/review_fixes_needed(与 Evaluator-Optimizer 闭环同机制)

## 2026-08-10 变更
- **量化检查A-E**: 分析长度均衡/评分制度/人格标签/维度数量/文案广告法，逐项pass/fail
- **fixes_needed输出**: 评分卡新增`fixes_needed`数组，每项含`section/dim_id/issue/action`四个字段，机器可读
- **定向修复接入**: `fix_issues.py`读取`fixes_needed`，仅重新生成标记fail的模块（copy/personality/analysis/questions/style）
- **Evaluator-Optimizer**: main.py workflow中score<6时自动回generator重修

## 评分维度
1. 题目设计质量 | 2. 文案商业价值 | 3. 分析内容丰富度
4. 人格映射准确性 | 5. 视觉风格匹配度 | 6. 整体商业价值
