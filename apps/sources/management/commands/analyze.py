"""
Recalculate financials, scores, and alerts for stored auctions.

Usage:
  python manage.py analyze
  python manage.py analyze --auction-id=42
  python manage.py analyze --stats-only --county=DELAWARE
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Run deterministic financial analysis and scoring over stored auctions."

    def add_arguments(self, parser):
        parser.add_argument("--auction-id", type=int, default=None,
                            help="Analyze a single auction by primary key.")
        parser.add_argument("--stats-only", action="store_true",
                            help="Print historical statistics without writing scores.")
        parser.add_argument("--county", type=str, default=None,
                            help="County filter for --stats-only.")
        parser.add_argument("--zip", type=str, default=None,
                            help="ZIP filter for --stats-only.")
        parser.add_argument("--no-alerts", action="store_true",
                            help="Skip alert generation.")

    def handle(self, *args, **opts):
        from apps.analysis.engine import HistoricalAuctionStats
        from apps.sources.tasks import generate_alerts, run_analysis

        if opts["stats_only"]:
            stats = HistoricalAuctionStats().get_stats(
                county=opts["county"], zip_code=opts["zip"],
            )
            self.stdout.write(self.style.HTTP_INFO("\n▶ Historical auction statistics"))
            if stats.get("status") == "INSUFFICIENT_DATA":
                self.stdout.write(self.style.WARNING(f"  {stats['message']}"))
                return
            for key, val in stats.items():
                if key == "status":
                    continue
                self.stdout.write(f"  {key:<32} {val}")
            return

        self.stdout.write(self.style.HTTP_INFO("▶ Running analysis..."))
        result = run_analysis(auction_id=opts["auction_id"])
        self.stdout.write(self.style.SUCCESS(
            f"  ✓ Scored {result['processed']} auctions"
        ))

        if not opts["no_alerts"]:
            alerts = generate_alerts()
            self.stdout.write(self.style.SUCCESS(
                f"  ✓ Generated {alerts['created']} new alerts"
            ))
