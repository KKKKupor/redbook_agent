"""
Xiaohongshu authentication via Playwright with saved cookies.

Loads cookies from data/xhs_cookies.json and injects them into a
Playwright browser context to simulate a logged-in session.

Usage:
    async with XHSBrowser() as (browser, context, page):
        await page.goto("https://creator.xiaohongshu.com")
        # now you're logged in
"""

import json
from pathlib import Path
from typing import Optional

from playwright.async_api import (
    async_playwright,
    Browser,
    BrowserContext,
    Page,
)

COOKIE_FILE = Path(__file__).resolve().parent.parent / "data" / "xhs_cookies.json"

# Real Chrome on Windows UA — avoids bot detection
DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)


def load_cookies() -> list[dict]:
    """Load saved Xiaohongshu cookies from JSON."""
    if not COOKIE_FILE.exists():
        raise FileNotFoundError(
            f"Cookie file not found: {COOKIE_FILE}\n"
            "Export cookies from browser (F12 → Application → Cookies) "
            "and save as data/xhs_cookies.json"
        )
    raw = json.loads(COOKIE_FILE.read_text(encoding="utf-8"))
    # Normalize: Playwright needs sameSite as one of Strict|Lax|None
    for c in raw:
        if "sameSite" in c:
            val = c["sameSite"]
            if val not in ("Strict", "Lax", "None"):
                c["sameSite"] = "Lax"
        if "expires" in c and isinstance(c["expires"], str):
            # convert ISO string to unix timestamp if needed
            pass
    return raw


class XHSBrowser:
    """Async context manager: launches Chromium with Xiaohongshu cookies."""

    def __init__(self, headless: bool = True, user_agent: Optional[str] = None):
        self.headless = headless
        self.user_agent = user_agent or DEFAULT_UA
        self._playwright = None
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None

    async def __aenter__(self):
        self._playwright = await async_playwright().start()
        self.browser = await self._playwright.chromium.launch(
            headless=self.headless,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
        )
        self.context = await self.browser.new_context(
            user_agent=self.user_agent,
            viewport={"width": 1440, "height": 900},
            locale="zh-CN",
        )
        # Inject cookies
        cookies = load_cookies()
        await self.context.add_cookies(cookies)
        self.page = await self.context.new_page()
        return self.browser, self.context, self.page

    async def __aexit__(self, *args):
        if self.browser:
            await self.browser.close()
        if self._playwright:
            await self._playwright.stop()


# Quick test
async def _test():
    async with XHSBrowser(headless=False) as (browser, context, page):
        await page.goto("https://www.xiaohongshu.com/explore", wait_until="domcontentloaded")
        title = await page.title()
        print(f"Page title: {title}")
        # Take a screenshot to verify login status
        await page.screenshot(path="xhs_test.png", full_page=False)


if __name__ == "__main__":
    import asyncio
    asyncio.run(_test())
