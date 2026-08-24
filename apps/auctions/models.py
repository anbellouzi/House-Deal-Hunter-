"""
Core database models for Auction Intelligence Platform.

Design principles:
- NEVER overwrite historical data — append only for events/bids
- Every externally sourced field carries source + confidence + retrieved_at
- All monetary fields use DecimalField for precision
- Nullable means genuinely unknown; do NOT default to 0
"""
from decimal import Decimal
from django.db import models
from django.utils import timezone


# ─────────────────────────────────────────────────────────────────────────────
# ENUMERATIONS
# ─────────────────────────────────────────────────────────────────────────────

class AuctionStatus(models.TextChoices):
    UPCOMING             = "UPCOMING",             "Upcoming"
    ACTIVE               = "ACTIVE",               "Active"
    ENDED_THIRD_PARTY    = "ENDED_THIRD_PARTY",    "Ended — Third Party Won"
    ENDED_PLAINTIFF      = "ENDED_PLAINTIFF",      "Ended — Sold to Plaintiff"
    ENDED_NO_SALE        = "ENDED_NO_SALE",        "Ended — No Sale"
    WITHDRAWN            = "WITHDRAWN",            "Withdrawn"
    CANCELLED            = "CANCELLED",            "Cancelled"
    UNKNOWN              = "UNKNOWN",              "Unknown"


class AuctionType(models.TextChoices):
    SHERIFF_SALE         = "SHERIFF_SALE",         "Sheriff Sale"
    TAX_FORECLOSURE      = "TAX_FORECLOSURE",      "Tax Foreclosure"
    MORTGAGE_FORECLOSURE = "MORTGAGE_FORECLOSURE", "Mortgage Foreclosure"
    FEDERAL_FORFEITURE   = "FEDERAL_FORFEITURE",   "Federal Forfeiture"
    OTHER                = "OTHER",                "Other"


class ReserveStatus(models.TextChoices):
    NO_RESERVE  = "NO_RESERVE",  "No Reserve"
    RESERVE_MET = "RESERVE_MET", "Reserve Met"
    WITH_RESERVE= "WITH_RESERVE","With Reserve (not yet met)"
    UNKNOWN     = "UNKNOWN",     "Unknown"


class PropertyType(models.TextChoices):
    SINGLE_FAMILY = "SINGLE_FAMILY", "Single Family"
    MULTI_FAMILY  = "MULTI_FAMILY",  "Multi Family"
    CONDO         = "CONDO",         "Condo"
    TOWNHOUSE     = "TOWNHOUSE",     "Townhouse"
    COMMERCIAL    = "COMMERCIAL",    "Commercial"
    LAND          = "LAND",          "Land/Lot"
    MIXED_USE     = "MIXED_USE",     "Mixed Use"
    UNKNOWN       = "UNKNOWN",       "Unknown"


class RepairGrade(models.TextChoices):
    A = "A", "A — Move-in ready"
    B = "B", "B — Cosmetic"
    C = "C", "C — Moderate"
    D = "D", "D — Major renovation"
    E = "E", "E — Gut renovation"
    F = "F", "F — Unknown / uninspectable"


class County(models.TextChoices):
    DELAWARE     = "DELAWARE",     "Delaware County"
    MONTGOMERY   = "MONTGOMERY",   "Montgomery County"
    PHILADELPHIA = "PHILADELPHIA", "Philadelphia County"
    CHESTER      = "CHESTER",      "Chester County"
    BUCKS        = "BUCKS",        "Bucks County"
    OTHER_PA     = "OTHER_PA",     "Other PA County"


class DataConfidence(models.TextChoices):
    HIGH     = "HIGH",     "High — verified source"
    MEDIUM   = "MEDIUM",   "Medium — estimated"
    LOW      = "LOW",      "Low — uncertain"
    UNKNOWN  = "UNKNOWN",  "Unknown — verify"


# ─────────────────────────────────────────────────────────────────────────────
# AUCTION SOURCE
# ─────────────────────────────────────────────────────────────────────────────

class AuctionSource(models.Model):
    """Tracks where auction data came from."""
    name         = models.CharField(max_length=100, unique=True)  # e.g. "Bid4Assets"
    base_url     = models.URLField()
    is_active    = models.BooleanField(default=True)
    last_crawled = models.DateTimeField(null=True, blank=True)
    notes        = models.TextField(blank=True)

    def __str__(self):
        return self.name


# ─────────────────────────────────────────────────────────────────────────────
# PROPERTY
# ─────────────────────────────────────────────────────────────────────────────

