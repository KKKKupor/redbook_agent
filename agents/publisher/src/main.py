"""
Upload Agent (Publisher) — deploy HTML to Vercel for public URL.

V1.0: Vercel CLI (shell=True to find npx in user PATH)
V2.0: Xiaohongshu shop integration
"""

import subprocess
from pathlib import Path
from loguru import logger
from utils.review import save


def _deploy_to_vercel(deploy_dir: str, max_retries: int = 1) -> str:
    """Deploy directory (must contain index.html + vercel.json) to Vercel.

    Uses shell=True so npx is found via user PATH on Windows.
    Retries once on failure (network timeouts are common with Vercel CLI).
    """
    import time
    vercel_cfg = Path(deploy_dir) / "vercel.json"
    if not vercel_cfg.exists():
        vercel_cfg.write_text('{"version": 2}', encoding="utf-8")

    last_error = ""
    for attempt in range(max_retries + 1):
        try:
            result = subprocess.run(
                f'npx vercel "{deploy_dir}" --prod --yes',
                capture_output=True, text=True, timeout=60,
                cwd=deploy_dir, shell=True,
                encoding="utf-8", errors="replace",
            )
            output = (result.stdout or "") + (result.stderr or "")
            # Try JSON output format first (Vercel --yes returns JSON)
            import json, re
            try:
                data = json.loads(output)
                url = data.get("deployment", {}).get("url", "") or data.get("url", "")
                if url:
                    logger.info(f"Publisher: deployed -> {url} (attempt {attempt+1})")
                    return url
            except json.JSONDecodeError:
                pass
            # Fallback: text output format
            for line in output.split("\n"):
                line = line.strip()
                if "https://" in line and "vercel.app" in line:
                    url = re.search(r'https://[^\s"]+', line)
                    if url:
                        logger.info(f"Publisher: deployed -> {url.group()} (attempt {attempt+1})")
                        return url.group()
            last_error = f"No URL found. Output: {output[:300]}"
        except Exception as e:
            last_error = str(e)

        if attempt < max_retries:
            logger.warning(f"Publisher: deploy attempt {attempt+1} failed ({last_error[:100]}) — retrying in 5s...")
            time.sleep(5)

    logger.error(f"Publisher: deploy failed after {max_retries+1} attempts: {last_error[:200]}")
    return ""


def publisher_node(state: dict) -> dict:
    """Deploy generated HTML to public URL via Vercel."""
    html_content = state.get("generated_html", "")
    topic = state.get("selected_topic", "test")
    scheduled_time = state.get("scheduled_publish_time")

    if not html_content:
        logger.warning("Publisher: no HTML to deploy")
        return {"html_url": "", "xhs_note_id": ""}

    deploy_dir = Path(__file__).resolve().parent.parent.parent.parent / "output" / "deploy" / "latest"
    deploy_dir.mkdir(parents=True, exist_ok=True)
    (deploy_dir / "index.html").write_text(html_content, encoding="utf-8")
    (deploy_dir / "vercel.json").write_text('{"version": 2}', encoding="utf-8")

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

    logger.info("Publisher: deploying to Vercel...")
    url = _deploy_to_vercel(str(deploy_dir))

    from utils.posting_materials import derive_image_urls
    if url and capture_ok:
        image_urls = derive_image_urls(url)
    else:
        if url:
            logger.warning("Publisher: deploy ok but capture failed — image URLs left empty for message degradation")
        else:
            url = str(deploy_dir / "index.html")
            logger.warning(f"Publisher: using local path: {url}")
        image_urls = {"cover_image_url": "", "result_image_url": "", "product_image_url": ""}

    save("publisher", "deploy_result.json", {"url": url, "topic": topic, **image_urls})
    return {"html_url": url, "xhs_note_id": "", "actual_publish_time": scheduled_time, **image_urls}
