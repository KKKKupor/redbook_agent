"""GitHub Pages 部署 — 把生成的 HTML+截图发布到 gh-pages 分支。"""

import re
import shutil
import subprocess
import tempfile
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


REPO_ROOT = Path(__file__).resolve().parent.parent


def _git(repo_dir: Path, *args: str) -> str:
    """在指定仓库目录执行 git 命令,返回 stdout。失败抛异常。"""
    result = subprocess.run(
        ["git", "-C", str(repo_dir), *args],
        capture_output=True, text=True, timeout=180,
        encoding="utf-8", errors="replace",
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()[:300]}")
    return result.stdout.strip()


def _git_config(key: str) -> str:
    """读取主仓库配置(proxy/user.name/user.email),缺失返回空串。"""
    try:
        return _git(REPO_ROOT, "config", "--get", key)
    except RuntimeError:
        return ""


def deploy_to_ghpages(deploy_dir: Path, date_str: str) -> dict:
    """部署 deploy_dir(HTML+截图)到 gh-pages:根=最新版,d/{date}=当天永久版。

    仅 index.html 必需;3 张 PNG 存在才复制(截图失败时仍部署 HTML,
    由调用方把图片 URL 置空走"封面图生成失败"降级)。失败抛异常。
    """
    index = deploy_dir / "index.html"
    if not index.exists():
        raise FileNotFoundError(f"{index} 不存在,无法部署")

    origin = _git_config("remote.origin.url") or _git(REPO_ROOT, "remote", "get-url", "origin")
    if not origin:
        raise RuntimeError("未配置 git remote origin")

    tmp = Path(tempfile.mkdtemp(prefix="ghpages_"))
    try:
        _git(tmp, "init")
        proxy = _git_config("http.proxy")
        if proxy:
            _git(tmp, "config", "http.proxy", proxy)
        _git(tmp, "config", "user.name", _git_config("user.name") or "Kiran")
        _git(tmp, "config", "user.email", _git_config("user.email") or "kuporlink@gmail.com")
        _git(tmp, "remote", "add", "origin", origin)

        # 分支存在 → 在其上追加提交;不存在(首次)→ orphan 分支直接推
        try:
            _git(tmp, "fetch", "--depth", "1", "origin", "gh-pages")
            _git(tmp, "checkout", "-q", "FETCH_HEAD")
            _git(tmp, "switch", "-q", "-c", "gh-pages")
        except RuntimeError:
            _git(tmp, "checkout", "-q", "--orphan", "gh-pages")

        # 组装:根=最新版,d/{date}/=当天永久版
        day = tmp / "d" / date_str
        day.mkdir(parents=True, exist_ok=True)
        for name in ("index.html", "cover.png", "result.png", "product.png"):
            src = deploy_dir / name
            if not src.exists():
                continue
            shutil.copy(src, tmp / name)
            shutil.copy(src, day / name)
        (tmp / ".nojekyll").touch()

        _git(tmp, "add", "-A")
        # 内容与远端完全一致时无可提交(同日重跑):跳过 commit/push,视为部署成功
        if _git(tmp, "status", "--porcelain"):
            _git(tmp, "commit", "-m", f"deploy {date_str}")
            _git(tmp, "push", "origin", "gh-pages")
        else:
            logger.info("ghpages_deploy: 内容与远端一致,跳过 commit/push")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    urls = derive_pages_urls(origin, date_str)
    logger.info(f"ghpages_deploy: {date_str} -> {urls['html_url']}")
    return urls