class Property(models.Model):
    """
    Represents a physical property.
    One property may have multiple auctions over time.
    All externally sourced fields carry provenance metadata.
    """
    # ── Identity ──────────────────────────────────────────────────────────────
    address       = models.CharField(max_length=255)
    city          = models.CharField(max_length=100)
    state         = models.CharField(max_length=2, default="PA")
    zip_code      = models.CharField(max_length=10)
    county        = models.CharField(max_length=30, choices=County.choices, default=County.OTHER_PA)
    parcel_number = models.CharField(max_length=100, blank=True, db_index=True)

    # ── Physical characteristics ──────────────────────────────────────────────
    property_type = models.CharField(
        max_length=20, choices=PropertyType.choices, default=PropertyType.UNKNOWN
    )
    bedrooms      = models.PositiveSmallIntegerField(null=True, blank=True)
    bathrooms     = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True)
    square_feet   = models.PositiveIntegerField(null=True, blank=True)
    lot_size_sqft = models.PositiveIntegerField(null=True, blank=True)
    year_built    = models.PositiveSmallIntegerField(null=True, blank=True)
    stories       = models.PositiveSmallIntegerField(null=True, blank=True)

    # ── Tax / assessment ──────────────────────────────────────────────────────
    assessed_value   = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    annual_taxes     = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    tax_year         = models.PositiveSmallIntegerField(null=True, blank=True)

    # ── Enrichment provenance ─────────────────────────────────────────────────
    enrichment_source     = models.CharField(max_length=200, blank=True)
    enrichment_source_url = models.URLField(blank=True)
    enrichment_retrieved  = models.DateTimeField(null=True, blank=True)
    enrichment_confidence = models.CharField(
        max_length=10, choices=DataConfidence.choices, default=DataConfidence.UNKNOWN
    )

    # ── Timestamps ────────────────────────────────────────────────────────────
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("parcel_number", "county")]
        indexes = [
            models.Index(fields=["zip_code"]),
            models.Index(fields=["county", "city"]),
            models.Index(fields=["parcel_number"]),
        ]

    def __str__(self):
        return f"{self.address}, {self.city}, {self.state} {self.zip_code}"

    @property
    def full_address(self):
        return f"{self.address}, {self.city}, {self.state} {self.zip_code}"


# ─────────────────────────────────────────────────────────────────────────────
# AUCTION
# ─────────────────────────────────────────────────────────────────────────────

class Auction(models.Model):
    """
    One auction event for one property.
    Never overwrite — use AuctionEvent for changes.
    """
    # ── Source ────────────────────────────────────────────────────────────────
    source      = models.ForeignKey(AuctionSource, on_delete=models.PROTECT)
    source_id   = models.CharField(max_length=100, db_index=True)   # Bid4Assets auction ID
    source_url  = models.URLField(max_length=500)

    # ── Property ──────────────────────────────────────────────────────────────
    property    = models.ForeignKey(Property, on_delete=models.PROTECT,
                                    related_name="auctions", null=True, blank=True)

    # ── Auction type & status ──────────────────────────────────────────────────
    auction_type   = models.CharField(max_length=30, choices=AuctionType.choices,
                                       default=AuctionType.SHERIFF_SALE)
    auction_status = models.CharField(max_length=30, choices=AuctionStatus.choices,
                                       default=AuctionStatus.UNKNOWN)

    # ── Dates ─────────────────────────────────────────────────────────────────
    auction_date       = models.DateField(null=True, blank=True)
    auction_close_time = models.DateTimeField(null=True, blank=True)

    # ── Parties ───────────────────────────────────────────────────────────────
    plaintiff  = models.CharField(max_length=500, blank=True)
    defendant  = models.CharField(max_length=500, blank=True)

    # ── Financial ─────────────────────────────────────────────────────────────
    minimum_bid       = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    current_bid       = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    final_bid         = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    bid_increment     = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    bid_count         = models.PositiveIntegerField(default=0)
    bidder_count      = models.PositiveIntegerField(null=True, blank=True)

    # ── Terms ─────────────────────────────────────────────────────────────────
    reserve_status       = models.CharField(max_length=20, choices=ReserveStatus.choices,
                                             default=ReserveStatus.UNKNOWN)
    overtime_minutes     = models.PositiveIntegerField(null=True, blank=True)
    deposit_requirement  = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    buyer_premium_pct    = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    payment_deadline_days= models.PositiveSmallIntegerField(null=True, blank=True)

    # ── Outcome ───────────────────────────────────────────────────────────────
    sold_to_plaintiff   = models.BooleanField(null=True, blank=True)
    winning_bidder_type = models.CharField(max_length=50, blank=True)

    # ── Raw data ──────────────────────────────────────────────────────────────
    raw_terms     = models.TextField(blank=True)   # Full raw auction terms text
    raw_html_hash = models.CharField(max_length=64, blank=True)  # SHA256 of last fetched HTML

    # ── Monitoring ────────────────────────────────────────────────────────────
    last_checked_at = models.DateTimeField(null=True, blank=True)
    check_count     = models.PositiveIntegerField(default=0)

    # ── Timestamps ────────────────────────────────────────────────────────────
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("source", "source_id")]
        indexes = [
            models.Index(fields=["auction_date"]),
            models.Index(fields=["auction_status"]),
            models.Index(fields=["minimum_bid"]),
            models.Index(fields=["current_bid"]),
        ]

    def __str__(self):
        addr = self.property.address if self.property else "Unknown"
        return f"[{self.source_id}] {addr} — {self.auction_date}"

    @property
    def current_bid_to_min_ratio(self):
        if self.minimum_bid and self.current_bid and self.minimum_bid > 0:
            return float(self.current_bid / self.minimum_bid)
        return None

    @property
    def final_bid_to_min_ratio(self):
        if self.minimum_bid and self.final_bid and self.minimum_bid > 0:
            return float(self.final_bid / self.minimum_bid)
        return None

    @property
    def effective_buyer_premium(self):
        """Dollar amount of buyer's premium on current bid."""
        if self.buyer_premium_pct and self.current_bid:
            return self.current_bid * (self.buyer_premium_pct / Decimal("100"))
        return None


