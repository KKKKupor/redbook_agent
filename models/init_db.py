"""Initialize database: create tables + seed sample data.

Usage: python models/init_db.py
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv()

from models.base import Base, get_engine, get_session
from models.product import Product
from models.order import Order
from models.strategy_log import StrategyLog
from models.user_profile import UserProfile


def init():
    engine = get_engine()
    Base.metadata.create_all(engine)
    print("Tables created.")

    session = get_session()

    # Seed sample products if table is empty
    if session.query(Product).count() == 0:
        products = [
            Product(
                name="MBTI职场性格测试",
                topic="MBTI职场",
                question_count=60,
                price=3.99,
                status="published",
                dimension_defs=[
                    {"id": "D1", "name": "外向性", "high_label": "社交驱动", "low_label": "独立思考"},
                    {"id": "D2", "name": "信息处理", "high_label": "直觉先行", "low_label": "务实导向"},
                    {"id": "D3", "name": "决策风格", "high_label": "逻辑主导", "low_label": "情感主导"},
                    {"id": "D4", "name": "工作节奏", "high_label": "计划先行", "low_label": "随遇而安"},
                    {"id": "D5", "name": "领导潜力", "high_label": "天生领袖", "low_label": "潜力待发"},
                    {"id": "D6", "name": "压力应对", "high_label": "韧性十足", "low_label": "敏感细腻"},
                ],
            ),
            Product(
                name="你的隐藏人格是什么",
                topic="心理情感",
                question_count=50,
                price=5.99,
                status="published",
            ),
            Product(
                name="测测你的抗压指数",
                topic="职场能力",
                question_count=50,
                price=3.99,
                status="published",
            ),
            Product(
                name="恋爱人格匹配测试",
                topic="恋爱关系",
                question_count=40,
                price=6.99,
                status="draft",
            ),
        ]
        session.add_all(products)
        session.commit()
        print(f"Seeded {len(products)} products.")

        # Seed sample orders
        from datetime import datetime, timedelta
        import random
        orders = []
        for prod in products[:3]:  # Only published products have orders
            for days_ago in range(7):
                count = random.randint(0, 5)
                for _ in range(count):
                    orders.append(Order(
                        product_id=prod.id,
                        gmv=prod.price,
                        created_at=datetime.utcnow() - timedelta(days=days_ago, hours=random.randint(0, 23)),
                    ))
        if orders:
            session.add_all(orders)
            session.commit()
            print(f"Seeded {len(orders)} orders.")

    session.close()
    print("Done.")


if __name__ == "__main__":
    init()
