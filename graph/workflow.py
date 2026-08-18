"""
Main LangGraph workflow — orchestrates all 9 Agents.

Daily flow:
  START → data_analyst → navigator → trend_hunter
       → generator → packager → reviewer
       → [score≥6: auditor | score<6: generator (review retry, max 2)]
       → auditor → [pass: publisher | fail: generator (audit retry, max 3)]
       → publisher → END

Review feedback loop (Evaluator-Optimizer pattern):
  reviewer scores < 6 → back to generator with fixes_needed
  This is the primary quality gate — catches weak content before audit.

Error flow:
  Any node error → self_healer → [healed: resume | fatal: END]
"""

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from loguru import logger

from graph.state import AgentState
from agents.navigator.src.main import navigator_node
from agents.data_analyst.src.main import data_analyst_node
from agents.trend_hunter.src.main import trend_hunter_node
from agents.generator.src.main import generator_node
from agents.packager.src.main import packager_node
from agents.reviewer.src.main import reviewer_node
from agents.auditor.src.main import auditor_node
from agents.publisher.src.main import publisher_node


# ─── Conditional edges ──────────────────────────────────────────────────────

def review_gate(state: AgentState) -> str:
    """Evaluator-Optimizer: reviewer score < 6 → back to generator for redo.

    Gives the generator up to 2 chances to fix quality issues flagged by reviewer.
    Reviewer's fixes_needed (structured per-section/dimension instructions) is
    passed through state so the generator can do targeted fixes.
    """
    score = state.get("review_score", 0)
    verdict = state.get("review_verdict", "revise")
    retries = state.get("review_retry_count", 0)
    max_review_retries = 2

    if score >= 6 or verdict == "approve":
        logger.info(f"Review score {score}/10 ≥ 6 → passing to auditor")
        return "auditor"

    if retries >= max_review_retries:
        logger.warning(f"Review score {score}/10 after {retries} review retries → passing anyway (max reached)")
        return "auditor"

    logger.info(f"Review score {score}/10 < 6 (retry {retries+1}/{max_review_retries}) → back to generator with fixes")
    return "generator"


def audit_gate(state: AgentState) -> str:
    """Decide next node after audit: pass → publisher, fail+retries<3 → retry, fail+retries≥3 → publisher."""
    status = state.get("audit_status", "fail")
    retries = state.get("retry_count", 0)

    if status == "pass":
        logger.info("Audit PASSED → publishing")
        return "publisher"

    if retries >= 3:
        logger.warning(f"Audit FAILED after {retries} retries → publishing anyway")
        return "publisher"

    logger.info(f"Audit FAILED (retry {retries}/3) → regenerating")
    return "generator"


# ─── Build graph ─────────────────────────────────────────────────────────────

def build_workflow() -> StateGraph:
    """Construct the main agent workflow graph."""
    wf = StateGraph(AgentState)

    # Add nodes
    wf.add_node("data_analyst", data_analyst_node)
    wf.add_node("navigator", navigator_node)
    wf.add_node("trend_hunter", trend_hunter_node)
    wf.add_node("generator", generator_node)
    wf.add_node("packager", packager_node)
    wf.add_node("reviewer", reviewer_node)
    wf.add_node("auditor", auditor_node)
    wf.add_node("publisher", publisher_node)

    # Linear chain: data → decide → hunt → generate → package
    wf.set_entry_point("data_analyst")
    wf.add_edge("data_analyst", "navigator")
    wf.add_edge("navigator", "trend_hunter")
    wf.add_edge("trend_hunter", "generator")
    wf.add_edge("generator", "packager")

    # Evaluator-Optimizer loop: reviewer scores → pass to auditor or back to generator
    wf.add_edge("packager", "reviewer")
    wf.add_conditional_edges(
        "reviewer",
        review_gate,
        {
            "auditor": "auditor",
            "generator": "generator",
        },
    )

    # Audit gate: pass → publisher, fail → retry generator or publish anyway
    wf.add_edge("auditor", "publisher")
    wf.add_edge("publisher", END)
    wf.add_conditional_edges(
        "auditor",
        audit_gate,
        {
            "publisher": "publisher",
            "generator": "generator",
        },
    )

    return wf


def get_app():
    """Return compiled LangGraph app with memory checkpointer."""
    wf = build_workflow()
    memory = MemorySaver()
    return wf.compile(checkpointer=memory)
