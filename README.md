# Auction Intelligence Platform

Automated discovery and analysis of Pennsylvania sheriff sale and foreclosure auctions, built to find properties where **low purchase price + low competition + strong economics** intersect.

---

## 1. Data sources — what's actually available

Answering the discovery question directly, since it determines the architecture:

### Bid4Assets — no public API

Bid4Assets has **no official public API, data feed, or structured export** as of 2026. They run PA sheriff sales for Delaware, Montgomery, Philadelphia, and other counties, but county pages are HTML only.

What *is* publicly accessible without authentication:

| Source | URL pattern | Contains |
|---|---|---|
| County landing pages | `bid4assets.com/{county-slug}` | Links to active auctions |
| Auction detail pages | `bid4assets.com/auctions/detail/{id}` | Address, min bid, current bid, close time, plaintiff, terms |
| PA sheriff hub | `bid4assets.com/pages/public/content/pa-sheriff-sales` | County list |

What is **not** available without an account:
- Individual bidder identities
- Complete historical bid timestamps
- Full bidder counts on some auctions

The adapter records `bid_count`, `bid_amounts`, and `bid_timestamps` as observed on each poll, which is enough to compute bidding intensity without ever attempting to identify bidders.

### Constraint you should know about

Some Bid4Assets pages render auction cards via JavaScript. The parser handles both server-rendered links and `data-auction-id` attributes, but if a county page returns zero links, it logs a warning suggesting Playwright. **Adding a headless browser is a legitimate rendering choice, not a protection bypass** — but if a page returns a Cloudflare challenge, the client stops immediately and does not retry.

### Delaware County — better source available

Delaware County publishes the official sale list as a **public PDF**: `delcopa.gov/sites/default/files/sheriff/list1.pdf`

This is strictly better than scraping — it's the authoritative government document, includes debt amounts and hand money, and needs no HTML parsing. `DelawareCountyAdapter` parses it with pdfplumber and derives minimum bid as debt × 2/3 per PA law.

**Recommended: use the PDF for Delco, Bid4Assets only for live bid state.**

### Crawler safety guarantees

Built into `apps/sources/base.py`, not optional:

- `robots.txt` fetched and checked before **every** request, cached 1 hour
- 5-second crawl delay per domain (configurable)
- Honest self-identifying User-Agent with contact address
- Exponential backoff on errors; honors `Retry-After` on 429
- **Detects Cloudflare/bot challenges and stops** — never attempts a bypass
- No CAPTCHA solving, no auth circumvention, no rotating proxies

If Bid4Assets blocks this crawler or updates their ToS to prohibit automated access, disable the adapter. The Delco PDF path remains available regardless.

---

## 2. Project structure

```
auction_intel/
├── manage.py
├── requirements.txt
├── pytest.ini
├── .env.example
├── auction_intel/
│   ├── settings.py          # config, crawler policy, analysis weights
│   ├── celery.py            # beat schedule
│   ├── urls.py
│   └── wsgi.py
├── apps/
│   ├── auctions/
│   │   ├── models.py        # Auction, Property, AuctionEvent, Bid, Financial, Risk, Comps
│   │   ├── api.py           # serializers, filters, viewsets
│   │   ├── admin.py
│   │   └── tests.py
│   ├── sources/
│   │   ├── base.py          # AuctionSourceAdapter ABC, HttpClient, robots, rate limiter
│   │   ├── bid4assets.py    # Bid4AssetsAdapter
│   │   ├── delaware_county.py  # DelawareCountyAdapter (PDF)
│   │   ├── tasks.py         # Celery tasks
│   │   └── management/commands/{crawl,analyze}.py
│   ├── analysis/
│   │   └── engine.py        # deterministic calculators + scorers
│   └── dashboard/
│       └── views.py
├── templates/dashboard/{home,_table,detail}.html
└── static/
```

Every source implements the five required methods:

```python
class AuctionSourceAdapter(ABC):
    def discover_auctions(self) -> list[dict]
    def fetch_auction(self, url) -> str | None
    def parse_auction(self, raw, url) -> dict
    def normalize_auction(self, parsed) -> dict
    def save_auction(self, normalized) -> Auction
```

Adding Chester or Montgomery County means writing one new subclass — nothing else changes.

---

## 3. Core design decision: facts vs. interpretation

This is the separation you asked for, enforced structurally:

