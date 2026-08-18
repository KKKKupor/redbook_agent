"""
LangGraph global State schema definition.

All 9 agents communicate through this shared state,
passed along edges of the StateGraph.
"""

from datetime import datetime
from typing import TypedDict, Optional


class AgentState(TypedDict, total=False):
    # ===== Input =====
    user_command: str

    # ===== Navigator decisions =====
    selected_topic: str
    target_question_count: int
    suggested_price: float
    scheduled_publish_time: datetime
    decision_reasoning: str

    # ===== Generation output =====
    dimension_defs: list
    questions_json: dict
    generated_html: str
    packaging_text: str

    # ===== Audit =====
    audit_status: str          # "pass" | "fail"
    audit_feedback: str
    retry_count: int

    # ===== Publishing =====
    html_url: str
    xhs_note_id: str
    actual_publish_time: datetime
    cover_image_url: str
    result_image_url: str
    product_image_url: str

    # ===== Cost & Monitoring =====
    total_token_cost: float
    cost_breakdown: dict
    git_commit_hash: str

    # ===== Data recovery (async) =====
    daily_gmv: float
    comment_sentiment: dict

    # ===== Quality review =====
    review_score: float
    review_verdict: str
    review_retry_count: int       # how many times reviewer sent back to generator
    review_fixes_needed: list     # structured fixes from reviewer → generator

    # ===== Error handling =====
    error_occurred: bool
    error_trace: str
    heal_attempted: bool
    heal_depth: int
