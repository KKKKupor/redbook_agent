"""Product model — 商品表."""

import uuid
from datetime import datetime
from sqlalchemy import Column, String, Integer, Float, Text, DateTime, JSON
from models.base import Base


class Product(Base):
    __tablename__ = "products"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(200), nullable=False)
    topic = Column(String(50), nullable=False)  # e.g. "MBTI职场", "心理情感"
    question_count = Column(Integer, default=50)
    price = Column(Float, default=3.99)
    html_url = Column(String(500), default="")
    dimension_defs = Column(JSON, default=list)
    personality_mapping = Column(JSON, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow)
    published_at = Column(DateTime, nullable=True)
    status = Column(String(20), default="draft")  # draft | published | archived