| Layer | Responsibility | Never does |
|---|---|---|
| **Crawler** (`apps/sources/`) | Collects observable facts. Missing field → `"UNKNOWN — VERIFY"` | Estimate, infer, or fill gaps |
| **Analysis** (`apps/analysis/engine.py`) | Deterministic arithmetic on stored facts | Invent inputs it doesn't have |
| **Claude / LLM** | Interprets risk, reads terms, writes the thesis | Generate numbers |

Three places this shows up concretely:

**Insufficient data is returned, not papered over.** `HistoricalAuctionStats` returns `INSUFFICIENT_DATA` with the actual sample size when fewer than `MIN_HISTORICAL_SAMPLE` (default 30) comparable auctions exist. It does not emit a ratio computed from four data points.

**Win probability can be `None`.** `MinBidWinProbability` returns `None` for every field when history is thin. Every output is labeled `MODEL ESTIMATE — NOT GUARANTEED`.

**Missing inputs score zero, not average.** In `DealScorer`, an unknown ARV contributes 0 to the flip component — it doesn't quietly get 50 and inflate the grade.

---

## 4. Running it locally

### Prerequisites
PostgreSQL 14+, Redis 6+, Python 3.11+

### Setup

```bash
git clone <your-repo> auction_intel && cd auction_intel

python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env              # then edit
createdb auction_intel

python manage.py makemigrations auctions
python manage.py migrate
python manage.py createsuperuser
```

### First crawl

```bash
# See what would be discovered without writing anything
python manage.py crawl --source=delaware --dry-run

# Delco PDF first — authoritative and reliable
python manage.py crawl --source=delaware

# Then Bid4Assets for live bid state
python manage.py crawl --source=bid4assets

# Score everything
python manage.py analyze
```

### Run the app

```bash
# Terminal 1
python manage.py runserver

# Terminal 2
celery -A auction_intel worker -l info

# Terminal 3
celery -A auction_intel beat -l info --scheduler django_celery_beat.schedulers:DatabaseScheduler
```

Dashboard: `http://localhost:8000/`
API: `http://localhost:8000/api/auctions/`
Admin: `http://localhost:8000/admin/`

### Tests

```bash
pytest                                    # all
pytest apps/auctions/tests.py -v          # verbose
pytest -k "test_insufficient_data"        # the never-fabricate guarantees
pytest --cov=apps --cov-report=term       # coverage
```

---

## 5. API

```
GET /api/auctions/
GET /api/auctions/{id}/                       full detail + events + bids + comps
GET /api/auctions/{id}/history/               complete bidding history
GET /api/auctions/top-deals/
GET /api/auctions/low-competition/
GET /api/auctions/closing-soon/?hours=48
GET /api/auctions/one-bidder/
GET /api/auctions/minimum-bid-opportunities/
GET /api/auctions/new/?days=7
GET /api/auctions/withdrawn-cancelled/
GET /api/alerts/
```

Filters on the list endpoint:

```
?county=DELAWARE
?city=Drexel Hill
?zip_code=19026
?minimum_bid_min=50000&minimum_bid_max=150000
?current_bid_min=&current_bid_max=
?auction_date_after=2026-09-01&auction_date_before=2026-12-31
?auction_status=ACTIVE
?auction_type=SHERIFF_SALE
?bid_count_max=1
?bidder_count_max=2
?deal_score_min=70
?low_competition_score_min=70
?search=Garrett
?ordering=-minimum_bid
```

Example:

```bash
curl "http://localhost:8000/api/auctions/?county=DELAWARE&minimum_bid_max=120000&bid_count_max=1"
```

`minimum-bid-opportunities` applies the strict spec filter: min bid ≤ 40% of estimated value **AND** low competition score ≥ 70 **AND** risk score ≤ 60.

---

## 6. Change detection

Nothing is ever silently overwritten. Every observed change writes an immutable `AuctionEvent`:

```
DISCOVERED · BID_PLACED · BID_COUNT_CHANGED · MIN_BID_CHANGED
DATE_CHANGED · STATUS_CHANGED · OVERTIME_STARTED
WITHDRAWN · CANCELLED · CLOSED
PLAINTIFF_WIN · THIRD_PARTY_WIN · NO_SALE
```

`AuctionEventAdmin` disables add and delete permissions — the log is append-only at the admin layer too. Full history: `GET /api/auctions/{id}/history/`.

### Overtime handling

