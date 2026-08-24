"""
Celery is optional.

When USE_CELERY is false (the default), the app runs without a broker:
crawls and analysis execute synchronously when triggered from the admin.
This keeps the deployment to a single service plus Postgres — no Redis,
no worker, no beat.
"""
import os

if os.environ.get("USE_CELERY", "False").lower() in ("true", "1", "yes"):
    from .celery import app as celery_app
    __all__ = ("celery_app",)
else:
    __all__ = ()
