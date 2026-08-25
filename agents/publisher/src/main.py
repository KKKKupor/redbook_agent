"""
Upload Agent (Publisher) — deploy HTML to GitHub Pages (gh-pages branch).

V1.0: GitHub Pages deploy (gh-pages: root=latest, d/<date>/=permanent)
V1.5: static 模式(DEPLOY_MODE=static):仅留本地静态副本,由 web_console /quiz 自托管,
      URL 基于 PUBLIC_BASE_URL(服务器自托管,不依赖 GitHub)
V2.0: Xiaohongshu shop integration
"""

import os
from pathlib import Path
from loguru import logger
from utils.review import save
from utils.health import note
from utils.stream_bus import emit as _bus_emit


def _step(message: str) -> None:
    """向流式总线发进度提示(web 控制台可见;日常调度无消费者时 no-op)。"""
    _bus_emit({"event": "step", "message": message})


def publisher_node(state: dict) -> dict:
    """Deploy generated HTML + screenshots to GitHub Pages via gh-pages branch."""
    html_content = state.get("generated_html", "")
    topic = state.get("selected_topic", "test")
    scheduled_time = state.get("scheduled_publish_time")

    if not html_content:
        logger.warning("Publisher: no HTML to deploy")
        return {"html_url": "", "xhs_note_id": ""}

    deploy_dir = Path(__file__).resolve().parent.parent.parent.parent / "output" / "deploy" / "latest"
    deploy_dir.mkdir(parents=True, exist_ok=True)
    (deploy_dir / "index.html").write_text(html_content, encoding="utf-8")

    # 封面/商品图截图(部署前生成,随站点一起上线;失败不阻塞主流程)
    capture_ok = True
    try:
        _step("正在生成三张封面图(浏览器渲染,约30-40秒)…")
        from utils.cover_shots import capture_cover_images
        capture_cover_images(deploy_dir / "index.html", deploy_dir)
        _step("封面图生成完成")
        logger.info("Publisher: cover images generated")
    except Exception as e:
        capture_ok = False
        logger.warning(f"Publisher: cover capture failed (posting will degrade): {e}")
        note("publisher", "capture_failed", str(e)[:200])
        for stale in ("cover.png", "result.png", "product.png"):
            p = deploy_dir / stale
            if p.exists():
                p.unlink()
                logger.info(f"Publisher: removed stale/partial image {p.name}")

    from datetime import datetime
    date_str = datetime.now().strftime("%Y-%m-%d/%H%M%S")   # 时间子目录 → 同一天每轮唯一 URL
    deploy_mode = os.getenv("DEPLOY_MODE", "gh_pages")
    if deploy_mode == "static":
        # 服务器自托管:仅留本地静态副本(web_console /quiz 路由服务),URL 基于 PUBLIC_BASE_URL
        logger.info("Publisher: staging static copy (DEPLOY_MODE=static)...")
        try:
            _step("正在发布到静态目录…")
            from utils.ghpages_deploy import derive_static_urls, _stage_local_copy
            _stage_local_copy(deploy_dir, date_str)
            urls = derive_static_urls(os.getenv("PUBLIC_BASE_URL", ""), date_str)
            if not urls["html_url"]:
                raise RuntimeError("DEPLOY_MODE=static 需要 PUBLIC_BASE_URL 环境变量")
            url = urls["html_url"]
            image_urls = {k: urls[k] for k in ("cover_image_url", "result_image_url", "product_image_url")} if capture_ok \
                else {"cover_image_url": "", "result_image_url": "", "product_image_url": ""}
            _step("发布完成")
        except Exception as e:
            logger.warning(f"Publisher: static staging failed ({e}) — using local path")
            note("publisher", "deploy_failed", str(e)[:200])
            url = str(deploy_dir / "index.html")
            image_urls = {"cover_image_url": "", "result_image_url": "", "product_image_url": ""}
    else:
        logger.info("Publisher: deploying to GitHub Pages...")
        try:
            _step("正在上传到 GitHub Pages(约10-20秒)…")
            from utils.ghpages_deploy import deploy_to_ghpages
            urls = deploy_to_ghpages(deploy_dir, date_str)
            url = urls["html_url"]
            if capture_ok:
                image_urls = {k: urls[k] for k in ("cover_image_url", "result_image_url", "product_image_url")}
            else:
                image_urls = {"cover_image_url": "", "result_image_url": "", "product_image_url": ""}
                logger.warning("Publisher: deploy ok but capture failed — image URLs left empty for message degradation")
            _step("发布完成")
        except Exception as e:
            logger.warning(f"Publisher: deploy failed ({e}) — using local path")
            note("publisher", "deploy_failed", str(e)[:200])
            url = str(deploy_dir / "index.html")
            image_urls = {"cover_image_url": "", "result_image_url": "", "product_image_url": ""}

    save("publisher", "deploy_result.json", {"url": url, "topic": topic, **image_urls})
    return {"html_url": url, "xhs_note_id": "", "actual_publish_time": scheduled_time, **image_urls}
