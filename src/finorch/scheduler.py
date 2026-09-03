"""APScheduler ile zamanlanmis surekli calisma."""

from __future__ import annotations

import logging

from apscheduler.schedulers.blocking import BlockingScheduler

from finorch.config import settings
from finorch.pipeline import run_once, run_ticker

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

    # Piyasa seridi boru hattindan cok daha sik tazelenir: icerik toplama
    # dakikalar surerken serit birkac saniyelik bir fiyat sorgusudur.
    if settings.ticker_enabled and settings.market_enabled:
        ticker_interval = max(1, settings.ticker_refresh_minutes)
        scheduler.add_job(
            run_ticker,
            "interval",
            minutes=ticker_interval,
            id="ticker",
            max_instances=1,
            coalesce=True,
            next_run_time=None,
        )
        logger.info("Piyasa seridi her %d dakikada bir tazelenecek.", ticker_interval)

    logger.info("Zamanlayici basladi (her %d dakikada bir). Ilk dongu simdi calisiyor...", interval)

    # Baslangicta bir kez hemen calistir. Serit once gelsin ki dashboard
    # uzun suren ilk icerik dongusunu beklemeden dolu gorunsun.
    try:
        run_ticker()
        run_once()
    except Exception as e:
        logger.error("Ilk dongu hatasi: %s", e)

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Zamanlayici durduruldu.")
