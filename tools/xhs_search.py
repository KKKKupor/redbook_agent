"""小红书搜索结果抓取与缓存。

parse_notes 解析搜索结果页 innerText(标题+点赞,尽力附加时效),
filter_notes 本地筛选排序(点赞热度可靠;一周内为尽力而为——
需笔记带 days_ago 字段,开启时效筛选时无日期笔记被丢弃)。
live 搜索见 search_notes(依赖 data/xhs_cookies.json)。
"""

import json
import re
from datetime import datetime, timedelta
from pathlib import Path

from loguru import logger

CACHE_FILE = Path(__file__).resolve().parent.parent / "data" / "xhs_search_cache.json"
CACHE_TTL_DAYS = 7

LIKE_RE = re.compile(r"^\d+(\.\d+)?万?\+?$")
UI_BLACKLIST = {"首页", "我", "关注", "消息", "评论", "赞", "收藏", "分享", "登录", "更多", "搜索"}
TIME_RE = re.compile(r"^(\d+)\s*(天|小时|分钟|周|月)前$|^昨天$|^刚刚$")

SEARCH_URL = "https://www.xiaohongshu.com/search_result?keyword={kw}&type=51&sort={sort}"


def parse_notes(text: str, max_results: int = 10) -> list:
    """解析搜索结果页 innerText:点赞行向上匹配标题(跳过作者昵称行),黑名单过滤UI词。

    若点赞行下方紧跟时间标记(如"3天前"),尽力附加 days_ago 字段。
    """
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    notes = []
    for i, line in enumerate(lines):
        if not LIKE_RE.match(line):
            continue
        title = None
        for back in (2, 1):  # 优先隔一行(标题\n作者名\n点赞),退而求其次紧邻
            if i >= back:
                # back=2 时被跳过的那行若是点赞行,说明当前点赞行是孤儿(无标题),不配对
                if back == 2 and LIKE_RE.match(lines[i - 1]):
                    break
                cand = lines[i - back]
                if not LIKE_RE.match(cand) and cand not in UI_BLACKLIST and len(cand) >= 3:
                    title = cand
                    break
        if title is None:
            continue
        note = {"title": title, "likes": line}
        days = _parse_time_line(lines[i + 1]) if i + 1 < len(lines) else None
        if days is not None:
            note["days_ago"] = days
        notes.append(note)
        if len(notes) >= max_results:
            break
    return notes


def _parse_time_line(line: str) -> int | None:
    """'3天前'->3,'2小时前'->0,'1周前'->7,'昨天'->1,'刚刚'->0;非时间行->None。"""
    if line in ("昨天",):
        return 1
    if line in ("刚刚",):
        return 0
    m = re.match(r"^(\d+)\s*(天|小时|分钟|周|月)前$", line)
    if not m:
        return None
    n, unit = int(m.group(1)), m.group(2)
    return {"分钟": 0, "小时": 0, "天": n, "周": n * 7, "月": n * 30}[unit]


def parse_likes(raw: str) -> int:
    """'2.3万' -> 23000,'3924' -> 3924;无法解析返回 0。"""
    if not raw:
        return 0
    m = re.match(r"^(\d+(?:\.\d+)?)(万)?\+?$", raw.strip())
    if not m:
        return 0
    num = float(m.group(1))
    if m.group(2):
        num *= 10000
    return int(num)


def filter_notes(notes: list, min_likes: int = 0, max_age_days: int | None = None, top_n: int = 10) -> list:
    """本地筛选排序:按点赞降序(热度),可选点赞下限/时效上限/条数,附加 likes_num 字段。

    时效筛选为尽力而为:仅对带 days_ago 的笔记生效;
    开启 max_age_days 时,无日期笔记被丢弃(时效需求下未知时间不可信)。
    """
    out = []
    for n in notes:
        likes = parse_likes(n.get("likes", ""))
        if likes < min_likes:
            continue
        if max_age_days is not None:
            days = n.get("days_ago")
            if days is None or days > max_age_days:
                continue
        out.append({**n, "likes_num": likes})
    out.sort(key=lambda n: n["likes_num"], reverse=True)
    return out[:top_n]


def read_cache(keyword: str) -> list | None:
    """缓存命中(<7天)返回笔记列表,否则 None。"""
    if not CACHE_FILE.exists():
        return None
    try:
        data = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        entry = data.get(keyword)
        if not entry:
            return None
        scraped = datetime.fromisoformat(entry["scraped_at"])
        if datetime.now() - scraped > timedelta(days=CACHE_TTL_DAYS):
            return None
        return entry["notes"]
    except Exception:
        return None


def write_cache(keyword: str, notes: list) -> None:
    """写入缓存(保留其他关键词条目)。"""
    data = {}
    if CACHE_FILE.exists():
        try:
            data = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    data[keyword] = {"scraped_at": datetime.now().isoformat(), "notes": notes}
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    CACHE_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
