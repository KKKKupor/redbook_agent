"""
Upload Agent (Publisher) — deploy HTML to GitHub Pages (gh-pages branch).

V1.0: GitHub Pages deploy (gh-pages: root=latest, d/<date>/=permanent)
V2.0: Xiaohongshu shop integration
"""

from pathlib import Path
from loguru import logger
from utils.review import save


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
        from utils.cover_shots import capture_cover_images
        capture_cover_images(deploy_dir / "index.html", deploy_dir)
        logger.info("Publisher: cover images generated")
    except Exception as e:
        capture_ok = False
        logger.warning(f"Publisher: cover capture failed (posting will degrade): {e}")
        for stale in ("cover.png", "result.png", "product.png"):
            p = deploy_dir / stale
            if p.exists():
                p.unlink()
                logger.info(f"Publisher: removed stale/partial image {p.name}")

    logger.info("Publisher: deploying to GitHub Pages...")
    from datetime import datetime
    date_str = datetime.now().strftime("%Y-%m-%d")
    try:
        from utils.ghpages_deploy import deploy_to_ghpages
        urls = deploy_to_ghpages(deploy_dir, date_str)
        url = urls["html_url"]
        if capture_ok:
            image_urls = {k: urls[k] for k in ("cover_image_url", "result_image_url", "product_image_url")}
        else:
            image_urls = {"cover_image_url": "", "result_image_url": "", "product_image_url": ""}
            logger.warning("Publisher: deploy ok but capture failed — image URLs left empty for message degradation")
    except Exception as e:
        logger.warning(f"Publisher: deploy failed ({e}) — using local path")
        url = str(deploy_dir / "index.html")
        image_urls = {"cover_image_url": "", "result_image_url": "", "product_image_url": ""}

    save("publisher", "deploy_result.json", {"url": url, "topic": topic, **image_urls})
    return {"html_url": url, "xhs_note_id": "", "actual_publish_time": scheduled_time, **image_urls}
