"""
Xiaohongshu topic scraper — scheduled weekly (Mon 07:00).

Searches "测试题" and extracts trending test topic keywords.
Updates navigator's REAL_TOPIC_POOL on success.
"""

import asyncio, json, re, sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from utils.xhs_auth import XHSBrowser
from loguru import logger

POOL_FILE = Path(__file__).resolve().parent.parent / "data" / "topic_pool.json"

SEARCH_QUERIES = ["测试题", "人格测试", "心理测试", "性格测试"]

NOISE_WORDS = ("免费", "官方", "怎么", "为什么", "哪些", "什么")


def _filter_noise(topics: list) -> list:
    """过滤噪音话题:搜索词本身与带噪音词前缀的抓取产物。"""
    out = []
    for t in topics:
        if t in SEARCH_QUERIES:
            continue
        if any(w in t for w in NOISE_WORDS):
            continue
        out.append(t)
    return out

DEFAULT_TOPIC_POOL = [
    "人格阴影测试", "童年创伤程度测试", "恋爱人格匹配测试",
    "危险人格类型测试", "职场性格测试", "MBTI深度解析",
    "动物塑测试", "去性别化人格测试", "心理压力指数测试",
    "情商测试", "社交人格测试", "抑郁倾向筛查",
]
MIN_TOPICS = 3  # 原为6,过严导致文件从未产出


async def _scrape_topics() -> list:
    """Scrape trending topics from XHS search. Returns list of topic strings."""
    all_topics = set()
    async with XHSBrowser(headless=True) as (browser, context, page):
        for query in SEARCH_QUERIES:
            try:
                url = f"https://www.xiaohongshu.com/search_result?keyword={query}&type=51"
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                await asyncio.sleep(2)
                for _ in range(2):
                    await page.evaluate("window.scrollBy(0, 600)")
                    await asyncio.sleep(1)
                text = await page.evaluate("() => document.body.innerText")
                # Extract test-type patterns
                found = re.findall(
                    r'([一-鿿]{2,6}(?:测试|人格|性格|类型|倾向|程度|筛查|诊断|评估))',
                    text
                )
                all_topics.update(found)
                logger.info(f"Scraper: '{query}' -> {len(found)} topics")
            except Exception as e:
                logger.warning(f"Scraper: '{query}' failed: {e}")

    # Merge with known pool, deduplicate, sort by length (shorter=more general first)
    topics = sorted(all_topics, key=lambda t: (len(t), t))
    return topics


def run_scrape():
    """Synchronous entry point for APScheduler."""
    logger.info("Scraper: weekly topic refresh starting...")
    try:
        topics = _filter_noise(asyncio.run(_scrape_topics()))
        if len(topics) >= MIN_TOPICS:
            merged = topics + [t for t in DEFAULT_TOPIC_POOL if t not in set(topics)]
            data = {
                "updated_at": datetime.now().isoformat(),
                "topics": merged,
                "scraped_count": len(topics),
            }
            POOL_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            logger.info(f"Scraper: saved {len(merged)} topics ({len(topics)} scraped) -> {POOL_FILE}")
        else:
            logger.warning(f"Scraper: only {len(topics)} topics (need >= {MIN_TOPICS}), keeping old pool")
    except Exception as e:
        logger.error(f"Scraper: weekly run failed: {e}")


if __name__ == "__main__":
    run_scrape()
