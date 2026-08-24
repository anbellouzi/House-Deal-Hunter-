# Deploying to Railway

Step-by-step for this project. Assumes you've pushed to GitHub already.

---

## Architecture on Railway

You need **four services** in one Railway project:

| Service | What it is | Source |
|---|---|---|
| `web` | Django + gunicorn (dashboard + API) | Your GitHub repo |
| `worker` | Celery worker (runs crawls, analysis) | Same repo, different start command |
| `beat` | Celery beat (the scheduler) | Same repo, different start command |
| `Postgres` | Database | Railway plugin |
| `Redis` | Celery broker | Railway plugin |

The three code services all deploy from the same repo — they differ only in start command. Railway supports this natively.

---

## 1. Push to GitHub

```bash
unzip auction-intel.zip && cd auction_intel

git init
git branch -M main
git add .
git commit -m "Initial commit: PA auction intelligence pipeline"
git remote add origin https://github.com/YOUR_USERNAME/auction-intel.git
git push -u origin main
```

Before committing, run `git status` and confirm `.env` is **not** listed. `.env.example` is safe — it holds placeholders only.

---

## 2. Generate a SECRET_KEY

Run this locally and keep the output — you'll paste it into Railway in step 4:

```bash
python -c "import secrets; print(secrets.token_urlsafe(50))"
```

Never reuse the development default in production.

---

## 3. Create the project and add databases

1. railway.app → **New Project** → **Deploy from GitHub repo** → pick `auction-intel`
2. In the project canvas: **+ New** → **Database** → **Add PostgreSQL**
3. **+ New** → **Database** → **Add Redis**

Railway provisions both and exposes `DATABASE_URL` and `REDIS_URL` as reference variables.

---

## 4. Set variables on the web service

Click the web service → **Variables** tab → **Raw Editor**, and paste:

```
SECRET_KEY=<paste the key from step 2>
DEBUG=False
DATABASE_URL=${{Postgres.DATABASE_URL}}
REDIS_URL=${{Redis.REDIS_URL}}
CELERY_BROKER_URL=${{Redis.REDIS_URL}}
CRAWLER_USER_AGENT=AuctionIntelBot/1.0 (Pennsylvania Real Estate Research; contact: your@email.com)
CRAWL_DELAY_SECONDS=5
MIN_HISTORICAL_SAMPLE=30
LOW_COMPETITION_MIN_BID_RATIO=0.40
LOW_COMPETITION_SCORE_THRESHOLD=70
MAX_RISK_SCORE=60
LOG_LEVEL=INFO
```

The `${{Postgres.DATABASE_URL}}` syntax is a Railway **reference variable** — it resolves at deploy time and updates automatically if credentials rotate. Don't paste raw connection strings.

Put your real email in `CRAWLER_USER_AGENT`. An honest, reachable contact address is the difference between a polite crawler and an anonymous one, and it's what gets you a heads-up instead of a silent block.

---

## 5. Generate the public domain

Web service → **Settings** → **Networking** → **Generate Domain**.

`settings.py` already trusts `.railway.app` and reads `RAILWAY_PUBLIC_DOMAIN` for both `ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS`, so no extra config is needed.

---

## 6. Add the worker service

**+ New** → **GitHub Repo** → same repo. Then:

- **Settings** → **Start Command**:
  ```
  celery -A auction_intel worker -l info --concurrency 2
  ```
- **Settings** → **Networking**: leave it private (no domain — it's not an HTTP service)
- **Variables**: same block as step 4

---

## 7. Add the beat service

**+ New** → **GitHub Repo** → same repo again. Then:

- **Settings** → **Start Command**:
  ```
  celery -A auction_intel beat -l info --scheduler django_celery_beat.schedulers:DatabaseScheduler
  ```
- No domain
- Same variables

**Run exactly one beat instance.** Two schedulers on the same database will fire every task twice. Keep its replica count at 1 and never scale it.

---

## 8. First run

Migrations and `collectstatic` run automatically via `start.sh` on every web deploy. Once the deploy is green:

```bash
npm i -g @railway/cli
railway login
railway link          # select your project

railway run python manage.py createsuperuser

# Dry run first — shows what the parser finds without writing anything
railway run python manage.py crawl --source=delaware --dry-run

railway run python manage.py crawl --source=delaware
railway run python manage.py analyze
```

Start with the Delco PDF. It's the official county document rather than scraped HTML, so it's the least likely path to break on a first run.

---

## 9. Verify

- Dashboard → `https://your-app.railway.app/`
- API → `https://your-app.railway.app/api/auctions/`
- Admin → `https://your-app.railway.app/admin/`

In the Admin, open **Periodic Tasks** to confirm beat registered the schedule from `celery.py`:

| Task | Cadence |
|---|---|
| `crawl_bid4assets` | every 6 hours |
| `crawl_delaware_county` | daily 06:00 |
| `refresh_active_auctions` | every 30 min |
| `refresh_closing_soon` | every 5 min |
| `run_analysis` | hourly at :15 |

---

## Files that make this work

| File | Purpose |
|---|---|
| `Procfile` | Declares web / worker / beat process types |
| `railway.json` | Build config, health check on `/api/auctions/` |
| `start.sh` | Migrate → collectstatic → gunicorn |
| `runtime.txt`, `.python-version` | Pins Python 3.11 |
| `requirements.txt` | Adds gunicorn, whitenoise, dj-database-url |
| `settings.py` | Reads `DATABASE_URL`/`REDIS_URL`; WhiteNoise; HTTPS hardening when `DEBUG=False` |

---

## Troubleshooting

**`DisallowedHost`** — the generated domain isn't being picked up. Confirm `RAILWAY_PUBLIC_DOMAIN` exists in the web service Variables tab, or add your domain explicitly to `ALLOWED_HOSTS`.

**CSRF failures on admin login** — `DEBUG` must be `False` in production so the secure-cookie block activates, and the domain must be in `CSRF_TRUSTED_ORIGINS` with the `https://` scheme.

**Static files 404** — `collectstatic` failed during deploy. Check the build log; usually a missing `static/` directory, which the repo ships with a `.gitkeep` to prevent.

**Worker can't reach Redis** — `CELERY_BROKER_URL` must be set on the *worker* service, not only on web. Each service has its own variable scope.

**Celery TLS errors** — Railway Redis may use `rediss://`. `settings.py` detects this and sets the SSL cert policy automatically.

**Tasks running twice** — more than one beat instance. Scale beat to exactly 1.

---

## Cost note

Four services plus Postgres and Redis runs above the free tier. If you want to trim: the `beat` service is the cheapest to drop — you'd trigger crawls manually with `railway run python manage.py crawl` instead of on a schedule. Losing beat costs you automation, not data; the crawl and analysis commands work identically either way.

---

## Before the crawler runs against a live site

The polite-crawler behavior is built in — robots.txt checked before every request, 5-second delay, Cloudflare detection that stops rather than retries. Two things are still on you:

1. Put a **real contact address** in `CRAWLER_USER_AGENT`
2. Read the terms of service for every source you crawl, and disable an adapter if its terms prohibit automated access

The Delaware County PDF path stays available regardless of what happens with Bid4Assets.
