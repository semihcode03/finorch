"""APScheduler ile zamanlanmis surekli calisma."""

from __future__ import annotations

import logging

from apscheduler.schedulers.blocking import BlockingScheduler

from finorch.config import settings
from finorch.pipeline import run_once

logger = logging.getLogger(__name__)


def start() -> None:
    scheduler = BlockingScheduler(timezone="Europe/Istanbul")
    interval = max(1, settings.poll_interval_minutes)

    scheduler.add_job(
        run_once,
        "interval",
        minutes=interval,
        id="pipeline",
        max_instances=1,
        coalesce=True,
        next_run_time=None,
    )
    logger.info("Zamanlayici basladi (her %d dakikada bir). Ilk dongu simdi calisiyor...", interval)

    # Baslangicta bir kez hemen calistir
    try:
        run_once()
    except Exception as e:
        logger.error("Ilk dongu hatasi: %s", e)

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Zamanlayici durduruldu.")