# ─────────────────────────────────────────────────────────────────────────────
# AUCTION EVENT (Change Log — append only)
# ─────────────────────────────────────────────────────────────────────────────

class AuctionEventType(models.TextChoices):
    DISCOVERED      = "DISCOVERED",      "Auction discovered"
    BID_PLACED      = "BID_PLACED",      "New bid placed"
    BID_COUNT_CHANGED = "BID_COUNT_CHANGED", "Bid count changed"
    STATUS_CHANGED  = "STATUS_CHANGED",  "Status changed"
    MIN_BID_CHANGED = "MIN_BID_CHANGED", "Minimum bid changed"
    DATE_CHANGED    = "DATE_CHANGED",    "Auction date changed"
    WITHDRAWN       = "WITHDRAWN",       "Auction withdrawn"
    CANCELLED       = "CANCELLED",       "Auction cancelled"
    CLOSED          = "CLOSED",          "Auction closed"
    OVERTIME_STARTED= "OVERTIME_STARTED","Overtime period started"
    PLAINTIFF_WIN   = "PLAINTIFF_WIN",   "Sold to plaintiff"
    THIRD_PARTY_WIN = "THIRD_PARTY_WIN", "Sold to third party"
    NO_SALE         = "NO_SALE",         "No sale / no bids"
    CHECK_COMPLETED = "CHECK_COMPLETED", "Routine check completed"


class AuctionEvent(models.Model):
    """
    Immutable log of every change observed for an auction.
    Never update — only insert.
    """
    auction    = models.ForeignKey(Auction, on_delete=models.CASCADE, related_name="events")
    event_type = models.CharField(max_length=30, choices=AuctionEventType.choices)
    occurred_at= models.DateTimeField(default=timezone.now)

    # Previous values (before change)
    previous_value = models.JSONField(null=True, blank=True)
    # New values (after change)
    new_value      = models.JSONField(null=True, blank=True)

    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["occurred_at"]
        indexes  = [models.Index(fields=["auction", "occurred_at"])]

    def __str__(self):
        return f"{self.auction.source_id} | {self.event_type} @ {self.occurred_at}"


# ─────────────────────────────────────────────────────────────────────────────
# BID HISTORY
# ─────────────────────────────────────────────────────────────────────────────

class BidObservation(models.Model):
    """
    Every publicly visible bid amount observed.
    Bidder identities are NOT stored — only public information.
    """
    auction       = models.ForeignKey(Auction, on_delete=models.CASCADE, related_name="bid_observations")
    observed_at   = models.DateTimeField(default=timezone.now)
    bid_amount    = models.DecimalField(max_digits=12, decimal_places=2)
    bid_count_snapshot = models.PositiveIntegerField()  # Total bid count at this moment
    # Public bidder username if displayed (many auctions only show "Bidder 1" etc.)
    public_bidder_id  = models.CharField(max_length=100, blank=True)

    class Meta:
        ordering = ["observed_at"]
        unique_together = [("auction", "bid_amount", "observed_at")]


