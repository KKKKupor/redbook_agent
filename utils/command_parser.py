"""Shared command parser — parses user messages into intent commands.

Used by both the DingTalk bot (bot_server.py) and the web console.
"""

import re

# 中文数字(一~九十九的常见形式):五→5 十五→15 二十三→23 十→10 两→2
_CN_DIGITS = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
              "六": 6, "七": 7, "八": 8, "九": 9}
# 题量片段:阿拉伯数字 或 中文数字(两者互斥,分别落在 group 1/2)
_COUNT_PART = r'((\d+)|([一二两三四五六七八九十]+))'


def _parse_cn_count(s: str) -> int:
    """中文数字 → 整数:'五'→5 '十五'→15 '二十三'→23 '十'→10 '二十'→20。"""
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
    """Parse user message — detects both 'generate' and 'coordinate' commands."""
    text = re.sub(r'@\S+', '', text).strip()

    # Coordination commands (Navigator handles these)
    if any(kw in text for kw in ["发小红书", "发布", "上传", "publish"]):
        return {"type": "publish", "text": text}
    if any(kw in text for kw in ["重新生成", "重做", "再来", "redo", "regenerate"]):
        return {"type": "regenerate", "text": text}
    if any(kw in text for kw in ["改", "调整", "换成"]):
        count_match = re.search(_COUNT_PART + r'\s*题', text)
        new_count = _to_count(count_match)
        return {"type": "modify", "text": text, "new_count": new_count}
    if any(kw in text for kw in ["挺好", "不错", "可以", "ok", "行", "好"]):
        return {"type": "approve_publish", "text": text}

    # Generate command
    # 前缀剥离(做/要/想要/关于/生成 + 一个/个/一款),题量尾巴单独去掉,保留话题里的"测试"字样
    # 题量尾巴兼容量词:"1000题" / "1000道题" / "1000道测试题" / "五题" / "十五道测试题"
    count_tail = _COUNT_PART + r'\s*[道个]?\s*(?:测试)?题'
    topic_match = re.search(r'(?:关于|做|想要|要|生成)(?:一个|个|一款)?(.+)', text)
    if topic_match:
        topic = re.sub(r'[，,。\s]*' + count_tail + r'.*$', '', topic_match.group(1)).strip()
    else:
        # 无动词前缀(如"你几岁了,10道题")同样剥离题量尾巴
        topic = re.sub(r'[，,。\s]*' + count_tail + r'.*$', '', text[:30]).strip()
    if re.fullmatch(_COUNT_PART + r'\s*[道个]?', topic):
        # 纯题量残留("做15道")→ 空选题
        topic = ""
    if len(topic) <= 2:
        # 剥离后无实质主题(如"帮我生成一个10道测试题")→ 空选题,由 navigator 走选题池
        topic = ""
    count_match = re.search(count_tail, text)
    if count_match is None:
        # 仅有量词无"题"字:"做15道" / "做五道"
        count_match = re.search(_COUNT_PART + r'\s*[道个]\s*$', text)
    count = _to_count(count_match)
    count = count if count is not None else 15
    # 不做静默截断:题量校验交给 navigator 的拒绝逻辑(web 场景上限 60 题)
    return {"type": "generate", "text": text, "topic": topic, "question_count": count}
