"""
Manual crawl trigger.

Usage:
  python manage.py crawl --source=bid4assets
  python manage.py crawl --source=delaware
  python manage.py crawl --source=all
  python manage.py crawl --source=bid4assets --dry-run
"""
import logging

from django.core.management.base import BaseCommand, CommandError

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Discover and import auctions from a configured source."

    def add_arguments(self, parser):
        parser.add_argument(
            "--source", type=str, default="all",
            choices=["bid4assets", "delaware", "all"],
            help="Which source adapter to run.",
        )
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Discover and parse but do not write to the database.",
        )

    def handle(self, *args, **options):
        source = options["source"]
        dry_run = options["dry_run"]

        from apps.sources.bid4assets import Bid4AssetsAdapter
        from apps.sources.delaware_county import DelawareCountyAdapter

        adapters = []
        if source in ("bid4assets", "all"):
            adapters.append(Bid4AssetsAdapter())
        if source in ("delaware", "all"):
            adapters.append(DelawareCountyAdapter())

        if not adapters:
            raise CommandError(f"No adapter matched source={source}")

        total = 0
        for adapter in adapters:
            self.stdout.write(self.style.HTTP_INFO(
                f"\n▶ Running {adapter.source_name}..."
            ))

            if dry_run:
                listings = adapter.discover_auctions()
                self.stdout.write(self.style.WARNING(
                    f"  DRY RUN — discovered {len(listings)} listings, nothing saved."
                ))
                for item in listings[:10]:
                    self.stdout.write(f"    · {item.get('source_id')} "
                                      f"{item.get('source_url', '')[:80]}")
                if len(listings) > 10:
                    self.stdout.write(f"    ... and {len(listings)-10} more")
                continue

            try:
                saved = adapter.run()
                total += saved
                self.stdout.write(self.style.SUCCESS(
                    f"  ✓ {adapter.source_name}: {saved} auctions processed"
                ))
            except Exception as e:
                logger.exception("Adapter failed")
                self.stdout.write(self.style.ERROR(
                    f"  ✗ {adapter.source_name} failed: {e}"
                ))

        if not dry_run:
            self.stdout.write(self.style.SUCCESS(
                f"\n✓ Crawl complete. {total} auctions processed total."
            ))
            self.stdout.write(
                "  Next: run `python manage.py analyze` to score them."
            )
