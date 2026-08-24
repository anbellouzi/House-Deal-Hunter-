"""
Scheduled Celery tasks.

Cadence recommendation (set in Django admin via django_celery_beat):
  crawl_bid4assets        — every 6 hours
  crawl_delaware_county   — daily at 06:00
  refresh_active_auctions — every 30 minutes
  refresh_closing_soon    — every 5 minutes
  run_analysis            — hourly
  generate_alerts         — after each refresh
"""
import logging
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

# When Celery is disabled we still want these functions importable and
# directly callable. shared_task-decorated functions are callable anyway,
# but importing celery at module load is unnecessary in inline mode.
if getattr(settings, "USE_CELERY", False):
    from celery import shared_task
else:
    def shared_task(*dargs, **dkwargs):
        """No-op stand-in so the module imports without a broker."""
        def wrap(fn):
            fn.delay = fn          # calling .delay() just runs it inline
            fn.apply_async = fn
            return fn
        # Support both @shared_task and @shared_task(bind=True, ...)
        if len(dargs) == 1 and callable(dargs[0]) and not dkwargs:
            return wrap(dargs[0])
        return wrap


# ─────────────────────────────────────────────────────────────────────────────
# DISCOVERY TASKS
# ─────────────────────────────────────────────────────────────────────────────

@shared_task(bind=True, max_retries=2)
def crawl_bid4assets(self=None):
    """Full discovery pass over all configured Bid4Assets PA county pages."""
    from apps.sources.bid4assets import Bid4AssetsAdapter
    try:
        adapter = Bid4AssetsAdapter()
        saved = adapter.run()
        logger.info(f"crawl_bid4assets complete: {saved} auctions processed")
        return {"source": "Bid4Assets", "saved": saved}
    except Exception as exc:
        logger.exception("crawl_bid4assets failed")
        if self is not None and hasattr(self, "retry"):
            raise self.retry(exc=exc, countdown=300)
        raise


@shared_task(bind=True, max_retries=2)
def crawl_delaware_county(self=None):
    """Parse the official Delaware County sheriff sale PDF."""
    from apps.sources.delaware_county import DelawareCountyAdapter
    try:
        adapter = DelawareCountyAdapter()
        saved = adapter.run()
        logger.info(f"crawl_delaware_county complete: {saved} entries processed")
        return {"source": "Delaware County Sheriff", "saved": saved}
    except Exception as exc:
        logger.exception("crawl_delaware_county failed")
        if self is not None and hasattr(self, "retry"):
            raise self.retry(exc=exc, countdown=300)
        raise


# ─────────────────────────────────────────────────────────────────────────────
# REFRESH TASKS (change detection)
# ─────────────────────────────────────────────────────────────────────────────

@shared_task
def refresh_active_auctions():
    """
    Re-fetch every ACTIVE auction to detect bid changes.
    Every change is written to AuctionEvent — nothing is overwritten silently.
    """
    from apps.auctions.models import Auction, AuctionStatus
    from apps.sources.bid4assets import Bid4AssetsAdapter

    qs = Auction.objects.filter(
        auction_status__in=[AuctionStatus.ACTIVE, AuctionStatus.UPCOMING]
    ).select_related("source")

    adapter = Bid4AssetsAdapter()
    refreshed = 0

    for auction in qs:
        if auction.source.name != adapter.source_name:
            continue
        try:
            raw = adapter.fetch_auction(auction.source_url)
            if not raw:
                continue
            parsed = adapter.parse_auction(raw, auction.source_url)
            normalized = adapter.normalize_auction(parsed)
            adapter.save_auction(normalized)
            refreshed += 1
        except Exception:
            logger.exception(f"Refresh failed for {auction.source_id}")

    logger.info(f"refresh_active_auctions: {refreshed} auctions refreshed")
    generate_alerts.delay()   # inline mode: .delay is the function itself
    return {"refreshed": refreshed}


