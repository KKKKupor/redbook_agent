"""
Quality review mode — when enabled, each agent writes its full
input/output/reasoning to output/{run_id:02d}/{agent_name}/.

Control:
  - Env var REVIEW_MODE=true  →  enabled (quality audit)
  - Env var REVIEW_MODE=false or unset → disabled (production)

Run ID auto-increments: 01, 02, 03...
"""

import os
import json
from datetime import datetime
from pathlib import Path
from loguru import logger

REVIEW_MODE = os.getenv("REVIEW_MODE", "false").lower() in ("true", "1", "yes")
OUTPUT_BASE = Path(__file__).resolve().parent.parent / "output"

_auto_run_id = None


def _get_run_id() -> str:
    """Find the next available run ID by scanning output/."""
    global _auto_run_id
    if _auto_run_id:
        return _auto_run_id
    n = 1
    while (OUTPUT_BASE / f"{n:02d}").exists():
        n += 1
    _auto_run_id = f"{n:02d}"
    return _auto_run_id


def is_enabled() -> bool:
    return REVIEW_MODE


def _cleanup_old_runs(keep: int = 7):
    """Keep only the most recent N runs. Deletes older ones."""
    if not OUTPUT_BASE.exists():
        return
    runs = sorted(
        [d for d in OUTPUT_BASE.iterdir() if d.is_dir() and d.name[:2].isdigit()],
        key=lambda x: x.name,
        reverse=True,
    )
    for old in runs[keep:]:
        import shutil
        shutil.rmtree(old)
        logger.debug(f"[REVIEW] Cleaned up old run: {old.name}")


def start_run() -> str:
    """Begin a new review run. Returns run_id. Auto-cleans old runs."""
    rid = _get_run_id()
    if REVIEW_MODE:
        _cleanup_old_runs(keep=7)
        logger.info(f"[REVIEW] Starting run {rid}")
    return rid


def save(agent_name: str, filename: str, data, run_id: str = None):
    """Save agent output to output/{run_id}/{agent_name}/{filename}.

    Args:
        agent_name: e.g. 'navigator', 'generator'
        filename:   e.g. 'decision.json', 'questions.json'
        data:       dict, list, or string — anything JSON-serializable
        run_id:     auto-detected if None
    """
    if not REVIEW_MODE:
        return

    rid = run_id or _get_run_id()
    agent_dir = OUTPUT_BASE / rid / agent_name
    agent_dir.mkdir(parents=True, exist_ok=True)

    path = agent_dir / filename
    if isinstance(data, (dict, list)):
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        path.write_text(str(data), encoding="utf-8")

    logger.debug(f"[REVIEW] {rid}/{agent_name}/{filename}")


def save_prompt(agent_name: str, prompt_text: str, run_id: str = None):
    """Save the full LLM prompt used by an agent."""
    if not REVIEW_MODE:
        return
    rid = run_id or _get_run_id()
    agent_dir = OUTPUT_BASE / rid / agent_name
    agent_dir.mkdir(parents=True, exist_ok=True)
    (agent_dir / "_prompt.txt").write_text(prompt_text, encoding="utf-8")


def save_response(agent_name: str, response_text: str, run_id: str = None):
    """Save the raw LLM response from an agent."""
    if not REVIEW_MODE:
        return
    rid = run_id or _get_run_id()
    agent_dir = OUTPUT_BASE / rid / agent_name
    agent_dir.mkdir(parents=True, exist_ok=True)
    (agent_dir / "_response.txt").write_text(response_text, encoding="utf-8")
