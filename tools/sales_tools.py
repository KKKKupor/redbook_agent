"""Data analysis tools — now querying real SQLite database."""

from datetime import datetime, timedelta
from typing import Optional

from langchain_core.tools import tool
from sqlalchemy import func, desc

from models.base import get_session
from models.product import Product
from models.order import Order
from models.strategy_log import StrategyLog


@tool
def get_sales_analytics(product_id: str, days: int = 7) -> dict:
    """查询指定测试题的销量、GMV、转化率。

    Args:
        product_id: 商品UUID
        days: 查询最近N天，默认7天
    """
    session = get_session()
    try:
        since = datetime.utcnow() - timedelta(days=days)
        orders = (
            session.query(Order)
            .filter(Order.product_id == product_id, Order.created_at >= since)
            .all()
        )
        product = session.query(Product).filter(Product.id == product_id).first()
        total_gmv = sum(o.gmv for o in orders)
        sales_count = len(orders)
        return {
            "product_id": product_id,
            "product_name": product.name if product else "unknown",
            "period_days": days,
            "sales_count": sales_count,
            "gmv": round(total_gmv, 2),
            "conversion_rate": f"{min(sales_count / max(1, days * 10) * 100, 100):.1f}%",
            "avg_order_value": round(total_gmv / max(1, sales_count), 2),
        }
    except Exception:
        return {"product_id": product_id, "product_name": "暂无", "period_days": days, "sales_count": 0, "gmv": 0, "conversion_rate": "0%", "avg_order_value": 0}
    finally:
        session.close()


@tool
def get_product_rankings(time_range: str = "7d") -> list:
    """获取自身店铺所有测试题的销量排行。

    Args:
        time_range: 时间范围，7d 或 30d
    """
    days = 30 if time_range == "30d" else 7
    session = get_session()
    try:
        since = datetime.utcnow() - timedelta(days=days)
        results = (
            session.query(
                Product.id,
                Product.name,
                Product.topic,
                func.count(Order.id).label("sales"),
                func.coalesce(func.sum(Order.gmv), 0).label("gmv"),
            )
            .outerjoin(Order, (Order.product_id == Product.id) & (Order.created_at >= since))
            .group_by(Product.id)
            .order_by(desc("sales"))
            .all()
        )

        rankings = []
        for i, r in enumerate(results, 1):
            status = "热销" if r.sales > 10 else ("滞销" if r.sales <= 3 else "一般")
            rankings.append({
                "rank": i, "name": r.name, "topic": r.topic,
                "sales": r.sales, "gmv": round(float(r.gmv), 2), "status": status,
            })
        return rankings if rankings else [{"rank": 0, "name": "暂无数据", "topic": "未知", "sales": 0, "gmv": 0, "status": "无销售"}]
    except Exception:
        return [{"rank": 0, "name": "暂无数据", "topic": "未知", "sales": 0, "gmv": 0, "status": "无销售"}]
    finally:
        session.close()


@tool
def get_competitor_trend(keyword: str) -> dict:
    """分析同类付费测试题的发布时间、定价区间、卖点。（暂用mock）"""
    return {
        "keyword": keyword,
        "hot_publish_hours": [20, 21, 22],
        "price_range": {"min": 3.0, "max": 9.9, "median": 5.99},
        "top_selling_points": ["超准", "免费试3题", "专业心理团队背书"],
        "avg_question_count": 60,
        "_note": "Mock — real data requires XHS search API",
    }


@tool
def time_series_forecast(historical_data: Optional[list] = None) -> dict:
    """基于历史发布时间与销量相关性，预测最佳发布时间段。（暂用mock）"""
    return {
        "best_hour": 21,
        "best_weekday": "周二",
        "confidence": 0.78,
        "reasoning": "基于历史数据，周二晚21点发布的测试题转化率最高",
        "_note": "Mock — real impl uses ML forecast on strategy_logs",
    }


@tool
def get_topic_diversity() -> dict:
    """查询当前商品库各题材占比，用于多样性监控（>40%强制切换）。"""
    session = get_session()
    try:
        total = session.query(func.count(Product.id)).scalar() or 1
        rows = session.query(Product.topic, func.count(Product.id)).group_by(Product.topic).all()
        diversity = {topic: f"{count / total * 100:.0f}%" for topic, count in rows}
        warning = next((t for t, pct in diversity.items() if int(pct.replace("%", "")) > 40), None)
        return {"distribution": diversity, "warning": warning, "total_products": total}
    except Exception:
        return {"distribution": {}, "warning": None, "total_products": 0}
    finally:
        session.close()


ALL_SALES_TOOLS = [
    get_sales_analytics,
    get_product_rankings,
    get_competitor_trend,
    time_series_forecast,
    get_topic_diversity,
]
