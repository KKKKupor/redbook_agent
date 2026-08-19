# Packager — 包装优化

**角色**: 视觉设计师 + 分析专家 + 文案写手  
**Temperature**: 0.7  
**模型**: DeepSeek-Chat (max_tokens=8192)  

## 2026-08-10 变更
- **分析逐维生成**: `_gen_analysis` 改为每维单独调LLM，强制均等字数（最长/最短≈1.1x）
- **人格IP覆盖**: `_gen_personality` 收到`ip_info`时完全替换prompt，强制输出角色名而非抽象标签
- **评分传参**: 计算并传递`max_score_per_question`给HTML模板
- **Skill全面增强**: copy/style/analysis/personality四个skill全部重写

## 2026-08-18 — 文案提取契约化修复
- **问题**: 【首推版本】块LLM只输出版本名+推荐理由,旧启发式提取把"思考过程"当文案发进了钉钉素材消息
- **修复**: copy.md 输出契约改为【首推版本】=完整复制所选文案、【推荐理由】=一句话理由;`_extract_recommended` 纯函数按契约提取(截断到下一【标记、去版本选择器行、校验≥20字+含话题标签),不合格回退 `FALLBACK_COPY`
- **测试**: `tests/test_packager_copy.py` 6个TDD测试(含真实坏样本回归)

## MVP临时变更
- 人格映射动态化（非强制MBTI）
- 所有prompt用`.replace()`

## 已知局限
- **HTML输出路径bug**: `main.py:256` 的 `output_dir` 只回溯3级parent → 实际写入 `agents/output/`（而非根 `output/`），每次运行都会重建该目录；日志却声称写到 `output/`，与CLAUDE.md描述不符。修复方式：改为4级parent（同文件231行模板路径已是4级）。
