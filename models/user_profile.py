"""User profile model — 用户画像表（脱敏）."""

import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime, JSON, ForeignKey
from models.base import Base


class UserProfile(Base):
    __tablename__ = "user_profiles"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    product_id = Column(String(36), ForeignKey("products.id"), nullable=False)
    dimension_scores = Column(JSON, default=dict)   # {D1:85, D2:62, ...}
    personality_tag = Column(String(10), default="")
    answer_pattern = Column(JSON, default=dict)      # 选项统计，无个人标识
    created_at = Column(DateTime, default=datetime.utcnow)
