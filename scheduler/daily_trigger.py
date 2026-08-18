"""APScheduler daily trigger — fires at 08:00 local time."""

from apscheduler.schedulers.background import BackgroundScheduler
from loguru import logger

scheduler = BackgroundScheduler()


def start_scheduler(run_func):
    """Register the main workflow (daily 08:00) + weekly scraper (Mon 07:00)."""
    scheduler.add_job(
        run_func,
        trigger="cron",
        hour=8,
        minute=0,
        id="daily_main_workflow",
        replace_existing=True,
    )
    # Weekly topic pool refresh: Monday 07:00
    from tools.xhs_scraper import run_scrape
    scheduler.add_job(
        run_scrape,
        trigger="cron",
        day_of_week="mon",
        hour=7,
        minute=0,
        id="weekly_scraper",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("Scheduler: daily 08:00 workflow + Mon 07:00 scraper")


def stop_scheduler():
    scheduler.shutdown(wait=False)
