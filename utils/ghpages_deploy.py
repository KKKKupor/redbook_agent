"""GitHub Pages 部署 — 把生成的 HTML+截图发布到 gh-pages 分支。"""

import re
from pathlib import Path

from loguru import logger

_EMPTY_URLS = {
    "html_url": "",
    "cover_image_url": "",
    "result_image_url": "",
    "product_image_url": "",
}

_REMOTE_PATTERNS = [
    re.compile(r"https?://github\.com/(?P<user>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?/?$"),
    re.compile(r"git@github\.com:(?P<user>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?$"),
]


def derive_pages_urls(remote_url: str, date_str: str) -> dict:
    """由 origin remote URL 推导 GitHub Pages 链接。解析失败返回全空串。"""
    if not remote_url or not date_str:
        return dict(_EMPTY_URLS)
    user = repo = None
    for pat in _REMOTE_PATTERNS:
        m = pat.match(remote_url.strip())
        if m:
            user, repo = m.group("user"), m.group("repo")
            break
    if not user or not repo:
        return dict(_EMPTY_URLS)

    day = f"https://{user}.github.io/{repo}/d/{date_str}"
    return {
        "html_url": day + "/",
        "cover_image_url": f"{day}/cover.png",
        "result_image_url": f"{day}/result.png",
        "product_image_url": f"{day}/product.png",
    }
