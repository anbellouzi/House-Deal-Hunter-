from django.contrib import admin, messages

from .models import (
    Alert, Auction, AuctionDocument, AuctionEvent, AuctionSource,
    BidObservation, ComparableSale, Property, PropertyFinancial,
    PropertyRisk, RentalComparable,
)


class AuctionEventInline(admin.TabularInline):
    model = AuctionEvent
    extra = 0
    readonly_fields = ("event_type", "occurred_at", "previous_value", "new_value")
    can_delete = False


class PropertyFinancialInline(admin.TabularInline):
    model = PropertyFinancial
    extra = 0
    readonly_fields = ("calculated_at", "version", "deal_score",
                       "low_competition_score", "risk_score")


@admin.register(AuctionSource)
class AuctionSourceAdmin(admin.ModelAdmin):
    """
    Trigger crawls and analysis from the admin UI.

    This exists so the whole pipeline can be driven from a browser —
    no terminal or CLI required. Actions are queued to Celery, so the
    page returns immediately rather than blocking on a long crawl.
    """
    list_display = ("name", "base_url", "is_active", "last_crawled")
    list_filter = ("is_active",)
    actions = ["run_delaware_crawl", "run_bid4assets_crawl", "run_analysis_now"]

    def _report(self, request, outcome):
        """Show the dispatch result, whichever execution mode was used."""
        level = {
            "inline": messages.SUCCESS,
            "queued": messages.SUCCESS,
            "refused": messages.WARNING,
            "failed": messages.ERROR,
        }.get(outcome["mode"], messages.INFO)

        text = outcome["message"]
        result = outcome.get("result")
        if isinstance(result, dict):
            detail = ", ".join(f"{k}: {v}" for k, v in result.items())
            text = f"{text} ({detail})"
        self.message_user(request, text, level)

    @admin.action(description="▶ Crawl Delaware County (official PDF)")
    def run_delaware_crawl(self, request, queryset):
        from apps.sources.runner import dispatch
        from apps.sources.tasks import crawl_delaware_county
        # One PDF download and parse — fast enough to run in the request.
        self._report(request, dispatch(crawl_delaware_county, inline_ok=True))

    @admin.action(description="▶ Crawl Bid4Assets (slow — needs worker)")
    def run_bid4assets_crawl(self, request, queryset):
        from apps.sources.runner import dispatch
        from apps.sources.tasks import crawl_bid4assets
        # Enforces a 5-second delay per request, so it will outlast an
        # HTTP request. Refused inline rather than risking a timeout
        # partway through a crawl.
        self._report(request, dispatch(crawl_bid4assets, inline_ok=False))

    @admin.action(description="▶ Run analysis and scoring")
    def run_analysis_now(self, request, queryset):
        from apps.sources.runner import dispatch
        from apps.sources.tasks import run_analysis
        self._report(request, dispatch(run_analysis, inline_ok=True))


@admin.register(Auction)
class AuctionAdmin(admin.ModelAdmin):
    list_display = ("source_id", "property", "auction_date", "auction_status",
                    "minimum_bid", "current_bid", "bid_count")
    list_filter = ("auction_status", "auction_type", "source", "auction_date")
    search_fields = ("source_id", "property__address", "plaintiff", "defendant")
    date_hierarchy = "auction_date"
    inlines = [PropertyFinancialInline, AuctionEventInline]
    readonly_fields = ("created_at", "updated_at", "last_checked_at", "check_count")
    actions = ["analyze_selected"]

    @admin.action(description="▶ Re-run analysis on selected auctions")
    def analyze_selected(self, request, queryset):
        from apps.sources.runner import dispatch
        from apps.sources.tasks import run_analysis
        for auction in queryset:
            dispatch(run_analysis, auction_id=auction.pk, inline_ok=True)
        self.message_user(
            request, f"Analysis run for {queryset.count()} auction(s).",
            messages.SUCCESS,
        )


@admin.register(Property)
class PropertyAdmin(admin.ModelAdmin):
    list_display = ("address", "city", "zip_code", "county", "parcel_number",
                    "bedrooms", "bathrooms", "square_feet", "year_built")
    list_filter = ("county", "property_type", "city")
    search_fields = ("address", "parcel_number", "zip_code")


@admin.register(Alert)
class AlertAdmin(admin.ModelAdmin):
    list_display = ("alert_type", "auction", "created_at", "is_read")
    list_filter = ("alert_type", "is_read")
    actions = ["mark_read"]

    @admin.action(description="Mark selected alerts as read")
    def mark_read(self, request, queryset):
        queryset.update(is_read=True)


@admin.register(AuctionEvent)
class AuctionEventAdmin(admin.ModelAdmin):
    list_display = ("auction", "event_type", "occurred_at")
    list_filter = ("event_type",)
    readonly_fields = ("auction", "event_type", "occurred_at",
                       "previous_value", "new_value", "notes")

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False   # the event log is immutable


admin.site.register([
    PropertyFinancial, PropertyRisk, BidObservation,
    ComparableSale, RentalComparable, AuctionDocument,
])
admin.site.site_header = "Auction Intelligence"
admin.site.site_title = "Auction Intelligence"
admin.site.index_title = "Pipeline control"
