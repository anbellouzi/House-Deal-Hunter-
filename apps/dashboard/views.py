"""Django dashboard views — server-rendered overview of auction intelligence."""
from datetime import timedelta

from django.conf import settings
from django.db.models import OuterRef, Q, Subquery
from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from apps.auctions.models import (
    Alert, Auction, AuctionStatus, PropertyFinancial,
)

CFG = settings.ANALYSIS


def _with_scores(qs):
    """Annotate a queryset with the latest financial scores."""
    latest = PropertyFinancial.objects.filter(
        auction=OuterRef("pk")).order_by("-calculated_at")
    return qs.annotate(
        deal_score=Subquery(latest.values("deal_score")[:1]),
        low_comp=Subquery(latest.values("low_competition_score")[:1]),
        risk=Subquery(latest.values("risk_score")[:1]),
        est_value=Subquery(latest.values("estimated_market_value")[:1]),
        est_rent=Subquery(latest.values("rent_base")[:1]),
        max_bid=Subquery(latest.values("max_bid_recommended")[:1]),
    )


def dashboard_home(request):
    live = Auction.objects.filter(
        auction_status__in=[AuctionStatus.ACTIVE, AuctionStatus.UPCOMING]
    ).select_related("property")

    scored = _with_scores(live)

    top_deals = scored.filter(deal_score__isnull=False).order_by("-deal_score")[:15]

    low_comp = scored.filter(
        low_comp__gte=CFG["LOW_COMPETITION_SCORE_THRESHOLD"]
    ).order_by("-low_comp")[:15]

    closing_soon = _with_scores(
        live.filter(auction_close_time__gte=timezone.now(),
                    auction_close_time__lte=timezone.now() + timedelta(hours=72))
    ).order_by("auction_close_time")[:15]

    one_bidder = _with_scores(
        live.filter(Q(bidder_count__lte=1) | Q(bid_count__lte=1))
    ).order_by("auction_close_time")[:15]

    # Minimum-bid opportunities — strict spec filter
    candidates = scored.filter(
        low_comp__gte=CFG["LOW_COMPETITION_SCORE_THRESHOLD"],
        risk__lte=CFG["MAX_RISK_SCORE"],
        est_value__isnull=False,
        minimum_bid__isnull=False,
    )
    min_bid_ops = [
        a for a in candidates
        if a.est_value and float(a.minimum_bid / a.est_value) <= CFG["LOW_COMPETITION_MIN_BID_RATIO"]
    ]
    min_bid_ops.sort(key=lambda a: float(a.minimum_bid / a.est_value))

    new_auctions = _with_scores(
        Auction.objects.filter(created_at__gte=timezone.now() - timedelta(days=7))
    ).order_by("-created_at")[:15]

    withdrawn = Auction.objects.filter(
        auction_status__in=[AuctionStatus.WITHDRAWN, AuctionStatus.CANCELLED]
    ).select_related("property").order_by("-updated_at")[:15]

    context = {
        "top_deals":     top_deals,
        "low_comp":      low_comp,
        "closing_soon":  closing_soon,
        "one_bidder":    one_bidder,
        "min_bid_ops":   min_bid_ops[:15],
        "new_auctions":  new_auctions,
        "withdrawn":     withdrawn,
        "alerts":        Alert.objects.filter(is_read=False)[:20],
        "stats": {
            "total_auctions": Auction.objects.count(),
            "active":         live.count(),
            "alerts_unread":  Alert.objects.filter(is_read=False).count(),
            "min_bid_ops":    len(min_bid_ops),
        },
    }
    return render(request, "dashboard/home.html", context)


def auction_detail(request, pk):
    auction = get_object_or_404(
        Auction.objects.select_related("property", "risk", "source"), pk=pk
    )
    return render(request, "dashboard/detail.html", {
        "auction":   auction,
        "financial": auction.financials.first(),
        "events":    auction.events.all()[:100],
        "bids":      auction.bid_observations.all()[:100],
        "alerts":    auction.alerts.all(),
        "comps":     auction.property.comps.all()[:10] if auction.property else [],
    })
