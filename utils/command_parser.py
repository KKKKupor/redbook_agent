"""Shared command parser — 只做指令分类,不做语义解析。

选题/题量的语义判读由 navigator 的 LLM 完成(用户意图表达方式多样,
规则解析无法覆盖,详见 navigator skill 的"用户意图解析"段)。
"""

import re

# 题量片段(仅 modify 指令的数字提取用):阿拉伯数字或中文数字
_COUNT_PART = r'((\d+)|([一二两三四五六七八九十]+))'

_CN_DIGITS = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
              "六": 6, "七": 7, "八": 8, "九": 9}


def _parse_cn_count(s: str) -> int:
    """中文数字 → 整数:'五'→5 '十五'→15 '二十三'→23 '十'→10。"""
    if not s:
        return 0
    if "十" in s:
        left, _, right = s.partition("十")
        tens = _CN_DIGITS.get(left, 1) if left else 1
        ones = _CN_DIGITS.get(right, 0)
        return tens * 10 + ones
    return _CN_DIGITS.get(s, 0)


def _to_count(m: re.Match | None) -> int | None:
    """从题量正则 Match 提取整数;阿拉伯数字优先,其次中文数字。"""
    if not m:
        return None
    if m.group(2) is not None:
        return int(m.group(2))
    if m.group(3):
        return _parse_cn_count(m.group(3))
    return None


def parse_command(text: str) -> dict:
    """Parse user message — 指令分类;generate 类的选题/题量由 navigator LLM 判读。"""
    text = re.sub(r'@\S+', '', text).strip()

    # Coordination commands (Navigator handles these)
    if any(kw in text for kw in ["发小红书", "发布", "上传", "publish"]):
        return {"type": "publish", "text": text}
    if any(kw in text for kw in ["重新生成", "重做", "再来", "redo", "regenerate"]):
        return {"type": "regenerate", "text": text}
    if any(kw in text for kw in ["改", "调整", "换成"]):
        count_match = re.search(_COUNT_PART + r'\s*题', text)
        return {"type": "modify", "text": text, "new_count": _to_count(count_match)}
    if any(kw in text for kw in ["挺好", "不错", "可以", "ok", "行", "好"]):
        return {"type": "approve_publish", "text": text}

    # Generate command — 语义(选题/题量)由 navigator 的 LLM 判读,此处只透传原文
    return {"type": "generate", "text": text, "topic": "", "question_count": 15}
