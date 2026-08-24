"""
Bid4Assets Source Adapter
=========================

⚠️  LEGAL & TECHNICAL NOTES — READ BEFORE MODIFYING
=====================================================

1. Bid4Assets does NOT expose a public API or data feed as of 2026.
   Their sitemap (https://www.bid4assets.com/sitemap.xml) lists auction
   detail pages but does not provide structured data.

2. Their public county auction pages (e.g. bid4assets.com/delawarecountysheriff)
   contain HTML-rendered auction listings that are publicly accessible
   without authentication.

3. This adapter:
   - Checks robots.txt FIRST before every request (base.py HttpClient)
   - Enforces a configurable crawl delay (default: 5 seconds)
   - Identifies itself honestly via User-Agent
   - NEVER bypasses Cloudflare, CAPTCHA, or any auth mechanism
   - If a page returns 403/429/503 with bot-protection signals, it stops

4. If Bid4Assets blocks this crawler or modifies their ToS to explicitly
   prohibit automated access, this adapter MUST be disabled.

5. A more robust long-term solution is to partner with Bid4Assets directly
   or use their official government data feed if/when one becomes available.

DATA AVAILABILITY
=================
Public pages expose:
  - Auction ID (in URL and page)
  - Property address
  - City, ZIP, County, State
  - Minimum/upset bid
  - Current bid
  - Bid count (sometimes)
  - Auction close date/time
  - Plaintiff / Defendant
  - Auction type
  - Buyer's premium (in terms section)
  - Deposit requirements

NOT publicly available without account:
  - Full bidder count history
  - Individual bidder identities
  - Complete bid timestamps (only current state shown)
"""

import logging
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from django.conf import settings

from .base import AuctionSourceAdapter

logger = logging.getLogger(__name__)

# Known public county pages on Bid4Assets for PA
PA_COUNTY_URLS = settings.BID4ASSETS_PA_COUNTIES

UNKNOWN = "UNKNOWN — VERIFY"