@shared_task
def refresh_closing_soon():
    """
    High-frequency refresh for auctions closing within 2 hours.
    This is where overtime detection matters most.
    """
    from apps.auctions.models import (
        Auction, AuctionStatus, AuctionEvent, AuctionEventType
    )
    from apps.sources.bid4assets import Bid4AssetsAdapter

    cutoff = timezone.now() + timedelta(hours=2)
    qs = Auction.objects.filter(
        auction_status=AuctionStatus.ACTIVE,
        auction_close_time__lte=cutoff,
        auction_close_time__gte=timezone.now() - timedelta(hours=1),
    ).select_related("source")

    adapter = Bid4AssetsAdapter()
    for auction in qs:
        prev_close = auction.auction_close_time
        try:
            raw = adapter.fetch_auction(auction.source_url)
            if not raw:
                continue
            parsed = adapter.parse_auction(raw, auction.source_url)
            normalized = adapter.normalize_auction(parsed)
            adapter.save_auction(normalized)

            auction.refresh_from_db()
            # Overtime detection: close time pushed later than we last saw
            if (auction.auction_close_time and prev_close
                    and auction.auction_close_time > prev_close):
                AuctionEvent.objects.create(
                    auction=auction,
                    event_type=AuctionEventType.OVERTIME_STARTED,
                    previous_value={"close_time": str(prev_close)},
                    new_value={"close_time": str(auction.auction_close_time)},
                    notes="Close time extended — overtime triggered by a late bid.",
                )
        except Exception:
            logger.exception(f"Closing-soon refresh failed for {auction.source_id}")

    return {"checked": qs.count()}


# ─────────────────────────────────────────────────────────────────────────────
# ANALYSIS TASK
# ─────────────────────────────────────────────────────────────────────────────

@shared_task
def run_analysis(auction_id=None):
    """
    Recalculate financials + scores.
    Deterministic Python only — no AI-generated numbers.
    """
    from decimal import Decimal
    from apps.auctions.models import Auction, AuctionStatus, PropertyFinancial
    from apps.analysis.engine import (
        HistoricalAuctionStats, LowCompetitionScorer,
        MinBidWinProbability, MaxBidCalculator, DealScorer,
    )

    qs = (Auction.objects.filter(pk=auction_id) if auction_id
          else Auction.objects.filter(
              auction_status__in=[AuctionStatus.ACTIVE, AuctionStatus.UPCOMING]))

    stats_engine = HistoricalAuctionStats()
    comp_scorer  = LowCompetitionScorer()
    prob_engine  = MinBidWinProbability()
    bid_calc     = MaxBidCalculator()
    deal_scorer  = DealScorer()

    processed = 0
    for auction in qs.select_related("property"):
        prop = auction.property
        stats = stats_engine.get_stats(
            county=prop.county if prop else None,
            zip_code=prop.zip_code if prop and prop.zip_code else None,
            auction_type=auction.auction_type,
        )

        comp   = comp_scorer.score(auction, stats)
        prob   = prob_engine.estimate(stats, auction.current_bid_to_min_ratio)

        # Only compute max bids where we actually have an ARV on file.
        latest = auction.financials.first()
        arv         = latest.arv_base if latest else None
        repair_base = latest.repair_base if latest else None
        repair_high = latest.repair_high if latest else None
        rent        = latest.rent_base if latest else None
        mkt_value   = latest.estimated_market_value if latest else None

        flip = bid_calc.flip_max_bid(
            arv=arv, repair_base=repair_base, repair_high=repair_high,
            buyer_premium_pct=auction.buyer_premium_pct,
        ) if arv else {}

        flip_profit = None
        if arv and auction.minimum_bid and repair_base:
            flip_profit = (arv - auction.minimum_bid - repair_base
                           - (arv * Decimal("0.06")))

        risk = _risk_score(auction)

        deal = deal_scorer.score(
            minimum_bid=auction.minimum_bid,
            market_value=mkt_value,
            arv=arv,
            monthly_rent=rent,
            repair_base=repair_base,
            low_competition_score=comp["score"],
            flip_profit=flip_profit,
            risk_score=risk,
        )

        version = (latest.version + 1) if latest else 1
        PropertyFinancial.objects.create(
            auction=auction,
            version=version,
            estimated_market_value=mkt_value,
            arv_base=arv,
            rent_base=rent,
            repair_base=repair_base,
            repair_high=repair_high,
            max_bid_aggressive=flip.get("max_bid_aggressive"),
            max_bid_recommended=flip.get("max_bid_recommended"),
            max_bid_absolute=flip.get("max_bid_absolute"),
            expected_flip_profit=flip_profit,
            deal_score=deal["deal_score"],
            low_competition_score=comp["score"],
            risk_score=risk,
            min_bid_win_probability=prob.get("within_10pct"),
        )
        processed += 1

    logger.info(f"run_analysis: {processed} auctions scored")
    return {"processed": processed}


