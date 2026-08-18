"""Order model — 订单表."""

import uuid
from datetime import datetime
from sqlalchemy import Column, String, Float, DateTime, ForeignKey
from models.base import Base


class Order(Base):
    __tablename__ = "orders"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    product_id = Column(String(36), ForeignKey("products.id"), nullable=False)
    platform_order_id = Column(String(100), default="")
    gmv = Column(Float, default=0.0)
    created_at = Column(DateTime, default=datetime.utcnow)
