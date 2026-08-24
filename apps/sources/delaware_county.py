"""
Delaware County Sheriff Sale PDF Source Adapter
================================================

Delaware County publishes their sheriff sale list as a public PDF at:
  https://www.delcopa.gov/sites/default/files/sheriff/list1.pdf

This adapter:
1. Downloads the PDF
2. Extracts text using pdfplumber
3. Parses the structured table format
4. Saves to database

The PDF format (as observed from the Sept 18, 2026 list) follows:
  No. | Sold For / Hand Money | Location / Term & No. | Name | Attorney

This is the OFFICIAL source for Delco sheriff sales — prefer this over
Bid4Assets HTML scraping for Delaware County.
"""
import hashlib
import io
import logging
import re
from decimal import Decimal
from typing import Optional

import pdfplumber
import requests
from django.conf import settings
from django.utils import timezone

from .base import AuctionSourceAdapter, UNKNOWN

logger = logging.getLogger(__name__)

DELCO_PDF_URL = "https://www.delcopa.gov/sites/default/files/sheriff/list1.pdf"
DELCO_SALE_PAGE = "https://www.delcopa.gov/sheriff/real-estate"


class DelawareCountyAdapter(AuctionSourceAdapter):
    """
    Parses Delaware County's official PDF sheriff sale list.
    More reliable than HTML scraping — official government document.
    """

    source_name = "Delaware County Sheriff"
    base_url    = "https://www.delcopa.gov"
    pdf_url     = DELCO_PDF_URL

    def discover_auctions(self) -> list[dict]:
        """
        Download and parse the Delco sheriff sale PDF.
        Returns a list of auction dicts ready for save_auction().
        This adapter does discover + parse in one step since the PDF
        contains all listings together.
        """
        logger.info(f"Fetching Delaware County sheriff sale PDF: {self.pdf_url}")
        resp = self.http.get(self.pdf_url)
        if not resp:
            logger.error("Could not download Delaware County sheriff sale PDF")
            return []

        # Check content type
        content_type = resp.headers.get("Content-Type", "")
        if "pdf" not in content_type.lower() and not resp.content[:4] == b"%PDF":
            logger.error(f"Response does not appear to be a PDF. Content-Type: {content_type}")
            return []

        pdf_hash = hashlib.sha256(resp.content).hexdigest()
        logger.info(f"PDF downloaded. Hash: {pdf_hash[:12]}...")

        auctions = self._parse_pdf(resp.content, pdf_hash)
        logger.info(f"Parsed {len(auctions)} entries from Delco PDF")
        return auctions

    def _parse_pdf(self, pdf_bytes: bytes, pdf_hash: str) -> list[dict]:
        """
        Extract and parse all sale entries from the PDF.
        """
        results = []

        try:
            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                full_text = ""
                for page in pdf.pages:
                    text = page.extract_text()
                    if text:
                        full_text += text + "\n"
        except Exception as e:
            logger.exception(f"PDF extraction failed: {e}")
            return []

        # Parse the sale date from header
        sale_date = self._extract_sale_date(full_text)
        logger.info(f"Sheriff sale date: {sale_date}")

        # Split into individual entries
        entries = self._split_entries(full_text)
        logger.info(f"Found {len(entries)} raw entries")

        for raw_entry in entries:
            try:
                parsed = self._parse_entry(raw_entry, sale_date, pdf_hash)
                if parsed:
                    results.append(parsed)
            except Exception as e:
                logger.warning(f"Error parsing entry: {e}\nRaw: {raw_entry[:200]}")

        return results

    def _extract_sale_date(self, text: str) -> Optional[str]:
        """Extract the auction sale date from the PDF header."""
        match = re.search(
            r"Real Estate Sale for\s+(\w+ \d+,?\s+\d{4}|\d{1,2}/\d{1,2}/\d{4})",
            text, re.IGNORECASE
        )
        return match.group(1).strip() if match else UNKNOWN

    def _split_entries(self, full_text: str) -> list[str]:
        """
        Split the full PDF text into individual property entries.
        Each entry starts with a number (1. 2. 3. etc.)
        """
        # Pattern: line starting with a number followed by period
        pattern = r"(?=^\d+\.\s)"
        entries = re.split(pattern, full_text, flags=re.MULTILINE)
        # Filter out empty/header lines
        return [e.strip() for e in entries if e.strip() and re.match(r"^\d+\.", e.strip())]

    def _parse_entry(self, raw: str, sale_date: str, pdf_hash: str) -> Optional[dict]:
        """
        Parse a single sheriff sale entry.

        PDF format:
          Line 1: entry_number. [plaintiff attorney firm]
          Line 2: $DEBT_AMOUNT
          Line 3: $HAND_MONEY
          Line 4: Municipality   DOCKET_NO   Owner/Defendant Name
          Line 5: Address
          Line 6: (continued entries if multiple properties)

        Additional status lines:
          "STAYED"
          "CONTINUED TO [DATE]"
        """
        lines = [l.strip() for l in raw.split("\n") if l.strip()]
        if not lines:
            return None

        entry = {
            "source_url": self.pdf_url,
            "pdf_hash":   pdf_hash,
            "sale_date":  sale_date,
            "auction_type": "SHERIFF_SALE",
        }

        # ── Entry number ───────────────────────────────────────────────────────
        no_match = re.match(r"^(\d+)\.", lines[0])
        entry["entry_number"] = no_match.group(1) if no_match else UNKNOWN
        # Use "DELCO-{entry_number}-{sale_date_slug}" as source_id
        date_slug = re.sub(r"[^\d]", "", str(sale_date))[:8]
        entry["source_id"] = f"DELCO-{entry['entry_number']}-{date_slug}"

        # ── Status flags ────────────────────────────────────────────────────────
        entry["status"] = "ACTIVE"
        for line in lines:
            if "STAYED" in line.upper():
                entry["status"] = "STAYED"
            m = re.search(r"CONTINUED TO\s+(.+?)(?:\s*\(|$)", line, re.IGNORECASE)
            if m:
                entry["status"] = f"CONTINUED — {m.group(1).strip()}"

        # ── Dollar amounts ─────────────────────────────────────────────────────
        money_amounts = re.findall(r"\$[\d,]+\.?\d*", raw)
        if len(money_amounts) >= 1:
            entry["debt_amount_raw"] = money_amounts[0]
        if len(money_amounts) >= 2:
            entry["hand_money_raw"] = money_amounts[1]

        # ── Municipality ───────────────────────────────────────────────────────
        # Typically appears after the dollar amounts
        muni_match = re.search(
            r"\$([\d,]+\.?\d*)\s*\n\s*([A-Za-z\s]+(?:Twp\.|Boro\.|Township|Borough|City)?)\s+"
            r"(\d{2}-\d{6}[A-Z]?)",
            raw
        )
        if muni_match:
            entry["municipality"] = muni_match.group(2).strip()
            entry["docket_number"] = muni_match.group(3).strip()
        else:
            entry["municipality"] = UNKNOWN
            entry["docket_number"] = UNKNOWN

        # ── Address extraction ─────────────────────────────────────────────────
        # Addresses typically have street number + name
        addr_matches = re.findall(
            r"\d+\s+[A-Z][a-zA-Z\s]+(?:Road|Rd|Street|St|Avenue|Ave|Drive|Dr|Lane|Ln|"
            r"Court|Ct|Blvd|Boulevard|Way|Circle|Cir|Place|Pl)[\.,]?",
            raw
        )
        entry["addresses"] = addr_matches  # may contain multiple properties in one entry

        if addr_matches:
            entry["primary_address"] = addr_matches[0]
        else:
            entry["primary_address"] = UNKNOWN

        # ── Defendant / owner name ─────────────────────────────────────────────
        # Name appears after docket number
        name_match = re.search(r"\d{2}-\d{6}[A-Z]?\s+(.+?)(?:\n|$)", raw)
        entry["defendant"] = name_match.group(1).strip() if name_match else UNKNOWN

        # ── Attorney ──────────────────────────────────────────────────────────
        atty_patterns = [
            r"([\w\s&]+(?:LLC|PC|LLP|Ltd|Associates|Law Group|Law Firm))",
        ]
        for pat in atty_patterns:
            atty_match = re.search(pat, raw)
            if atty_match:
                entry["attorney"] = atty_match.group(1).strip()
                break
        else:
            entry["attorney"] = UNKNOWN

        # ── Min bid calculation ───────────────────────────────────────────────
        # PA law: min bid = debt × (2/3)
        debt = self._parse_money(entry.get("debt_amount_raw", ""))
        if debt:
            entry["minimum_bid"] = float(debt * Decimal("0.6667"))
            entry["debt_amount"] = float(debt)
        else:
            entry["minimum_bid"] = None
            entry["debt_amount"] = None

        entry["hand_money"] = float(
            self._parse_money(entry.get("hand_money_raw", "")) or 0
        ) or None

        return entry

    # ── Required interface methods ─────────────────────────────────────────────

    def fetch_auction(self, source_url: str) -> Optional[str]:
        """For Delco, the 'detail page' is the PDF itself — already handled."""
        return None  # Not used; discovery handles everything

    def parse_auction(self, raw_content: str, source_url: str) -> dict:
        """Not used for PDF source — parsing done in discover_auctions."""
        return {}

    def normalize_auction(self, parsed: dict) -> dict:
        """Normalize a parsed PDF entry into our standard schema."""
        from apps.auctions.models import AuctionStatus, AuctionType

        status_raw = parsed.get("status", "ACTIVE")
        if status_raw == "STAYED":
            status = AuctionStatus.CANCELLED
        elif "CONTINUED" in status_raw:
            status = AuctionStatus.UPCOMING
        else:
            status = AuctionStatus.UPCOMING  # All future sales are upcoming

        return {
            "source_id":          parsed["source_id"],
            "source_url":         self.pdf_url,
            "auction_type":       AuctionType.SHERIFF_SALE,
            "auction_status":     status,
            "auction_date":       self._parse_date(parsed.get("sale_date", "")),
            "plaintiff":          parsed.get("attorney", ""),
            "defendant":          parsed.get("defendant", ""),
            "minimum_bid":        Decimal(str(parsed["minimum_bid"])) if parsed.get("minimum_bid") else None,
            "deposit_requirement":Decimal(str(parsed["hand_money"])) if parsed.get("hand_money") else None,
            "bid_count":          0,
            "raw_terms":          f"Docket: {parsed.get('docket_number', UNKNOWN)} | "
                                  f"Municipality: {parsed.get('municipality', UNKNOWN)} | "
                                  f"Attorney: {parsed.get('attorney', UNKNOWN)}",
            "property_data": {
                "address":       parsed.get("primary_address", ""),
                "city":          parsed.get("municipality", ""),
                "state":         "PA",
                "zip_code":      "",  # Not in PDF — enriched later
                "county":        "DELAWARE",
                "parcel_number": parsed.get("docket_number", ""),
            },
        }

    def run(self):
        """Overridden run — PDF discovers and parses in one step."""
        from apps.auctions.models import AuctionSource
        AuctionSource.objects.get_or_create(
            name=self.source_name,
            defaults={"base_url": self.base_url}
        )
        entries = self.discover_auctions()
        saved = 0
        for entry in entries:
            try:
                normalized = self.normalize_auction(entry)
                self.save_auction(normalized)
                saved += 1
            except Exception as e:
                logger.exception(f"Error saving entry {entry.get('source_id')}: {e}")
        logger.info(f"Delaware County: saved {saved}/{len(entries)}")
        return saved

    # ── Utilities ──────────────────────────────────────────────────────────────

    @staticmethod
    def _parse_money(raw: str) -> Optional[Decimal]:
        if not raw or raw == UNKNOWN:
            return None
        cleaned = re.sub(r"[^\d.]", "", str(raw))
        try:
            return Decimal(cleaned)
        except Exception:
            return None

    @staticmethod
    def _parse_date(raw: str):
        import dateparser
        if not raw or raw == UNKNOWN:
            return None
        try:
            parsed = dateparser.parse(raw)
            return parsed.date() if parsed else None
        except Exception:
            return None
