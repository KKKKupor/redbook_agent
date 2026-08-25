"""Shared command parser — parses user messages into intent commands.

Used by both the DingTalk bot (bot_server.py) and the web console.
"""

import re


def parse_command(text: str) -> dict:
    """Parse user message — detects both 'generate' and 'coordinate' commands."""
    text = re.sub(r'@\S+', '', text).strip()

    # Coordination commands (Navigator handles these)
    if any(kw in text for kw in ["发小红书", "发布", "上传", "publish"]):
        return {"type": "publish", "text": text}
    if any(kw in text for kw in ["重新生成", "重做", "再来", "redo", "regenerate"]):
        return {"type": "regenerate", "text": text}
    if any(kw in text for kw in ["改", "调整", "换成"]):
        count_match = re.search(r'(\d+)\s*题', text)
        return {"type": "modify", "text": text, "new_count": int(count_match.group(1)) if count_match else None}
    if any(kw in text for kw in ["挺好", "不错", "可以", "ok", "行", "好"]):
        return {"type": "approve_publish", "text": text}

    # Generate command
    # 前缀剥离(做/要/想要/关于/生成 + 一个/个/一款),题量尾巴单独去掉,保留话题里的"测试"字样
    # 题量尾巴兼容量词:"1000题" / "1000道题" / "1000道测试题"
    topic_match = re.search(r'(?:关于|做|想要|要|生成)(?:一个|个|一款)?(.+)', text)
    if topic_match:
        topic = re.sub(r'[，,。\s]*\d+\s*[道个]?\s*(?:测试)?题.*$', '', topic_match.group(1)).strip()
    else:
        # 无动词前缀(如"你几岁了,10道题")同样剥离题量尾巴
        topic = re.sub(r'[，,。\s]*\d+\s*[道个]?\s*(?:测试)?题.*$', '', text[:30]).strip()
    if re.fullmatch(r'\d+\s*[道个]?', topic):
        # 纯题量残留("做15道")→ 空选题
        topic = ""
    if len(topic) <= 2:
        # 剥离后无实质主题(如"帮我生成一个10道测试题")→ 空选题,由 navigator 走选题池
        topic = ""
    count_match = re.search(r'(\d+)\s*[道个]?\s*(?:测试)?题', text)
    if count_match is None:
        # 仅有量词无"题"字:"做15道"
        count_match = re.search(r'(\d+)\s*[道个]\s*$', text)
    count = int(count_match.group(1)) if count_match else 15
    # 不做静默截断:题量校验交给 navigator 的拒绝逻辑(web 场景上限 60 题)
    return {"type": "generate", "text": text, "topic": topic, "question_count": count}
