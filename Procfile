# Single-service deployment (default, USE_CELERY=False).
# Crawls and analysis run inline from the admin UI — no Redis required.
web: bash start.sh

# Optional: only needed if you set USE_CELERY=True and provide a broker.
# worker: celery -A auction_intel worker -l info --concurrency 2
# beat: celery -A auction_intel beat -l info --scheduler django_celery_beat.schedulers:DatabaseScheduler
