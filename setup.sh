#!/usr/bin/env bash
# Local setup helper for the Auction Intelligence Platform.
set -euo pipefail

echo "▶ Creating virtual environment..."
python3 -m venv venv
source venv/bin/activate

echo "▶ Installing dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

if [ ! -f .env ]; then
  echo "▶ Creating .env from template (edit it before running)..."
  cp .env.example .env
fi

echo "▶ Creating database (skips if it already exists)..."
createdb auction_intel 2>/dev/null || echo "  database already exists — continuing"

echo "▶ Running migrations..."
python manage.py makemigrations auctions
python manage.py migrate

echo ""
echo "✓ Setup complete."
echo ""
echo "Next steps:"
echo "  python manage.py createsuperuser"
echo "  python manage.py crawl --source=delaware --dry-run"
echo "  python manage.py crawl --source=delaware"
echo "  python manage.py analyze"
echo "  python manage.py runserver"
