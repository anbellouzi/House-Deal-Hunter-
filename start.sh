#!/usr/bin/env bash
# Railway web service entrypoint.
# Runs everything needed on each deploy so no shell access is required.
set -e

echo "▶ Running migrations..."
python manage.py migrate --noinput

echo "▶ Collecting static files..."
python manage.py collectstatic --noinput

echo "▶ Bootstrapping admin user (skips if already present)..."
python manage.py bootstrap_admin

echo "▶ Starting gunicorn..."
exec gunicorn auction_intel.wsgi:application \
  --bind 0.0.0.0:${PORT:-8000} \
  --workers ${WEB_CONCURRENCY:-2} \
  --timeout 120 \
  --access-logfile - \
  --error-logfile -