# ─────────────────────────────────────────────────────────────────────────────
# PROPERTY FINANCIAL ANALYSIS
# ─────────────────────────────────────────────────────────────────────────────

class PropertyFinancial(models.Model):
    """
    Calculated financial analysis for a property/auction.
    Recalculated whenever new data arrives.
    Versioned so history is preserved.
    """
    auction     = models.ForeignKey(Auction, on_delete=models.CASCADE, related_name="financials")
    calculated_at = models.DateTimeField(auto_now_add=True)
    version     = models.PositiveSmallIntegerField(default=1)

    # ── Market value estimates ────────────────────────────────────────────────
    estimated_market_value    = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    market_value_confidence   = models.CharField(max_length=10, choices=DataConfidence.choices,
                                                  default=DataConfidence.UNKNOWN)
    arv_low                   = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    arv_base                  = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    arv_high                  = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)

    # ── Rental estimates ──────────────────────────────────────────────────────
    rent_low      = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    rent_base     = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    rent_high     = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)

    # ── Repair estimates ──────────────────────────────────────────────────────
    repair_grade  = models.CharField(max_length=1, choices=RepairGrade.choices, default=RepairGrade.F)
    repair_low    = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    repair_base   = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    repair_high   = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    # ── Acquisition costs ─────────────────────────────────────────────────────
    buyers_premium_amount   = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    transfer_tax_amount     = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    title_legal_costs       = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    recording_costs         = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    holding_costs_monthly   = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    holding_months          = models.PositiveSmallIntegerField(null=True, blank=True)

    # ── Total project cost (at current bid) ───────────────────────────────────
    total_project_cost_base = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)

    # ── Max bids ──────────────────────────────────────────────────────────────
    max_bid_aggressive      = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    max_bid_recommended     = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    max_bid_absolute        = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)

    # ── Rental cash flow ──────────────────────────────────────────────────────
    gross_monthly_rent      = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    vacancy_rate_pct        = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("8"))
    mgmt_fee_pct            = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("10"))
    maintenance_monthly     = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    capex_monthly           = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    net_monthly_cashflow    = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    cap_rate                = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    cash_on_cash_return     = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)

    # ── Flip economics ────────────────────────────────────────────────────────
    selling_costs_pct       = models.DecimalField(max_digits=4, decimal_places=2, default=Decimal("6"))
    expected_flip_profit    = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    flip_roi_pct            = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)

    # ── Scores ────────────────────────────────────────────────────────────────
    deal_score              = models.PositiveSmallIntegerField(null=True, blank=True)  # 0–100
    low_competition_score   = models.PositiveSmallIntegerField(null=True, blank=True)  # 0–100
    risk_score              = models.PositiveSmallIntegerField(null=True, blank=True)  # 0–100
    min_bid_win_probability = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)

    class Meta:
        ordering = ["-calculated_at"]
        unique_together = [("auction", "version")]


# ─────────────────────────────────────────────────────────────────────────────
# PROPERTY RISK
# ─────────────────────────────────────────────────────────────────────────────

class PropertyRisk(models.Model):
    """Risk flags for a property/auction."""
    auction = models.OneToOneField(Auction, on_delete=models.CASCADE, related_name="risk")

    # ── Legal / title risks ───────────────────────────────────────────────────
    federal_lien_suspected  = models.BooleanField(default=False)
    irs_lien_suspected      = models.BooleanField(default=False)
    municipal_lien_suspected= models.BooleanField(default=False)
    hoa_lien_suspected      = models.BooleanField(default=False)
    title_issues_noted      = models.BooleanField(default=False)
    requires_court_confirmation = models.BooleanField(default=False)
    plaintiff_can_withdraw  = models.BooleanField(default=True)

    # ── Property condition risks ──────────────────────────────────────────────
    interior_unknown        = models.BooleanField(default=True)
    occupancy_unknown       = models.BooleanField(default=True)
    potentially_occupied    = models.BooleanField(null=True, blank=True)
    structural_risk         = models.BooleanField(default=False)
    environmental_risk      = models.BooleanField(default=False)  # asbestos, lead, etc.
    flood_zone              = models.BooleanField(null=True, blank=True)

    # ── Financial risks ───────────────────────────────────────────────────────
    financing_unlikely      = models.BooleanField(default=True)   # auctions usually cash-only
    hoa_fees_unknown        = models.BooleanField(default=False)

    # ── Notes ─────────────────────────────────────────────────────────────────
    notes = models.TextField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)


