# Deploying From a Phone

No terminal, no laptop. Everything below works in a mobile browser.

The project has been adjusted so nothing requires shell access:

- Migrations, static files, and **admin user creation** all run automatically on deploy
- Crawls and analysis can be triggered from buttons in the Django admin
- The scheduler keeps everything current after that

---

## Part 1 — Get the code onto GitHub

The problem: GitHub's mobile site can upload files, but it can't unzip. With 76 files across nested folders, uploading by hand isn't realistic.

**Use GitHub Codespaces instead** — a full browser IDE with a terminal, free tier included, and it works on a phone.

### Steps

1. **Create the repo.** In your mobile browser go to `github.com/new`. Name it `auction-intel`. Leave everything else default — don't add a README or .gitignore, the project has both. Tap **Create repository**.

2. **Open a Codespace.** On the empty repo page, tap the **Code** button → **Codespaces** tab → **Create codespace on main**. Give it a minute to build.

3. **Upload the zip.** In the Codespace, find the file explorer (left panel — tap the hamburger menu if it's collapsed). Long-press in the empty area below the file list → **Upload...** → pick `auction-intel.zip` from your phone.

4. **Unzip and push.** Open the terminal panel (hamburger menu → **Terminal** → **New Terminal**) and paste:

```bash
unzip auction-intel.zip && mv auction_intel/* auction_intel/.[!.]* . 2>/dev/null; rm -rf auction_intel auction-intel.zip
git add . && git commit -m "Initial commit: PA auction intelligence pipeline" && git push
```

That's the only terminal work in the entire process.

**Tip for typing on a phone:** rotate to landscape before using the terminal, and paste rather than type. The Codespaces terminal supports long-press → Paste.

---

## Part 2 — Deploy on Railway

Railway's dashboard is fully usable on mobile. Landscape helps.

### 1. Create the project

`railway.app` → **New Project** → **Deploy from GitHub repo** → authorize GitHub → select `auction-intel`.

The first deploy will fail. That's expected — there's no database yet.

### 2. Add the databases

On the project canvas: **+ New** → **Database** → **Add PostgreSQL**. Then **+ New** → **Database** → **Add Redis**.

### 3. Generate a SECRET_KEY

You need a long random string and can't run Python. Any of these works:

- A password manager's generator, set to 50+ characters
- `random.org/strings` — set length 32, generate 2, paste them together
- Your phone's built-in strong-password suggestion

It only needs to be long, random, and secret.

### 4. Set the variables

Tap the **web service** (the one from your GitHub repo) → **Variables** → **Raw Editor**. Paste this, replacing the two placeholder values:

```
SECRET_KEY=paste-your-long-random-string-here
DEBUG=False
DATABASE_URL=${{Postgres.DATABASE_URL}}
REDIS_URL=${{Redis.REDIS_URL}}
CELERY_BROKER_URL=${{Redis.REDIS_URL}}
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

`ADMIN_PASSWORD` is what replaces `createsuperuser` — the app creates your admin account automatically on deploy. It's rejected if under 12 characters. Put a real address in `CRAWLER_USER_AGENT`; it's how a site owner reaches you instead of silently blocking you.

The `${{Postgres.DATABASE_URL}}` syntax is a Railway reference — it resolves at deploy time. Don't paste raw connection strings.

### 5. Generate the domain

Web service → **Settings** → **Networking** → **Generate Domain**. Copy the URL.

### 6. Add the worker

**+ New** → **GitHub Repo** → same repo. Then:

- **Settings** → **Start Command**:
  ```
  celery -A auction_intel worker -l info --concurrency 2
  ```
- **Variables** → paste the exact same block from step 4
- Don't generate a domain — it isn't a web service

Without this service, no crawls run at all.

### 7. Add beat

**+ New** → **GitHub Repo** → same repo once more:

- **Settings** → **Start Command**:
  ```
  celery -A auction_intel beat -l info --scheduler django_celery_beat.schedulers:DatabaseScheduler
  ```
- Same variables
- No domain

**Keep beat at exactly 1 replica.** Two schedulers fire every task twice.

---

## Part 3 — First run, all from your phone

1. Open `https://your-app.railway.app/admin/`
2. Log in with the `ADMIN_USERNAME` / `ADMIN_PASSWORD` you set
3. Tap **Auction sources**
4. Tick any row's checkbox
5. From the **Action** dropdown pick **▶ Crawl Delaware County (official PDF)** → **Go**
6. Wait a minute, then tap **Auctions** to see what came in
7. Back on Auction sources, run **▶ Run analysis and scoring**
8. Open `https://your-app.railway.app/` for the dashboard

Start with the Delaware County PDF. It's the official county document rather than scraped HTML, so it's the most reliable first run — and it's fast.

After this, the scheduler handles everything: Delco daily at 6am, Bid4Assets every 6 hours, bid refreshes every 30 minutes, and 5-minute polling on auctions closing soon.

---

## Using it day to day

Everything is a normal web page — bookmark these:

| URL | What |
|---|---|
| `/` | Dashboard: top deals, low competition, min-bid opportunities |
| `/admin/` | Trigger crawls, browse records, mark alerts read |
| `/api/auctions/` | Browsable API with filters |

The dashboard tables scroll horizontally on a phone. Landscape is easier for the wide ones.

Useful filtered links to save:

```
/api/auctions/minimum-bid-opportunities/
/api/auctions/one-bidder/
/api/auctions/closing-soon/?hours=48
/api/auctions/?county=DELAWARE&minimum_bid_max=120000
```

---

## If something breaks

You can read logs from your phone: Railway → tap the service → **Deployments** → tap the latest → **View Logs**.

| Symptom | Cause |
|---|---|
| Deploy fails, `DATABASE_URL` errors | Postgres not added, or the variable isn't referenced |
| Can't log into admin | `ADMIN_PASSWORD` unset or under 12 chars — check web service logs for the skip message |
| Crawl action does nothing | Worker service missing, or `CELERY_BROKER_URL` not set **on the worker** — variables are per-service |
| Everything runs twice | More than one beat replica |
| CSRF error on admin login | `DEBUG` must be `False` in production |

---

## Cost

Three code services plus Postgres and Redis exceeds Railway's free tier.

To cut it down: **drop the beat service.** You'd lose scheduling but keep everything else — trigger crawls yourself from the admin buttons whenever you want fresh data. Given sheriff sale lists update roughly monthly, manual triggering is honestly reasonable, and it takes one service off the bill.
