"""发帖素材消息组装 — 纯函数,便于单测。"""

from datetime import datetime

from loguru import logger


def derive_image_urls(base_url: str) -> dict:
    """由部署 base URL 推导 3 张图片公网 URL。空串输入→三个空串。

    调用方约定:仅部署成功时传入真实 URL(Vercel hostname 或完整 URL),
    部署失败传空串。不会收到本地路径。
    """
    if not base_url:
        return {"cover_image_url": "", "result_image_url": "", "product_image_url": ""}
    base = base_url.strip().rstrip("/")
    if not base.startswith(("http://", "https://")):
        base = "https://" + base
    return {
        "cover_image_url": f"{base}/cover.png",
        "result_image_url": f"{base}/result.png",
        "product_image_url": f"{base}/product.png",
    }


def _format_publish_time(value) -> str:
    if isinstance(value, datetime):
        return value.strftime("%m-%d %H:%M")
    if isinstance(value, str) and value:
        return value[:16].replace("T", " ")
    return "未定"


def build_message(state: dict) -> str | None:
    """组装钉钉「发帖素材」markdown 消息体(不含 title)。

    输入 workflow 结果 state;packaging_text 缺失/空白时返回 None。
    降级规则(spec 第5节):
    - 部署失败(html_url 非 http) → 链接行替换为部署失败提示,无图片行
    - 部署成功但截图失败(图片 URL 缺失) → 保留链接,图片行替换为配图提示
    """
    copy_text = (state.get("packaging_text") or "").strip()
    if not copy_text:
        return None

    html_url = state.get("html_url") or ""
    cover = state.get("cover_image_url") or ""
    result = state.get("result_image_url") or ""
    product = state.get("product_image_url") or ""

    lines = [
        f"**文案**: {copy_text}",
        f"**建议发布时间**: {_format_publish_time(state.get('scheduled_publish_time'))}",
    ]

    deploy_ok = html_url.startswith(("http://", "https://"))
    if deploy_ok:
        lines.append(f"**商品链接**: {html_url}")
    else:
        lines.append(f"⚠️ **部署失败,商品链接与图片无公网 URL**(本地: {html_url or '无'})")

    lines.append(
        "**操作**: App → 发笔记 → 贴文案 → 传2张封面 → 定时发布 → 橱窗传商品主图 → 关联笔记"
    )

    if cover and result and product:
        lines.append(f"![封面-起始页]({cover})")
        lines.append(f"![封面-结果页]({result})")
        lines.append(f"![商品主图]({product})")
    elif deploy_ok:
        lines.append("⚠️ **封面图生成失败,请自行配图**")

    return "\n\n".join(lines)