# ─────────────────────────────────────────────────────────────────────────────
# COMPARABLE SALES
# ─────────────────────────────────────────────────────────────────────────────

class ComparableSale(models.Model):
    """Recently sold comparable properties used for ARV calculation."""
    property     = models.ForeignKey(Property, on_delete=models.CASCADE, related_name="comps")
    comp_address = models.CharField(max_length=255)
    comp_city    = models.CharField(max_length=100)
    comp_zip     = models.CharField(max_length=10)
    sold_price   = models.DecimalField(max_digits=12, decimal_places=2)
    sold_date    = models.DateField()
    square_feet  = models.PositiveIntegerField(null=True, blank=True)
    bedrooms     = models.PositiveSmallIntegerField(null=True, blank=True)
    bathrooms    = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True)
    distance_miles = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    price_per_sqft = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    source       = models.CharField(max_length=100, blank=True)
    source_url   = models.URLField(blank=True)
    retrieved_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-sold_date"]


class RentalComparable(models.Model):
    """Rental comps for monthly rent estimation."""
    property        = models.ForeignKey(Property, on_delete=models.CASCADE, related_name="rental_comps")
    comp_address    = models.CharField(max_length=255)
    comp_zip        = models.CharField(max_length=10)
    monthly_rent    = models.DecimalField(max_digits=8, decimal_places=2)
    bedrooms        = models.PositiveSmallIntegerField(null=True, blank=True)
    bathrooms       = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True)
    square_feet     = models.PositiveIntegerField(null=True, blank=True)
    source          = models.CharField(max_length=100, blank=True)
    retrieved_at    = models.DateTimeField(auto_now_add=True)
    listed_date     = models.DateField(null=True, blank=True)


# ─────────────────────────────────────────────────────────────────────────────
# AUCTION DOCUMENT
# ─────────────────────────────────────────────────────────────────────────────

class AuctionDocument(models.Model):
    """PDFs, notices, or other documents attached to an auction."""
    auction      = models.ForeignKey(Auction, on_delete=models.CASCADE, related_name="documents")
    document_type= models.CharField(max_length=50)  # e.g. "sheriff_list", "terms", "notice"
    title        = models.CharField(max_length=255, blank=True)
    source_url   = models.URLField(max_length=500, blank=True)
    local_path   = models.CharField(max_length=500, blank=True)
    retrieved_at = models.DateTimeField(auto_now_add=True)
    file_hash    = models.CharField(max_length=64, blank=True)


# ─────────────────────────────────────────────────────────────────────────────
# ALERT
# ─────────────────────────────────────────────────────────────────────────────

class AlertType(models.TextChoices):
    NEW_LOW_BID         = "NEW_LOW_BID",         "🔥 New low-bid auction"
    ONE_BIDDER          = "ONE_BIDDER",           "🔥 One bidder only"
    BID_AT_MINIMUM      = "BID_AT_MINIMUM",       "🔥 Current bid still at minimum"
    LOW_COMPETITION     = "LOW_COMPETITION",      "🔥 Low competition score"
    HIGH_ARV_DISCOUNT   = "HIGH_ARV_DISCOUNT",    "🔥 Large ARV discount"
    STRONG_RENTAL       = "STRONG_RENTAL",        "🔥 Strong rental cash flow"
    OVERTIME_STARTED    = "OVERTIME_STARTED",     "⚠️ Overtime started"
    PLAINTIFF_RISK      = "PLAINTIFF_RISK",       "⚠️ Plaintiff may win"
    WITHDRAWN           = "WITHDRAWN",            "⚠️ Auction withdrawn"
    CANCELLED           = "CANCELLED",            "⚠️ Auction cancelled"
    CLOSING_SOON        = "CLOSING_SOON",         "⚠️ Auction closing soon"
    NEW_AUCTION         = "NEW_AUCTION",          "📢 New auction discovered"
    PRICE_CHANGE        = "PRICE_CHANGE",         "📢 Minimum bid changed"


class Alert(models.Model):
    auction     = models.ForeignKey(Auction, on_delete=models.CASCADE, related_name="alerts")
    alert_type  = models.CharField(max_length=30, choices=AlertType.choices)
    message     = models.TextField()
    is_read     = models.BooleanField(default=False)
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.alert_type} — {self.auction.source_id}"
