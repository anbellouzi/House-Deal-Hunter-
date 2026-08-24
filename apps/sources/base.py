"""
Base auction source adapter.
All sources inherit from AuctionSourceAdapter.
"""
import hashlib
import logging
import time
from abc import ABC, abstractmethod
from typing import Optional
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import requests
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

CRAWLER_CFG = settings.CRAWLER


class RobotsTxtCache:
    """Thread-safe robots.txt cache — one parser per domain."""
    _cache: dict[str, tuple[RobotFileParser, float]] = {}
    _TTL = 3600  # refresh every hour

    @classmethod
    def get_parser(cls, base_url: str) -> RobotFileParser:
        domain = urlparse(base_url).netloc
        now = time.time()
        if domain in cls._cache:
            parser, fetched_at = cls._cache[domain]
            if now - fetched_at < cls._TTL:
                return parser

        robots_url = f"https://{domain}/robots.txt"
        parser = RobotFileParser()
        parser.set_url(robots_url)
        try:
            parser.read()
            logger.info(f"Fetched robots.txt for {domain}")
        except Exception as e:
            logger.warning(f"Could not fetch robots.txt for {domain}: {e}")
        cls._cache[domain] = (parser, now)
        return parser

    @classmethod
    def can_fetch(cls, url: str, user_agent: str) -> bool:
        if not CRAWLER_CFG.get("RESPECT_ROBOTS_TXT", True):
            return True
        parser = cls.get_parser(url)
        allowed = parser.can_fetch(user_agent, url)
        if not allowed:
            logger.warning(f"robots.txt DISALLOWS: {url}")
        return allowed


class RateLimiter:
    """Simple per-domain rate limiter."""
    _last_request: dict[str, float] = {}

    @classmethod
    def wait(cls, url: str):
        domain = urlparse(url).netloc
        now = time.time()
        last = cls._last_request.get(domain, 0)
        delay = CRAWLER_CFG["CRAWL_DELAY_SECONDS"]
        wait_time = delay - (now - last)
        if wait_time > 0:
            logger.debug(f"Rate limiting: sleeping {wait_time:.1f}s for {domain}")
            time.sleep(wait_time)
        cls._last_request[domain] = time.time()


class HttpClient:
    """
    Polite HTTP client:
    - Identifies itself honestly via User-Agent
    - Respects robots.txt
    - Enforces crawl delay
    - Retries on transient failures
    - Never bypasses auth, CAPTCHA, or Cloudflare
    """

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": CRAWLER_CFG["USER_AGENT"],
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        })
        self.timeout = CRAWLER_CFG["REQUEST_TIMEOUT"]
        self.max_retries = CRAWLER_CFG["MAX_RETRIES"]

    def get(self, url: str, **kwargs) -> Optional[requests.Response]:
        """Fetch a URL respecting robots.txt and rate limits."""
        ua = CRAWLER_CFG["USER_AGENT"]

        # 1. Check robots.txt
        if not RobotsTxtCache.can_fetch(url, ua):
            logger.warning(f"BLOCKED by robots.txt: {url}")
            return None

        # 2. Rate limit
        RateLimiter.wait(url)

        # 3. Fetch with retries
        for attempt in range(1, self.max_retries + 1):
            try:
                resp = self.session.get(url, timeout=self.timeout, **kwargs)

                # Detect Cloudflare / bot challenge pages — never try to bypass
                if resp.status_code in (403, 503) and "cloudflare" in resp.text.lower():
                    logger.error(f"Cloudflare protection detected at {url} — stopping.")
                    return None

                if resp.status_code == 429:
                    wait = int(resp.headers.get("Retry-After", 60))
                    logger.warning(f"Rate limited (429). Waiting {wait}s.")
                    time.sleep(wait)
                    continue

                resp.raise_for_status()
                return resp

            except requests.HTTPError as e:
                logger.warning(f"HTTP error on attempt {attempt}/{self.max_retries}: {e}")
                if attempt < self.max_retries:
                    time.sleep(2 ** attempt)  # exponential backoff
            except requests.RequestException as e:
                logger.warning(f"Request error on attempt {attempt}/{self.max_retries}: {e}")
                if attempt < self.max_retries:
                    time.sleep(2 ** attempt)

        logger.error(f"All {self.max_retries} attempts failed for {url}")
        return None

    @staticmethod
    def html_hash(content: str) -> str:
        return hashlib.sha256(content.encode()).hexdigest()


