"""
REST API — serializers, filters, viewsets.

Endpoints:
  GET /api/auctions/           list + filter
  GET /api/auctions/{id}/      full detail (auction + property + financial + risk + events)
  GET /api/auctions/top-deals/
  GET /api/auctions/low-competition/
  GET /api/auctions/closing-soon/
  GET /api/auctions/one-bidder/
  GET /api/auctions/minimum-bid-opportunities/
  GET /api/alerts/
"""
from datetime import timedelta

import django_filters as df
from django.conf import settings
from django.db.models import F, FloatField, OuterRef, Q, Subquery
from django.utils import timezone
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import (
    Alert, Auction, AuctionEvent, AuctionStatus, BidObservation,
    ComparableSale, Property, PropertyFinancial, PropertyRisk,
    RentalComparable,
)

CFG = settings.ANALYSIS


# ─────────────────────────────────────────────────────────────────────────────
# SERIALIZERS
# ─────────────────────────────────────────────────────────────────────────────

class PropertySerializer(serializers.ModelSerializer):
    full_address = serializers.ReadOnlyField()

    class Meta:
        model = Property
        fields = "__all__"


class PropertyFinancialSerializer(serializers.ModelSerializer):
    class Meta:
        model = PropertyFinancial
        fields = "__all__"


class PropertyRiskSerializer(serializers.ModelSerializer):
    class Meta:
        model = PropertyRisk
        fields = "__all__"


class AuctionEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = AuctionEvent
        fields = ["id", "event_type", "occurred_at", "previous_value",
                  "new_value", "notes"]


class BidObservationSerializer(serializers.ModelSerializer):
    class Meta:
        model = BidObservation
        fields = ["id", "observed_at", "bid_amount", "bid_count_snapshot"]


class ComparableSaleSerializer(serializers.ModelSerializer):
    class Meta:
        model = ComparableSale
        fields = "__all__"


class RentalComparableSerializer(serializers.ModelSerializer):
    class Meta:
        model = RentalComparable
        fields = "__all__"


class AlertSerializer(serializers.ModelSerializer):
    auction_source_id = serializers.CharField(source="auction.source_id", read_only=True)
    address = serializers.CharField(source="auction.property.address",
                                    read_only=True, default="")

    class Meta:
        model = Alert
        fields = ["id", "alert_type", "message", "is_read", "created_at",
                  "auction", "auction_source_id", "address"]


class AuctionListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for list views."""
    address    = serializers.CharField(source="property.address", read_only=True, default="")
    city       = serializers.CharField(source="property.city", read_only=True, default="")
    zip_code   = serializers.CharField(source="property.zip_code", read_only=True, default="")
    county     = serializers.CharField(source="property.county", read_only=True, default="")

    deal_score            = serializers.SerializerMethodField()
    low_competition_score = serializers.SerializerMethodField()
    risk_score            = serializers.SerializerMethodField()
    estimated_value       = serializers.SerializerMethodField()
    estimated_rent        = serializers.SerializerMethodField()
    max_bid_recommended   = serializers.SerializerMethodField()
    current_bid_ratio     = serializers.ReadOnlyField(source="current_bid_to_min_ratio")

    class Meta:
        model  = Auction
        fields = [
            "id", "source_id", "source_url", "auction_type", "auction_status",
            "auction_date", "auction_close_time",
            "address", "city", "zip_code", "county",
            "minimum_bid", "current_bid", "final_bid", "bid_count",
            "bidder_count", "current_bid_ratio",
            "deposit_requirement", "buyer_premium_pct",
            "plaintiff", "defendant",
            "deal_score", "low_competition_score", "risk_score",
            "estimated_value", "estimated_rent", "max_bid_recommended",
        ]

    def _fin(self, obj):
        return obj.financials.first()

    def get_deal_score(self, obj):
        f = self._fin(obj); return f.deal_score if f else None

    def get_low_competition_score(self, obj):
        f = self._fin(obj); return f.low_competition_score if f else None

    def get_risk_score(self, obj):
        f = self._fin(obj); return f.risk_score if f else None

    def get_estimated_value(self, obj):
        f = self._fin(obj); return f.estimated_market_value if f else None

    def get_estimated_rent(self, obj):
        f = self._fin(obj); return f.rent_base if f else None

    def get_max_bid_recommended(self, obj):
        f = self._fin(obj); return f.max_bid_recommended if f else None


class AuctionDetailSerializer(AuctionListSerializer):
    """Full detail — auction + property + financials + risk + history."""
    property_detail = PropertySerializer(source="property", read_only=True)
    financials      = PropertyFinancialSerializer(many=True, read_only=True)
    risk            = PropertyRiskSerializer(read_only=True)
    events          = AuctionEventSerializer(many=True, read_only=True)
    bid_observations= BidObservationSerializer(many=True, read_only=True)
    comps           = serializers.SerializerMethodField()
    rental_comps    = serializers.SerializerMethodField()
    alerts          = AlertSerializer(many=True, read_only=True)

    class Meta(AuctionListSerializer.Meta):
        fields = AuctionListSerializer.Meta.fields + [
            "property_detail", "financials", "risk", "events",
            "bid_observations", "comps", "rental_comps", "alerts",
            "reserve_status", "overtime_minutes", "payment_deadline_days",
            "sold_to_plaintiff", "winning_bidder_type", "raw_terms",
            "last_checked_at", "check_count", "created_at", "updated_at",
        ]

    def get_comps(self, obj):
        if not obj.property:
            return []
        return ComparableSaleSerializer(obj.property.comps.all()[:10], many=True).data

    def get_rental_comps(self, obj):
        if not obj.property:
            return []
        return RentalComparableSerializer(obj.property.rental_comps.all()[:10], many=True).data


# ─────────────────────────────────────────────────────────────────────────────
# FILTERS
# ─────────────────────────────────────────────────────────────────────────────

class AuctionFilter(df.FilterSet):
    county   = df.CharFilter(field_name="property__county", lookup_expr="iexact")
    city     = df.CharFilter(field_name="property__city", lookup_expr="icontains")
    zip_code = df.CharFilter(field_name="property__zip_code", lookup_expr="exact")

    minimum_bid_min = df.NumberFilter(field_name="minimum_bid", lookup_expr="gte")
    minimum_bid_max = df.NumberFilter(field_name="minimum_bid", lookup_expr="lte")
    current_bid_min = df.NumberFilter(field_name="current_bid", lookup_expr="gte")
    current_bid_max = df.NumberFilter(field_name="current_bid", lookup_expr="lte")

    auction_date_after  = df.DateFilter(field_name="auction_date", lookup_expr="gte")
    auction_date_before = df.DateFilter(field_name="auction_date", lookup_expr="lte")

    bid_count_max    = df.NumberFilter(field_name="bid_count", lookup_expr="lte")
    bidder_count_max = df.NumberFilter(field_name="bidder_count", lookup_expr="lte")

    deal_score_min            = df.NumberFilter(method="filter_deal_score")
    low_competition_score_min = df.NumberFilter(method="filter_low_comp")

    class Meta:
        model  = Auction
        fields = ["auction_status", "auction_type"]

    def filter_deal_score(self, qs, name, value):
        latest = PropertyFinancial.objects.filter(
            auction=OuterRef("pk")).order_by("-calculated_at")
        return qs.annotate(
            _ds=Subquery(latest.values("deal_score")[:1])
        ).filter(_ds__gte=value)

    def filter_low_comp(self, qs, name, value):
        latest = PropertyFinancial.objects.filter(
            auction=OuterRef("pk")).order_by("-calculated_at")
        return qs.annotate(
            _lc=Subquery(latest.values("low_competition_score")[:1])
        ).filter(_lc__gte=value)


# ─────────────────────────────────────────────────────────────────────────────
# VIEWSETS
# ─────────────────────────────────────────────────────────────────────────────

class AuctionViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = (Auction.objects
                .select_related("property", "source", "risk")
                .prefetch_related("financials", "events", "alerts"))
    filterset_class  = AuctionFilter
    search_fields    = ["property__address", "property__city", "source_id",
                        "plaintiff", "defendant"]
    ordering_fields  = ["auction_date", "minimum_bid", "current_bid", "bid_count"]
    ordering         = ["auction_date"]

    def get_serializer_class(self):
        return AuctionDetailSerializer if self.action == "retrieve" else AuctionListSerializer

    # ── Curated dashboard feeds ──────────────────────────────────────────────

    @action(detail=False, url_path="top-deals")
    def top_deals(self, request):
        latest = PropertyFinancial.objects.filter(
            auction=OuterRef("pk")).order_by("-calculated_at")
        qs = (self.get_queryset()
              .filter(auction_status__in=[AuctionStatus.ACTIVE, AuctionStatus.UPCOMING])
              .annotate(_ds=Subquery(latest.values("deal_score")[:1]))
              .filter(_ds__isnull=False)
              .order_by("-_ds")[:50])
        return Response(AuctionListSerializer(qs, many=True).data)

    @action(detail=False, url_path="low-competition")
    def low_competition(self, request):
        latest = PropertyFinancial.objects.filter(
            auction=OuterRef("pk")).order_by("-calculated_at")
        qs = (self.get_queryset()
              .filter(auction_status__in=[AuctionStatus.ACTIVE, AuctionStatus.UPCOMING])
              .annotate(_lc=Subquery(latest.values("low_competition_score")[:1]))
              .filter(_lc__gte=CFG["LOW_COMPETITION_SCORE_THRESHOLD"])
              .order_by("-_lc")[:50])
        return Response(AuctionListSerializer(qs, many=True).data)

    @action(detail=False, url_path="closing-soon")
    def closing_soon(self, request):
        hours = int(request.query_params.get("hours", 48))
        qs = (self.get_queryset()
              .filter(auction_status=AuctionStatus.ACTIVE,
                      auction_close_time__gte=timezone.now(),
                      auction_close_time__lte=timezone.now() + timedelta(hours=hours))
              .order_by("auction_close_time"))
        return Response(AuctionListSerializer(qs, many=True).data)

    @action(detail=False, url_path="one-bidder")
    def one_bidder(self, request):
        qs = (self.get_queryset()
              .filter(auction_status__in=[AuctionStatus.ACTIVE, AuctionStatus.UPCOMING])
              .filter(Q(bidder_count__lte=1) | Q(bid_count__lte=1))
              .order_by("auction_close_time"))
        return Response(AuctionListSerializer(qs, many=True).data)

    @action(detail=False, url_path="minimum-bid-opportunities")
    def minimum_bid_opportunities(self, request):
        """
        Strict filter per spec:
          min_bid <= 40% of estimated value
          AND low_competition_score >= 70
          AND risk_score <= 60
        """
        latest = PropertyFinancial.objects.filter(
            auction=OuterRef("pk")).order_by("-calculated_at")
        qs = (self.get_queryset()
              .filter(auction_status__in=[AuctionStatus.ACTIVE, AuctionStatus.UPCOMING])
              .annotate(
                  _lc=Subquery(latest.values("low_competition_score")[:1]),
                  _rs=Subquery(latest.values("risk_score")[:1]),
                  _mv=Subquery(latest.values("estimated_market_value")[:1]),
              )
              .filter(_lc__gte=CFG["LOW_COMPETITION_SCORE_THRESHOLD"],
                      _rs__lte=CFG["MAX_RISK_SCORE"],
                      _mv__isnull=False,
                      minimum_bid__isnull=False))

        ratio_cap = CFG["LOW_COMPETITION_MIN_BID_RATIO"]
        results = [a for a in qs
                   if a._mv and float(a.minimum_bid / a._mv) <= ratio_cap]
        results.sort(key=lambda a: float(a.minimum_bid / a._mv))
        return Response(AuctionListSerializer(results, many=True).data)

    @action(detail=False, url_path="new")
    def new_auctions(self, request):
        days = int(request.query_params.get("days", 7))
        qs = (self.get_queryset()
              .filter(created_at__gte=timezone.now() - timedelta(days=days))
              .order_by("-created_at"))
        return Response(AuctionListSerializer(qs, many=True).data)

    @action(detail=False, url_path="withdrawn-cancelled")
    def withdrawn_cancelled(self, request):
        qs = self.get_queryset().filter(
            auction_status__in=[AuctionStatus.WITHDRAWN, AuctionStatus.CANCELLED]
        ).order_by("-updated_at")
        return Response(AuctionListSerializer(qs, many=True).data)

    @action(detail=True, url_path="history")
    def history(self, request, pk=None):
        auction = self.get_object()
        return Response({
            "auction_id": auction.id,
            "source_id":  auction.source_id,
            "events":     AuctionEventSerializer(auction.events.all(), many=True).data,
            "bids":       BidObservationSerializer(
                              auction.bid_observations.all(), many=True).data,
        })


class AlertViewSet(viewsets.ReadOnlyModelViewSet):
    queryset         = Alert.objects.select_related("auction", "auction__property")
    serializer_class = AlertSerializer
    filterset_fields = ["alert_type", "is_read"]
    ordering         = ["-created_at"]
