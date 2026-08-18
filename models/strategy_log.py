"""Strategy log model — 策略日志表."""

import uuid
from datetime import datetime, date
from sqlalchemy import Column, String, Integer, Float, Text, DateTime, Date, JSON
from models.base import Base


class StrategyLog(Base):
    __tablename__ = "strategy_logs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    run_date = Column(Date, default=date.today)
    selected_topic = Column(String(50))
    target_questions = Column(Integer, default=50)
    suggested_price = Column(Float, default=3.99)
    actual_publish_time = Column(DateTime, nullable=True)
    token_cost = Column(Float, default=0.0)
    cost_breakdown = Column(JSON, default=dict)
    gmv_total = Column(Float, default=0.0)
    roi = Column(Float, default=0.0)
    decision_reasoning = Column(Text, default="")
