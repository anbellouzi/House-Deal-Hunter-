"""
Celery application entrypoint.

Only imported when USE_CELERY=True. Without a broker the project runs in
inline mode instead — see apps/sources/runner.py.
"""
import os

from celery import Celery
from celery.schedules import crontab

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "auction_intel.settings")

app = Celery("auction_intel")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

app.conf.beat_schedule = {
    "crawl-bid4assets-every-6h": {
        "task": "apps.sources.tasks.crawl_bid4assets",
        "schedule": crontab(minute=0, hour="*/6"),
    },
    "crawl-delaware-county-daily": {
        "task": "apps.sources.tasks.crawl_delaware_county",
        "schedule": crontab(minute=0, hour=6),
    },
    "refresh-active-every-30min": {
        "task": "apps.sources.tasks.refresh_active_auctions",
        "schedule": crontab(minute="*/30"),
    },
    "refresh-closing-soon-every-5min": {
        "task": "apps.sources.tasks.refresh_closing_soon",
        "schedule": crontab(minute="*/5"),
    },
    "run-analysis-hourly": {
        "task": "apps.sources.tasks.run_analysis",
        "schedule": crontab(minute=15),
    },
}
