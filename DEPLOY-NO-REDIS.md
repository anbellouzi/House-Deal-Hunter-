# Deploying Without Redis

Railway's free tier allows one volume per project, and Postgres uses it.
This configuration removes the Redis dependency entirely.

**One web service + Postgres. That's the whole deployment.**

---

## What changes

| | With Redis | Without Redis (this setup) |
|---|---|---|
| Services | web + worker + beat | web only |
| Databases | Postgres + Redis | Postgres |
| Crawls | Queued to a worker | Run inline from admin buttons |
| Scheduling | Automatic (beat) | Manual — you tap a button |
| Volumes used | 2 | 1 ✓ |

Nothing is lost from the data model, the analysis engine, the API, or the
dashboard. The only thing you give up is automatic scheduling.

For sheriff sale lists that publish monthly, tapping a button when a new
list drops is a reasonable workflow — not a downgrade.

---

## Railway setup

### 1. Delete the failed Redis service

On the project canvas, tap the Redis card → Settings → Delete. Confirm
Postgres remains.

### 2. Variables on the web service

Web service → **Variables** → **Raw Editor**:

```
SECRET_KEY=paste-a-long-random-string-here
DEBUG=False
USE_CELERY=False
DATABASE_URL=${{Postgres.DATABASE_URL}}
ADMIN_USERNAME=admin
ADMIN_EMAIL=you@example.com
ADMIN_PASSWORD=pick-a-strong-password-12-chars-minimum
CRAWLER_USER_AGENT=AuctionIntelBot/1.0 (Pennsylvania Real Estate Research; contact: you@example.com)
CRAWL_DELAY_SECONDS=5
MIN_HISTORICAL_SAMPLE=30
LOW_COMPETITION_MIN_BID_RATIO=0.40
LOW_COMPETITION_SCORE_THRESHOLD=70
MAX_RISK_SCORE=60
LOG_LEVEL=INFO
```

`USE_CELERY=False` is the switch. No `REDIS_URL`, no `CELERY_BROKER_URL`.

### 3. Generate a domain

Settings → Networking → Generate Domain.

### 4. Redeploy

It should go green. Migrations, static files, and your admin account are
all created automatically by `start.sh`.

---

## Running a crawl

1. Open `https://your-app.railway.app/admin/`
2. Log in with `ADMIN_USERNAME` / `ADMIN_PASSWORD`
3. Tap **Auction sources**
4. Tick any checkbox
5. Action dropdown → **▶ Crawl Delaware County (official PDF)** → **Go**

The page holds for a few seconds, then reports what it found. Tap
**Auctions** to see the imported records.

Then run **▶ Run analysis and scoring** the same way, and open `/` for
the dashboard.

---

## Why Bid4Assets is refused inline

The **▶ Crawl Bid4Assets** action is deliberately blocked in this mode.

That crawler enforces a 5-second delay between requests — the polite
behavior that keeps it from hammering a public site. Across dozens of
auction pages that runs for minutes, far longer than an HTTP request
should live. Running it inline would hit a gateway timeout partway
through, leaving a half-finished crawl.

Rather than fail unpredictably, the action refuses and tells you so.

**Delaware County is unaffected** — it's a single PDF download and parse,
and it finishes in seconds. It's also the better source: the official
county document rather than scraped HTML, including debt amounts and
hand money directly.

To run Bid4Assets, either add a broker later (below) or run it from a
Codespace terminal:

```bash
python manage.py crawl --source=bid4assets
```

---

## Adding background execution later

If you outgrow this, nothing needs rewriting:

1. Create a free Redis at `upstash.com`, copy the `rediss://` URL
2. Set on the web service: `USE_CELERY=True` and
   `CELERY_BROKER_URL=rediss://...`
3. Add a worker service from the same repo with start command
   `celery -A auction_intel worker -l info --concurrency 2`
4. Optionally add beat for scheduling — exactly one replica

The same admin buttons then queue jobs instead of running them inline.
The `dispatch()` layer in `apps/sources/runner.py` handles the switch,
and it falls back to inline automatically if the broker is unreachable.

---

## Troubleshooting

| Symptom | Cause |
|---|---|
| `ModuleNotFoundError: django_celery_beat` | `USE_CELERY` is set to `True` without a broker — set it to `False` |
| Crawl action returns "too slow to run inline" | Expected for Bid4Assets. Use the Delaware County action instead |
| Admin login fails | `ADMIN_PASSWORD` unset or under 12 characters — check the deploy logs |
| Deploy fails on `DATABASE_URL` | Postgres card missing, or the `${{Postgres.DATABASE_URL}}` reference is mistyped |
| CSRF error on login | `DEBUG` must be `False` in production |

Logs: Railway → tap the service → Deployments → tap the latest → View Logs.