class AuctionSourceAdapter(ABC):
    """
    Abstract base for all auction sources.
    Every source must implement these five methods.
    """
    source_name: str = "BASE"
    base_url: str = ""

    def __init__(self):
        self.http = HttpClient()

    @abstractmethod
    def discover_auctions(self) -> list[dict]:
        """
        Find all current auction listing URLs/IDs.
        Returns list of dicts: {source_id, source_url, ...minimal data}
        """
        ...

    @abstractmethod
    def fetch_auction(self, source_url: str) -> Optional[str]:
        """
        Fetch raw HTML/JSON for a single auction detail page.
        Returns raw content string, or None if failed.
        """
        ...

    @abstractmethod
    def parse_auction(self, raw_content: str, source_url: str) -> dict:
        """
        Parse raw content into a normalized dict.
        Return UNKNOWN_VERIFY for missing fields — never fabricate.
        """
        ...

    @abstractmethod
    def normalize_auction(self, parsed: dict) -> dict:
        """
        Map parsed fields to our standard schema.
        """
        ...

    def save_auction(self, normalized: dict) -> "Auction":
        """
        Save (or update) auction to database.
        Uses get_or_create + AuctionEvent for change tracking.
        """
        from apps.auctions.models import (
            Auction, AuctionSource, AuctionEvent, AuctionEventType, Property
        )

        source, _ = AuctionSource.objects.get_or_create(
            name=self.source_name,
            defaults={"base_url": self.base_url}
        )

        auction, created = Auction.objects.get_or_create(
            source=source,
            source_id=normalized["source_id"],
            defaults=self._build_auction_defaults(normalized),
        )

        if created:
            AuctionEvent.objects.create(
                auction=auction,
                event_type=AuctionEventType.DISCOVERED,
                new_value=normalized,
                notes=f"First discovered via {self.source_name}",
            )
            logger.info(f"NEW AUCTION: {auction.source_id} — {auction}")
        else:
            self._detect_and_log_changes(auction, normalized)
            self._update_auction_fields(auction, normalized)

        auction.last_checked_at = timezone.now()
        auction.check_count = (auction.check_count or 0) + 1
        auction.save()
        return auction

    def _build_auction_defaults(self, n: dict) -> dict:
        from apps.auctions.models import AuctionStatus, AuctionType
        return {
            "source_url":           n.get("source_url", ""),
            "auction_type":         n.get("auction_type", AuctionType.SHERIFF_SALE),
            "auction_status":       n.get("auction_status", AuctionStatus.UNKNOWN),
            "auction_date":         n.get("auction_date"),
            "auction_close_time":   n.get("auction_close_time"),
            "plaintiff":            n.get("plaintiff", ""),
            "defendant":            n.get("defendant", ""),
            "minimum_bid":          n.get("minimum_bid"),
            "current_bid":          n.get("current_bid"),
            "final_bid":            n.get("final_bid"),
            "bid_increment":        n.get("bid_increment"),
            "bid_count":            n.get("bid_count", 0),
            "bidder_count":         n.get("bidder_count"),
            "reserve_status":       n.get("reserve_status", "UNKNOWN"),
            "overtime_minutes":     n.get("overtime_minutes"),
            "deposit_requirement":  n.get("deposit_requirement"),
            "buyer_premium_pct":    n.get("buyer_premium_pct"),
            "payment_deadline_days":n.get("payment_deadline_days"),
            "raw_terms":            n.get("raw_terms", ""),
        }

    def _detect_and_log_changes(self, auction, normalized: dict):
        from apps.auctions.models import AuctionEvent, AuctionEventType

        watchfields = {
            "current_bid":    AuctionEventType.BID_PLACED,
            "bid_count":      AuctionEventType.BID_COUNT_CHANGED,
            "minimum_bid":    AuctionEventType.MIN_BID_CHANGED,
            "auction_status": AuctionEventType.STATUS_CHANGED,
            "auction_date":   AuctionEventType.DATE_CHANGED,
        }

        for field, event_type in watchfields.items():
            old_val = getattr(auction, field, None)
            new_val = normalized.get(field)
            if new_val is not None and str(old_val) != str(new_val):
                AuctionEvent.objects.create(
                    auction=auction,
                    event_type=event_type,
                    previous_value={field: str(old_val)},
                    new_value={field: str(new_val)},
                )
                logger.info(f"CHANGE [{event_type}] {auction.source_id}: {old_val} → {new_val}")

    def _update_auction_fields(self, auction, normalized: dict):
        for field, val in self._build_auction_defaults(normalized).items():
            if val is not None:
                setattr(auction, field, val)

    def run(self):
        """Full pipeline: discover → fetch → parse → normalize → save."""
        logger.info(f"Starting {self.source_name} pipeline")
        listings = self.discover_auctions()
        logger.info(f"Discovered {len(listings)} listings")

        saved = 0
        for listing in listings:
            try:
                raw = self.fetch_auction(listing["source_url"])
                if not raw:
                    continue
                parsed = self.parse_auction(raw, listing["source_url"])
                normalized = self.normalize_auction(parsed)
                self.save_auction(normalized)
                saved += 1
            except Exception as e:
                logger.exception(f"Error processing {listing.get('source_url')}: {e}")

        logger.info(f"{self.source_name} pipeline complete: {saved}/{len(listings)} saved")
        return saved
