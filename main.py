"""
Redbook Agent Group — Main entry point.

Usage:
    python main.py              # Run full daily workflow once
    python main.py --schedule   # Start daily scheduler (08:00)

MVP flow (6 agents wired):
    data_analyst → navigator → trend_hunter → generator → packager → auditor
"""

import sys
from dotenv import load_dotenv
load_dotenv()
from loguru import logger

logger.add(
    "logs/app.log",
    rotation="10 MB",
    retention="7 days",
    level="INFO",
)
logger.add(
    sys.stderr,
    level="INFO",
    format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>",
)


def run_once():
    """Execute the full daily workflow once."""
    from utils.review import start_run, REVIEW_MODE
    from graph.workflow import get_app

    run_id = start_run()
    if REVIEW_MODE:
        logger.info(f"Review mode ON — outputs will be saved to output/{run_id}/")

    app = get_app()
    config = {"configurable": {"thread_id": f"run-{run_id}"}}

    initial_state = {
        "user_command": "daily_auto_run",
        "retry_count": 0,
        "review_retry_count": 0,
        "review_fixes_needed": [],
        "error_occurred": False,
    }

    logger.info("=" * 50)
    logger.info("Starting daily workflow...")
    logger.info("=" * 50)

    # Agent-panorama live callback (one-line observability)
    callbacks = []
    try:
        from agent_panorama.live import PanoramaCallbackHandler
        callbacks.append(PanoramaCallbackHandler())
        logger.info("Agent-panorama callback enabled")
    except ImportError:
        logger.debug("agent-panorama not installed — skipping live callback")

    try:
        result = app.invoke(initial_state, config, callbacks=callbacks if callbacks else None)

        # Summary
        logger.info("=" * 50)
        logger.info("Workflow complete!")
        topic = result.get('selected_topic', 'N/A')
        questions = result.get('target_question_count', 0)
        price = result.get('suggested_price', 0)
        audit = result.get('audit_status', 'N/A')
        html_url = result.get('html_url', 'N/A')
        audit_retries = result.get('retry_count', 0)
        review_retries = result.get('review_retry_count', 0)
        review_score = result.get('review_score', 'N/A')
        logger.info(f"  Topic:     {topic}")
        logger.info(f"  Questions: {questions}")
        logger.info(f"  Price:     ¥{price}")
        logger.info(f"  Reviewer:  {review_score}/10 (review retries: {review_retries})")
        logger.info(f"  Audit:     {audit} (audit retries: {audit_retries})")
        logger.info(f"  HTML:      {html_url}")
        logger.info("=" * 50)

        # DingTalk notification — clean format
        from utils.notifier import notifier
        from utils.token_tracker import summary as token_summary, reset as token_reset
        from datetime import datetime

        cost = token_summary()
        total_cost = cost["total_cost"]
        agent_cn = {
            "data_analyst": "数据分析", "navigator": "领航员", "trend_hunter": "热点嗅探",
            "generator_b1": "生成器", "packager_style": "风格", "packager_analysis": "分析",
            "packager_personality": "人格", "packager_copy": "文案", "reviewer": "评审",
        }
        detail = "  \n".join([
            f"> {agent_cn.get(b['agent'], b['agent'])}: {b['total']}tokens / ¥{b['cost']:.4f}"
            for b in cost["breakdown"]
        ]) if cost["breakdown"] else "> 无LLM调用记录"

        now = datetime.now().strftime("%m-%d %H:%M")
        revenue = 0.0
        profit = revenue - total_cost
        roi_text = f"{(revenue - total_cost) / total_cost * 100:.0f}%" if total_cost > 0 else "N/A"
        warning = "⚠️ **当日亏损! 收入¥0.00 - 花费¥{:.4f} = ¥{:.4f}**".format(total_cost, profit) if profit < 0 else ""

        report = (
            f"## 小红书Agent日报 - {now}\n\n"
            f"**选题**: {topic}  \n"
            f"**题量**: {questions}题 | **定价**: ¥{price}  \n"
            f"**评分**: {review_score}/10 (评审重修{review_retries}次) | **审核**: {audit} (审核重修{audit_retries}次)  \n"
            f"**链接**: [打开测试]({html_url})  \n"
            f"\n"
            f"### 花费\n"
            f"**总花费: ¥{total_cost:.4f}**  \n"
            f"明细:  \n"
            f"{detail}  \n"
            f"\n"
            f"{warning}\n\n" if warning else ""
            f"### 收益\n"
            f"> 今日新增订单: 0 单  \n"
            f"> 今日新增GMV: ¥0.00  \n"
            f"> 累计总GMV: ¥0.00  \n"
            f"> 投入产出比(ROI): {roi_text}  \n"
            f"\n"
            f"小红书"  # keyword for DingTalk filter
        )

        try:
            notifier.send(title=f"小红书日报 - {topic}", content=report, level="info")
            token_reset()
        except Exception as e:
            logger.warning(f"Notification failed: {e}")

        return result

    except Exception as e:
        logger.error(f"Workflow crashed: {e}")
        raise


def run_scheduled():
    """Start the 08:00 daily scheduler."""
    from scheduler.daily_trigger import start_scheduler, stop_scheduler

    try:
        start_scheduler(run_once)
        logger.info("Scheduler running. Press Ctrl+C to stop.")
        import time
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        stop_scheduler()
        logger.info("Scheduler stopped.")


if __name__ == "__main__":
    if "--schedule" in sys.argv:
        logger.info("Starting scheduled mode (daily at 08:00)...")
        run_scheduled()
    else:
        run_once()
