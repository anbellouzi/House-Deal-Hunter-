"""
Job dispatch layer.

The project supports two execution modes:

  INLINE  (default, USE_CELERY=False)
      Jobs run synchronously in the web process. No Redis, no worker,
      no beat — a single service plus Postgres. Suitable when your
      crawl targets are small and infrequent, which is the case for
      county sheriff sale PDFs that publish roughly monthly.

  CELERY  (USE_CELERY=True)
      Jobs are queued to a broker and executed by a worker process,
      with beat handling the schedule. Needed once crawls grow long
      enough to exceed an HTTP request timeout.

Callers use dispatch() and don't care which mode is active. This keeps
the admin actions and management commands identical across both.
"""
import logging
from typing import Callable, Optional

from django.conf import settings

logger = logging.getLogger(__name__)

# Inline jobs longer than this are risky behind a proxy with a request
# timeout. The Delaware County PDF crawl finishes well under it; the
# Bid4Assets crawl does not, because it enforces a polite 5s delay per
# request. dispatch() warns rather than blocking — the caller decides.
INLINE_SAFE_SECONDS = 25


def celery_enabled() -> bool:
    return getattr(settings, "USE_CELERY", False)


def dispatch(job: Callable, *args, inline_ok: bool = True, **kwargs) -> dict:
    """
    Run a job via Celery if available, otherwise inline.

    Args:
        job: a function, or a Celery task (which is also callable directly)
        inline_ok: set False for jobs too slow to run in a web request.
                   In inline mode these are refused rather than risking
                   a gateway timeout mid-crawl.

    Returns a dict describing what happened, suitable for showing the user.
    """
    name = getattr(job, "__name__", str(job))

    if celery_enabled():
        try:
            job.delay(*args, **kwargs)
            return {
                "mode": "queued",
                "job": name,
                "message": f"{name} queued to the worker.",
            }
        except Exception as exc:
            # Broker unreachable — fall back rather than losing the request.
            logger.warning(f"Could not queue {name} ({exc}); running inline.")

    if not inline_ok:
        return {
            "mode": "refused",
            "job": name,
            "message": (
                f"{name} is too slow to run inline. Either set USE_CELERY=True "
                f"with a broker, or run it from the CLI: "
                f"python manage.py crawl --source=bid4assets"
            ),
        }

    # Inline execution. Celery tasks are callable directly, which bypasses
    # the broker entirely and just runs the function body.
    try:
        result = job(*args, **kwargs)
        return {
            "mode": "inline",
            "job": name,
            "result": result,
            "message": f"{name} completed.",
        }
    except Exception as exc:
        logger.exception(f"{name} failed inline")
        return {
            "mode": "failed",
            "job": name,
            "error": str(exc),
            "message": f"{name} failed: {exc}",
        }