class Bid4AssetsAdapter(AuctionSourceAdapter):
    """
    Discovers and parses Pennsylvania sheriff/foreclosure auctions
    from publicly accessible Bid4Assets county pages.
    """

    source_name = "Bid4Assets"
    base_url    = "https://www.bid4assets.com"

    # ── 1. DISCOVER ───────────────────────────────────────────────────────────

    def discover_auctions(self) -> list[dict]:
        """
        Visit each known PA county page and collect auction detail URLs.
        """
        discovered = []

        for county_key, county_url in PA_COUNTY_URLS.items():
            logger.info(f"Discovering auctions from: {county_url}")
            resp = self.http.get(county_url)
            if not resp:
                logger.warning(f"Could not fetch county page: {county_url}")
                continue

            links = self._extract_auction_links(resp.text, county_url, county_key)
            logger.info(f"Found {len(links)} auction links on {county_key}")
            discovered.extend(links)

        # Deduplicate by source_id
        seen = set()
        unique = []
        for item in discovered:
            if item["source_id"] not in seen:
                seen.add(item["source_id"])
                unique.append(item)

        logger.info(f"Total unique auctions discovered: {len(unique)}")
        return unique

    def _extract_auction_links(self, html: str, base_page_url: str, county_key: str) -> list[dict]:
        """
        Parse county listing page HTML to find individual auction links.
        Bid4Assets auction detail URLs typically match:
          /auctions/detail/{id}
        """
        soup = BeautifulSoup(html, "html.parser")
        results = []

        # Pattern 1: Direct auction detail links
        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"]
            match = re.search(r"/auctions/detail/(\d+)", href)
            if match:
                auction_id = match.group(1)
                full_url = urljoin(self.base_url, href)
                results.append({
                    "source_id":  auction_id,
                    "source_url": full_url,
                    "county_key": county_key,
                })

        # Pattern 2: Data attributes (Bid4Assets sometimes uses JS-rendered
        # auction cards with data-auction-id)
        for elem in soup.find_all(attrs={"data-auction-id": True}):
            auction_id = elem["data-auction-id"]
            full_url = f"{self.base_url}/auctions/detail/{auction_id}"
            if not any(r["source_id"] == auction_id for r in results):
                results.append({
                    "source_id":  auction_id,
                    "source_url": full_url,
                    "county_key": county_key,
                })

        if not results:
            logger.warning(
                f"No auction links found on {base_page_url}. "
                f"The page may be JavaScript-rendered or the HTML structure changed. "
                f"Consider using Playwright/Selenium for JS-heavy pages."
            )

        return results

    # ── 2. FETCH ──────────────────────────────────────────────────────────────

    def fetch_auction(self, source_url: str) -> Optional[str]:
        """Fetch a single auction detail page."""
        resp = self.http.get(source_url)
        if resp:
            return resp.text
        return None

    # ── 3. PARSE ──────────────────────────────────────────────────────────────

    def parse_auction(self, raw_html: str, source_url: str) -> dict:
        """
        Parse Bid4Assets auction detail page HTML.
        Returns raw extracted values (not yet normalized).
        All unknown fields set to UNKNOWN — never fabricated.
        """
        soup = BeautifulSoup(raw_html, "html.parser")
        data = {
            "source_url":     source_url,
            "raw_html_hash":  self.http.html_hash(raw_html),
        }

        # ── Auction ID from URL ───────────────────────────────────────────────
        id_match = re.search(r"/auctions/detail/(\d+)", source_url)
        data["source_id"] = id_match.group(1) if id_match else UNKNOWN

        # ── Title / Address ───────────────────────────────────────────────────
        # Bid4Assets typically puts address in h1 or .auction-title
        for selector in ["h1.auction-title", "h1", ".property-address", ".auction-address"]:
            el = soup.select_one(selector)
            if el:
                data["title"] = el.get_text(strip=True)
                break
        else:
            data["title"] = UNKNOWN

        # ── Parse structured detail fields ────────────────────────────────────
        # Bid4Assets uses a dl/dt/dd pattern for key→value pairs
        detail_map = {}
        for dl in soup.find_all(["dl", "table"]):
            dts = dl.find_all(["dt", "th"])
            dds = dl.find_all(["dd", "td"])
            for dt, dd in zip(dts, dds):
                key = dt.get_text(strip=True).lower().replace(" ", "_").rstrip(":")
                val = dd.get_text(strip=True)
                detail_map[key] = val

        # Also try label: value pattern in divs
        for div in soup.find_all(["div", "span"], class_=re.compile(r"(label|key|field)")):
            sibling = div.find_next_sibling()
            if sibling:
                key = div.get_text(strip=True).lower().replace(" ", "_").rstrip(":")
                detail_map[key] = sibling.get_text(strip=True)

        logger.debug(f"Extracted {len(detail_map)} detail fields")

        # ── Minimum / Upset bid ───────────────────────────────────────────────
        data["minimum_bid_raw"] = self._find_field(
            detail_map, soup,
            ["minimum_bid", "upset_price", "starting_bid", "min_bid", "reserve"],
            css_selectors=[".minimum-bid", ".starting-bid", "#minimum-bid",
                           ".auction-minimum-bid", ".upset-price"]
        )

        # ── Current bid ───────────────────────────────────────────────────────
        data["current_bid_raw"] = self._find_field(
            detail_map, soup,
            ["current_bid", "current_price", "high_bid"],
            css_selectors=[".current-bid", "#current-bid", ".high-bid",
                           "[data-current-bid]", ".current-price"]
        )

        # ── Bid count ─────────────────────────────────────────────────────────
        data["bid_count_raw"] = self._find_field(
            detail_map, soup,
            ["bid_count", "number_of_bids", "bids", "total_bids"],
            css_selectors=[".bid-count", "#bid-count", ".number-of-bids"]
        )

        # ── Auction close time ────────────────────────────────────────────────
        data["close_time_raw"] = self._find_field(
            detail_map, soup,
            ["closes", "closing_time", "auction_end", "end_time", "auction_date",
             "close_time", "ends"],
            css_selectors=["[data-auction-end]", ".auction-end-time",
                           ".closing-time", "#auction-close-time",
                           "time[datetime]"]
        )

        # ── Auction status ────────────────────────────────────────────────────
        data["status_raw"] = self._find_field(
            detail_map, soup,
            ["status", "auction_status"],
            css_selectors=[".auction-status", "#auction-status", ".status-badge"]
        )

        # ── Plaintiff / Defendant ─────────────────────────────────────────────
        data["plaintiff_raw"] = self._find_field(
            detail_map, soup,
            ["plaintiff", "seller", "lienholder"],
            css_selectors=[".plaintiff", ".seller-name"]
        )
        data["defendant_raw"] = self._find_field(
            detail_map, soup,
            ["defendant", "borrower", "property_owner"],
            css_selectors=[".defendant", ".borrower-name"]
        )

        # ── Location fields ───────────────────────────────────────────────────
        data["address_raw"] = self._find_field(
            detail_map, soup,
            ["address", "property_address", "location"],
            css_selectors=[".property-address", ".address", "#property-address"]
        )
        data["city_raw"]    = detail_map.get("city", UNKNOWN)
        data["state_raw"]   = detail_map.get("state", "PA")
        data["zip_raw"]     = detail_map.get("zip", detail_map.get("zip_code", UNKNOWN))
        data["county_raw"]  = detail_map.get("county", UNKNOWN)
        data["parcel_raw"]  = self._find_field(
            detail_map, soup,
            ["parcel", "parcel_number", "parcel_id", "apn", "tax_id"],
            css_selectors=[".parcel-number", "#parcel-number", ".tax-id"]
        )

        # ── Financial terms ───────────────────────────────────────────────────
        data["buyer_premium_raw"]   = self._find_field(
            detail_map, soup,
            ["buyer's_premium", "buyers_premium", "buyer_premium"],
            css_selectors=[".buyer-premium", ".buyers-premium"]
        )
        data["deposit_raw"] = self._find_field(
            detail_map, soup,
            ["deposit", "required_deposit", "hand_money"],
            css_selectors=[".deposit", ".required-deposit"]
        )
        data["bid_increment_raw"] = self._find_field(
            detail_map, soup,
            ["bid_increment", "minimum_increment"],
            css_selectors=[".bid-increment"]
        )

        # ── Overtime ──────────────────────────────────────────────────────────
        data["overtime_raw"] = self._find_field(
            detail_map, soup,
            ["overtime", "overtime_period", "extended_bidding"],
            css_selectors=[".overtime", ".overtime-period"]
        )

        # ── Terms text ────────────────────────────────────────────────────────
        terms_el = soup.find(
            class_=re.compile(r"(terms|conditions|auction-terms)"),
        ) or soup.find(id=re.compile(r"(terms|conditions)"))
        data["raw_terms"] = terms_el.get_text(separator="\n", strip=True) if terms_el else ""

        # ── Auction type detection ────────────────────────────────────────────
        page_text = soup.get_text(" ").lower()
        if "sheriff" in page_text:
            data["auction_type_raw"] = "SHERIFF_SALE"
        elif "tax" in page_text and "foreclosure" in page_text:
            data["auction_type_raw"] = "TAX_FORECLOSURE"
        elif "mortgage" in page_text and "foreclosure" in page_text:
            data["auction_type_raw"] = "MORTGAGE_FORECLOSURE"
        else:
            data["auction_type_raw"] = UNKNOWN

        return data

    def _find_field(self, detail_map: dict, soup: BeautifulSoup,
                    keys: list[str], css_selectors: list[str] = None) -> str:
        """
        Try to find a field value from multiple possible keys/selectors.
        Returns UNKNOWN if not found.
        """
        # 1. Try detail_map keys
        for key in keys:
            val = detail_map.get(key)
            if val and val.strip():
                return val.strip()

        # 2. Try CSS selectors
        if css_selectors:
            for sel in css_selectors:
                el = soup.select_one(sel)
                if el:
                    # Check data attributes first
                    for attr in ["data-value", "data-bid", "data-price", "datetime", "content"]:
                        if el.get(attr):
                            return el[attr]
                    text = el.get_text(strip=True)
                    if text:
                        return text

        return UNKNOWN

    # ── 4. NORMALIZE ─────────────────────────────────────────────────────────

    def normalize_auction(self, parsed: dict) -> dict:
        """
        Convert parsed raw strings to typed Python values using our schema.
        Sets None for genuinely unknown values — never fabricates.
        """
        from apps.auctions.models import AuctionStatus, AuctionType, ReserveStatus

        n = {
            "source_id":  parsed.get("source_id", UNKNOWN),
            "source_url": parsed.get("source_url", ""),
            "raw_terms":  parsed.get("raw_terms", ""),
        }

        # ── Monetary fields ───────────────────────────────────────────────────
        n["minimum_bid"]  = self._parse_money(parsed.get("minimum_bid_raw"))
        n["current_bid"]  = self._parse_money(parsed.get("current_bid_raw"))
        n["deposit_requirement"] = self._parse_money(parsed.get("deposit_raw"))
        n["bid_increment"]= self._parse_money(parsed.get("bid_increment_raw"))

        # ── Buyer's premium ────────────────────────────────────────────────────
        premium_raw = parsed.get("buyer_premium_raw", "")
        n["buyer_premium_pct"] = self._parse_percentage(premium_raw)

        # ── Bid count ─────────────────────────────────────────────────────────
        n["bid_count"] = self._parse_int(parsed.get("bid_count_raw")) or 0

        # ── Auction date / close time ─────────────────────────────────────────
        n["auction_close_time"] = self._parse_datetime(parsed.get("close_time_raw"))
        if n["auction_close_time"]:
            n["auction_date"] = n["auction_close_time"].date()
        else:
            n["auction_date"] = None

        # ── Status ────────────────────────────────────────────────────────────
        status_raw = (parsed.get("status_raw") or "").lower()
        if "active" in status_raw or "open" in status_raw:
            n["auction_status"] = AuctionStatus.ACTIVE
        elif "upcoming" in status_raw or "scheduled" in status_raw:
            n["auction_status"] = AuctionStatus.UPCOMING
        elif "withdrawn" in status_raw:
            n["auction_status"] = AuctionStatus.WITHDRAWN
        elif "cancelled" in status_raw or "canceled" in status_raw:
            n["auction_status"] = AuctionStatus.CANCELLED
        elif "closed" in status_raw or "ended" in status_raw:
            n["auction_status"] = AuctionStatus.ENDED_THIRD_PARTY  # refined later
        else:
            n["auction_status"] = AuctionStatus.UNKNOWN

        # ── Auction type ──────────────────────────────────────────────────────
        type_raw = parsed.get("auction_type_raw", "")
        type_map = {
            "SHERIFF_SALE":         AuctionType.SHERIFF_SALE,
            "TAX_FORECLOSURE":      AuctionType.TAX_FORECLOSURE,
            "MORTGAGE_FORECLOSURE": AuctionType.MORTGAGE_FORECLOSURE,
        }
        n["auction_type"] = type_map.get(type_raw, AuctionType.OTHER)

        # ── Parties ────────────────────────────────────────────────────────────
        n["plaintiff"] = self._clean_text(parsed.get("plaintiff_raw"))
        n["defendant"] = self._clean_text(parsed.get("defendant_raw"))

        # ── Overtime ──────────────────────────────────────────────────────────
        overtime_raw = parsed.get("overtime_raw", "")
        n["overtime_minutes"] = self._parse_overtime(overtime_raw)

        # ── Reserve ───────────────────────────────────────────────────────────
        # B4A sheriff sales typically have no reserve — minimum bid IS the floor
        n["reserve_status"] = ReserveStatus.NO_RESERVE

        # ── Property fields (passed to property creation) ─────────────────────
        n["property_data"] = {
            "address":       self._clean_text(parsed.get("address_raw")),
            "city":          self._clean_text(parsed.get("city_raw")),
            "state":         parsed.get("state_raw", "PA"),
            "zip_code":      self._clean_zip(parsed.get("zip_raw")),
            "county":        self._map_county(parsed.get("county_raw", "")),
            "parcel_number": self._clean_text(parsed.get("parcel_raw")),
        }

        return n

    # ── 5. SAVE (override to create Property first) ────────────────────────────

    def save_auction(self, normalized: dict):
        from apps.auctions.models import Property, PropertyRisk
        from apps.auctions.models import County

        prop_data = normalized.pop("property_data", {})

        # Create or find property
        prop = None
        parcel = prop_data.get("parcel_number", "")
        county = prop_data.get("county", "")

        if parcel and parcel != UNKNOWN and county and county != UNKNOWN:
            prop, created = Property.objects.get_or_create(
                parcel_number=parcel,
                county=county,
                defaults={
                    "address":   prop_data.get("address", ""),
                    "city":      prop_data.get("city", ""),
                    "state":     prop_data.get("state", "PA"),
                    "zip_code":  prop_data.get("zip_code", ""),
                }
            )
        elif prop_data.get("address") and prop_data["address"] != UNKNOWN:
            # Fall back to address match
            prop, _ = Property.objects.get_or_create(
                address=prop_data.get("address", ""),
                zip_code=prop_data.get("zip_code", ""),
                defaults=prop_data,
            )

        if prop:
            normalized["property_id"] = prop.pk

        # Create risk record
        auction = super().save_auction(normalized)

        if prop and not hasattr(auction, "risk"):
            PropertyRisk.objects.get_or_create(
                auction=auction,
                defaults={
                    "interior_unknown": True,
                    "occupancy_unknown": True,
                    "financing_unlikely": True,
                    "plaintiff_can_withdraw": True,
                }
            )

        return auction

    # ── Parsing utilities ─────────────────────────────────────────────────────

    @staticmethod
    def _parse_money(raw: str) -> Optional[Decimal]:
        if not raw or raw == UNKNOWN:
            return None
        cleaned = re.sub(r"[^\d.]", "", str(raw))
        try:
            val = Decimal(cleaned)
            return val if val > 0 else None
        except InvalidOperation:
            return None

    @staticmethod
    def _parse_percentage(raw: str) -> Optional[Decimal]:
        if not raw or raw == UNKNOWN:
            return None
        match = re.search(r"(\d+\.?\d*)\s*%", str(raw))
        if match:
            try:
                return Decimal(match.group(1))
            except InvalidOperation:
                pass
        return None

    @staticmethod
    def _parse_int(raw: str) -> Optional[int]:
        if not raw or raw == UNKNOWN:
            return None
        match = re.search(r"\d+", str(raw))
        return int(match.group()) if match else None

    @staticmethod
    def _parse_datetime(raw: str) -> Optional[datetime]:
        if not raw or raw == UNKNOWN:
            return None
        formats = [
            "%m/%d/%Y %I:%M %p",
            "%m/%d/%Y %H:%M",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M:%S",
            "%B %d, %Y %I:%M %p",
            "%b %d, %Y %I:%M %p",
        ]
        for fmt in formats:
            try:
                return datetime.strptime(raw.strip(), fmt)
            except ValueError:
                continue
        return None

    @staticmethod
    def _parse_overtime(raw: str) -> Optional[int]:
        if not raw or raw == UNKNOWN:
            return None
        match = re.search(r"(\d+)\s*(min|minute|hour)", str(raw).lower())
        if match:
            val = int(match.group(1))
            if "hour" in match.group(2):
                val *= 60
            return val
        return None

    @staticmethod
    def _clean_text(raw: str) -> str:
        if not raw or raw == UNKNOWN:
            return ""
        return " ".join(raw.split())

    @staticmethod
    def _clean_zip(raw: str) -> str:
        if not raw or raw == UNKNOWN:
            return ""
        match = re.search(r"\d{5}", str(raw))
        return match.group() if match else ""

    @staticmethod
    def _map_county(raw: str) -> str:
        from apps.auctions.models import County
        mapping = {
            "delaware":     County.DELAWARE,
            "montgomery":   County.MONTGOMERY,
            "philadelphia": County.PHILADELPHIA,
            "chester":      County.CHESTER,
            "bucks":        County.BUCKS,
        }
        raw_lower = raw.lower()
        for key, val in mapping.items():
            if key in raw_lower:
                return val
        return County.OTHER_PA
