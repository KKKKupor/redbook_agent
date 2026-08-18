"""封面/商品图截图 — Playwright 同步 API。

产出三张图(spec 第2节):
  cover.png   750×1000 (3:4)  起始页 — 笔记封面
  result.png  750×1000 (3:4)  结果页顶部(雷达图+人格标签) — 笔记封面
  product.png 1000×1000 (1:1) 起始页 — 商品主图

CLI 手工验证(输出到当前目录):
    python -m utils.cover_shots path/to/test.html

失败语义: 模板的 Chart.js 为阻塞 script(位于应用脚本之前)。
  CDN 挂起 → 应用脚本不执行 → wait_for_function("typeof startTest") 超时抛异常,
  整个截图失败,由调用方降级(全有或全无)。
  CDN 正常但图表加载慢 → 等 CHART_TIMEOUT_MS 后照常截图,仅雷达图可能缺失。
"""

import sys
from pathlib import Path

from loguru import logger
from playwright.sync_api import sync_playwright

VIEWPORT_COVER = {"width": 750, "height": 1000}
VIEWPORT_PRODUCT = {"width": 1000, "height": 1000}
CHART_TIMEOUT_MS = 15000
MAX_ANSWER_LOOP = 200


def _answer_all_questions(page) -> None:
    """点第一个选项 + 下一题,直到结果区可见。防死循环上限 200 步。"""
    for _ in range(MAX_ANSWER_LOOP):
        if page.is_visible("#results-section"):
            return
        page.click("#q-options .option-btn >> nth=0")
        page.click("#btn-next")
    raise TimeoutError(f"答题循环超过 {MAX_ANSWER_LOOP} 步仍未到达结果页")


def capture_cover_images(html_path: Path, out_dir: Path) -> dict:
    """对给定 HTML 截图,产出 cover/result/product 三张 png。失败抛异常。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    html_uri = html_path.resolve().as_uri()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        context = browser.new_context(viewport=VIEWPORT_COVER, locale="zh-CN")
        page = context.new_page()

        # 1) 起始页封面(3:4)—— wait_until="commit" 避免被 Chart.js CDN 拖慢
        page.goto(html_uri, wait_until="commit", timeout=30000)
        # 确定性首帧信号:等待 #landing 的 fadeSlideIn(0.5s)动画完成,
        # 替代固定延时/visible 信号(二者都会在动画中途截图,得到半透明残影)
        page.wait_for_function(
            "getComputedStyle(document.getElementById('landing')).opacity === '1'",
            timeout=5000,
        )
        page.screenshot(path=str(out_dir / "cover.png"))

        # 2) 答题到结果页,截雷达图(3:4)
        # 等模板应用脚本就绪(阻塞的 Chart.js CDN 挂起时这里 30s 超时抛异常,由调用方降级)
        page.wait_for_function("typeof startTest === 'function'", timeout=30000)
        page.click("#btn-start-new")
        _answer_all_questions(page)
        try:
            page.wait_for_function("typeof Chart !== 'undefined'", timeout=CHART_TIMEOUT_MS)
        except Exception:
            # CDN 正常但图表加载慢:照常截图,雷达图可能缺失
            # (CDN 完全挂起时应用脚本不执行,上面 wait_for_function 已抛异常,整个截图失败由调用方降级)
            logger.warning("cover_shots: Chart.js CDN 15s 超时,照常截图(雷达图可能缺失)")
        page.wait_for_timeout(1500)  # 等 Chart 动画完成
        # 结果区约 2900px 高,scroll_into_view_if_needed 会把整区居中导致雷达图在视口上方;
        # 用 block:'start' 把结果区顶部(人格标签+雷达图)对齐到视口顶部
        page.evaluate("document.getElementById('results-section').scrollIntoView({ block: 'start' })")
        page.wait_for_timeout(300)
        page.screenshot(path=str(out_dir / "result.png"))

        # 3) 商品主图(1:1)—— 重新以方形视口加载起始页
        page.set_viewport_size(VIEWPORT_PRODUCT)
        page.goto(html_uri, wait_until="commit", timeout=30000)
        page.wait_for_timeout(800)
        page.screenshot(path=str(out_dir / "product.png"))

        browser.close()

    result = {name: out_dir / f"{name}.png" for name in ("cover", "result", "product")}
    logger.info(f"cover_shots: 3 张图已生成 → {out_dir}")
    return result


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python -m utils.cover_shots <html文件路径> [输出目录]")
        sys.exit(1)
    html = Path(sys.argv[1])
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else Path.cwd()
    images = capture_cover_images(html, out)
    for name, path in images.items():
        print(f"{name}: {path}")