`refresh_closing_soon` polls every 5 minutes for auctions closing within 2 hours. If `auction_close_time` moves later than previously observed, it logs `OVERTIME_STARTED`.

This matters for the trap you flagged: **one bidder shortly before scheduled close does not mean the auction is won.** A late bid can extend it. The detail page shows the overtime window and the dashboard flags it.

---

## 7. Scoring

### Low Competition Score (0–100)

| Weight | Component |
|---|---|
| 25% | Historical bidder count for comparable auctions |
| 20% | Historical final/minimum bid ratio |
| 15% | % historically sold within 10% of minimum |
| 10% | Current bidder count |
| 10% | Current bid / minimum ratio |
| 10% | Property attractiveness |
| 5% | Neighborhood investor demand |
| 5% | Auction timing |

Comparable auctions are selected most-specific-first: ZIP → county → property type → min bid range. Below 30 observations, confidence drops to `LOW` and historical components fall back to neutral 50 rather than a fabricated figure.

### Deal Score (0–100) and grades

25% discount to market · 20% rental economics · 15% low competition · 15% flip economics · 10% property quality · 5% neighborhood · 5% resale · 5% risk adjustment (subtractive)

```
90+  A+  🔥 Exceptional      60-69  C  🟡 Investigate
80-89 A   🟢 Strong          50-59  D  🟠 High risk
70-79 B   🟢 Good             <50   F  🔴 Avoid
```

### Max bids

Three tiers from `MaxBidCalculator`:

- **Aggressive** — base repair estimate, half the target profit
- **Recommended** — base repair estimate, full target profit ← stop here
- **Absolute** — high repair estimate, hard ceiling, never exceed

Flip: `ARV − repairs − overhead − holding − selling costs − desired profit`
Rental: derived from NOI at your target cap rate

---

## 8. Cost model

`AcquisitionCostCalculator` computes total project cost, with PA-specific defaults:

```
Winning bid
+ Buyer's premium        (per-auction — never assumed uniform across counties)
+ Transfer tax           (3% PA default: 1% state + local)
+ Title/legal            ($3,000 — sheriff sale title work)
+ Recording              ($500)
+ Repairs + contingency  (15% on top of base estimate)
+ Holding costs          (months × monthly)
= TOTAL PROJECT COST
```

Buyer's premium is read per auction from that auction's terms. If it can't be found, the field is `None` and the result carries `buyer_premium_note: "UNKNOWN — VERIFY auction terms"` rather than defaulting to a number that would silently understate your cost.

---

## 9. Alerts

```
🔥 NEW_LOW_BID · ONE_BIDDER · BID_AT_MINIMUM · LOW_COMPETITION
🔥 HIGH_ARV_DISCOUNT · STRONG_RENTAL
⚠️ OVERTIME_STARTED · PLAINTIFF_RISK · WITHDRAWN · CANCELLED · CLOSING_SOON
📢 NEW_AUCTION · PRICE_CHANGE
```

Generated after every refresh, idempotent per `(auction, alert_type)`.

---

## 10. Adding a county

```python
# apps/sources/chester_county.py
from .base import AuctionSourceAdapter

class ChesterCountyAdapter(AuctionSourceAdapter):
    source_name = "Chester County Sheriff"
    base_url = "https://www.chesco.org"

    def discover_auctions(self): ...
    def fetch_auction(self, url): ...
    def parse_auction(self, raw, url): ...
    def normalize_auction(self, parsed): ...
```

Register it in `crawl.py` and add a Celery task. Nothing else changes.

---

## 11. Before you bid — what the system can't tell you

The scores narrow the field; they don't replace diligence. Verify independently:

- [ ] **Title search** — federal and IRS liens can survive a sheriff sale
- [ ] **All liens** — municipal, HOA, second mortgages
- [ ] **Occupancy** — an occupied property means eviction time and cost
- [ ] **Exact buyer's premium and deposit** — read that auction's terms, not a default
- [ ] **Payment deadline** — Delco is 10 days; missing it forfeits your deposit
- [ ] **Whether the plaintiff can still take the property** — a credit bid can beat you
- [ ] **Exterior condition** — drive it; interiors are almost never accessible
- [ ] **Overtime rules** — a late bid extends the clock

Every score in this system is a **model estimate, not a guarantee**. The dashboard says so on every detail page, deliberately.

---

## License

Personal research use. Comply with the terms of service of every source you crawl.