def _risk_score(auction) -> int:
    """Deterministic risk score 0–100. Higher = riskier."""
    score = 30  # baseline auction risk
    risk = getattr(auction, "risk", None)
    if risk:
        if risk.federal_lien_suspected:      score += 25
        if risk.irs_lien_suspected:          score += 20
        if risk.municipal_lien_suspected:    score += 10
        if risk.hoa_lien_suspected:          score += 10
        if risk.title_issues_noted:          score += 15
        if risk.interior_unknown:            score += 10
        if risk.potentially_occupied:        score += 15
        if risk.structural_risk:             score += 15
        if risk.environmental_risk:          score += 10
        if risk.flood_zone:                  score += 10
    if auction.buyer_premium_pct is None:    score += 5   # unknown terms
    return min(100, score)


# ─────────────────────────────────────────────────────────────────────────────
# ALERT TASK
# ─────────────────────────────────────────────────────────────────────────────

@shared_task
def generate_alerts():
    """Create alerts based on current auction state. Idempotent per auction+type."""
    from apps.auctions.models import Auction, AuctionStatus, Alert, AlertType

    created = 0

    def emit(auction, alert_type, message):
        nonlocal created
        _, made = Alert.objects.get_or_create(
            auction=auction, alert_type=alert_type,
            defaults={"message": message},
        )
        if made:
            created += 1

    active = Auction.objects.filter(
        auction_status__in=[AuctionStatus.ACTIVE, AuctionStatus.UPCOMING]
    ).select_related("property").prefetch_related("financials")

    for a in active:
        fin = a.financials.first()

        if a.bidder_count == 1:
            emit(a, AlertType.ONE_BIDDER, "Only one bidder currently registered.")

        if a.bid_count == 0 and a.minimum_bid:
            emit(a, AlertType.BID_AT_MINIMUM,
                 f"No bids yet — still at minimum {a.minimum_bid}.")

        if a.current_bid_to_min_ratio is not None and a.current_bid_to_min_ratio <= 1.0:
            emit(a, AlertType.BID_AT_MINIMUM, "Current bid still at the minimum.")

        if fin and fin.low_competition_score and fin.low_competition_score >= 70:
            emit(a, AlertType.LOW_COMPETITION,
                 f"Low competition score {fin.low_competition_score}/100.")

        if fin and fin.arv_base and a.minimum_bid and fin.arv_base > 0:
            discount = 1 - float(a.minimum_bid / fin.arv_base)
            if discount >= 0.50:
                emit(a, AlertType.HIGH_ARV_DISCOUNT,
                     f"Minimum bid is {discount*100:.0f}% below ARV.")

        if a.auction_close_time:
            hrs = (a.auction_close_time - timezone.now()).total_seconds() / 3600
            if 0 < hrs <= 24:
                emit(a, AlertType.CLOSING_SOON,
                     f"Auction closes in {hrs:.1f} hours.")

        if a.plaintiff and a.reserve_status != "NO_RESERVE":
            emit(a, AlertType.PLAINTIFF_RISK,
                 "Reserve/plaintiff bidding rights may prevent a third-party purchase.")

    for a in Auction.objects.filter(auction_status=AuctionStatus.WITHDRAWN):
        emit(a, AlertType.WITHDRAWN, "Auction withdrawn.")
    for a in Auction.objects.filter(auction_status=AuctionStatus.CANCELLED):
        emit(a, AlertType.CANCELLED, "Auction cancelled.")

    logger.info(f"generate_alerts: {created} new alerts")
    return {"created": created}
