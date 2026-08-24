"""
Test suite.

Run with:
  pytest
  pytest apps/auctions/tests.py -v
  pytest -k test_min_bid
"""
from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.analysis.engine import (
    AcquisitionCostCalculator, DealScorer, HistoricalAuctionStats,
    LowCompetitionScorer, MaxBidCalculator, MinBidWinProbability,
)
from apps.auctions.models import (
    Auction, AuctionEvent, AuctionEventType, AuctionSource, AuctionStatus,
    AuctionType, County, Property, PropertyFinancial, PropertyRisk,
)


# ─────────────────────────────────────────────────────────────────────────────
# FIXTURES
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def source(db):
    return AuctionSource.objects.create(
        name="Bid4Assets", base_url="https://www.bid4assets.com"
    )


@pytest.fixture
def prop(db):
    return Property.objects.create(
        address="4127 Garrett Rd", city="Drexel Hill", state="PA",
        zip_code="19026", county=County.DELAWARE,
        parcel_number="16-11-00123-45", bedrooms=3, bathrooms=Decimal("1.0"),
        square_feet=1245, year_built=1923,
    )


@pytest.fixture
def auction(db, source, prop):
    return Auction.objects.create(
        source=source, source_id="TEST-001",
        source_url="https://www.bid4assets.com/auctions/detail/TEST-001",
        property=prop,
        auction_type=AuctionType.SHERIFF_SALE,
        auction_status=AuctionStatus.ACTIVE,
        auction_date=date.today() + timedelta(days=14),
        auction_close_time=timezone.now() + timedelta(days=14),
        minimum_bid=Decimal("87074.00"),
        current_bid=Decimal("87074.00"),
        bid_count=0, bidder_count=0,
        buyer_premium_pct=Decimal("10.00"),
        deposit_requirement=Decimal("13061.08"),
    )


# ─────────────────────────────────────────────────────────────────────────────
# MODEL TESTS
# ─────────────────────────────────────────────────────────────────────────────

class TestModels:

    def test_auction_creation(self, auction):
        assert auction.source_id == "TEST-001"
        assert auction.minimum_bid == Decimal("87074.00")

    def test_current_bid_ratio(self, auction):
        assert auction.current_bid_to_min_ratio == pytest.approx(1.0)

    def test_current_bid_ratio_none_when_missing(self, db, source, prop):
        a = Auction.objects.create(
            source=source, source_id="T2", source_url="http://x",
            property=prop, minimum_bid=None, current_bid=None,
        )
        assert a.current_bid_to_min_ratio is None

    def test_effective_buyer_premium(self, auction):
        # 10% of 87,074
        assert auction.effective_buyer_premium == pytest.approx(Decimal("8707.40"))

    def test_property_unique_by_parcel_and_county(self, db, prop):
        with pytest.raises(Exception):
            Property.objects.create(
                address="Different address", city="X", zip_code="19026",
                county=County.DELAWARE, parcel_number="16-11-00123-45",
            )

    def test_auction_events_are_append_only(self, auction):
        AuctionEvent.objects.create(
            auction=auction, event_type=AuctionEventType.DISCOVERED,
            new_value={"minimum_bid": "87074.00"},
        )
        AuctionEvent.objects.create(
            auction=auction, event_type=AuctionEventType.BID_PLACED,
            previous_value={"current_bid": "87074.00"},
            new_value={"current_bid": "92000.00"},
        )
        assert auction.events.count() == 2
        # History is fully reconstructable
        assert auction.events.first().event_type == AuctionEventType.DISCOVERED


# ─────────────────────────────────────────────────────────────────────────────
# ACQUISITION COST TESTS
# ─────────────────────────────────────────────────────────────────────────────

class TestAcquisitionCost:

    def test_full_cost_calculation(self):
        calc = AcquisitionCostCalculator()
        r = calc.calculate(
            winning_bid=Decimal("100000"),
            buyer_premium_pct=Decimal("10"),
            repair_estimate=Decimal("20000"),
            holding_months=6,
            monthly_holding=Decimal("500"),
        )
        assert r["buyer_premium_amount"] == Decimal("10000.00")
        assert r["transfer_tax_amount"] == Decimal("3000.00")   # 3% default
        assert r["repair_contingency"] == Decimal("3000.00")    # 15% of 20k
        assert r["repair_total"] == Decimal("23000.00")
        assert r["holding_costs"] == Decimal("3000.00")
        # 100000 + 10000 + 3000 + 3000 + 500 + 23000 + 3000
        assert r["total_project_cost"] == Decimal("142500.00")

    def test_unknown_repairs_flagged_not_guessed(self):
        calc = AcquisitionCostCalculator()
        r = calc.calculate(
            winning_bid=Decimal("100000"),
            buyer_premium_pct=Decimal("10"),
            repair_estimate=None,
        )
        assert r["repair_total"] is None
        assert "repair_note" in r
        assert "UNKNOWN" in r["repair_note"]

    def test_unknown_buyer_premium_flagged(self):
        calc = AcquisitionCostCalculator()
        r = calc.calculate(
            winning_bid=Decimal("100000"),
            buyer_premium_pct=None,
            repair_estimate=Decimal("10000"),
        )
        assert r["buyer_premium_amount"] == Decimal("0")
        assert "UNKNOWN" in r["buyer_premium_note"]


# ─────────────────────────────────────────────────────────────────────────────
# MAX BID TESTS
# ─────────────────────────────────────────────────────────────────────────────

class TestMaxBid:

    def test_flip_max_bid_ordering(self):
        calc = MaxBidCalculator()
        r = calc.flip_max_bid(
            arv=Decimal("250000"),
            repair_base=Decimal("25000"),
            repair_high=Decimal("40000"),
            buyer_premium_pct=Decimal("10"),
            desired_profit=Decimal("40000"),
        )
        # Aggressive (less profit required) > Recommended
        assert r["max_bid_aggressive"] > r["max_bid_recommended"]
        # Absolute uses high repair estimate
        assert r["max_bid_absolute"] < r["max_bid_aggressive"]
        assert "MODEL ESTIMATE" in r["note"]

    def test_flip_requires_arv(self):
        calc = MaxBidCalculator()
        r = calc.flip_max_bid(
            arv=None, repair_base=Decimal("20000"),
            repair_high=None, buyer_premium_pct=None,
        )
        assert "error" in r

    def test_unknown_repair_produces_warning(self):
        calc = MaxBidCalculator()
        r = calc.flip_max_bid(
            arv=Decimal("250000"), repair_base=None,
            repair_high=None, buyer_premium_pct=None,
        )
        assert "repair_warning" in r

    def test_rental_max_bid(self):
        calc = MaxBidCalculator()
        r = calc.rental_max_bid(
            monthly_rent=Decimal("1800"),
            repair_base=Decimal("20000"),
            annual_taxes=Decimal("3500"),
            desired_cap_rate=Decimal("8"),
        )
        assert r["gross_annual_rent"] == Decimal("21600")
        assert r["noi"] > 0
        assert r["max_bid_recommended"] is not None
        assert "MODEL ESTIMATE" in r["note"]

    def test_rental_requires_rent(self):
        calc = MaxBidCalculator()
        r = calc.rental_max_bid(
            monthly_rent=None, repair_base=None, annual_taxes=None,
        )
        assert "error" in r


# ─────────────────────────────────────────────────────────────────────────────
# HISTORICAL STATS TESTS — the critical "never fabricate" guarantee
# ─────────────────────────────────────────────────────────────────────────────

class TestHistoricalStats:

    def test_insufficient_data_returned_not_fabricated(self, db, source, prop):
        """With <30 completed auctions we must return INSUFFICIENT_DATA."""
        Auction.objects.create(
            source=source, source_id="H1", source_url="http://x", property=prop,
            auction_status=AuctionStatus.ENDED_THIRD_PARTY,
            minimum_bid=Decimal("50000"), final_bid=Decimal("55000"),
        )
        stats = HistoricalAuctionStats().get_stats(county=County.DELAWARE)
        assert stats["status"] == "INSUFFICIENT_DATA"
        assert stats["sample_size"] == 1
        assert stats["min_required"] == 30
        # No fabricated numbers present
        assert "avg_final_min_ratio" not in stats

    def test_sufficient_data_produces_stats(self, db, source):
        for i in range(35):
            p = Property.objects.create(
                address=f"{i} Test St", city="Drexel Hill", zip_code="19026",
                county=County.DELAWARE, parcel_number=f"PARCEL-{i}",
            )
            Auction.objects.create(
                source=source, source_id=f"HIST-{i}", source_url="http://x",
                property=p, auction_status=AuctionStatus.ENDED_THIRD_PARTY,
                minimum_bid=Decimal("100000"),
                final_bid=Decimal("105000"),   # 1.05 ratio
                bid_count=2, bidder_count=1,
            )
        stats = HistoricalAuctionStats().get_stats(county=County.DELAWARE)
        assert stats["status"] == "OK"
        assert stats["sample_size"] == 35
        assert stats["avg_final_min_ratio"] == pytest.approx(1.05, abs=0.01)
        assert stats["pct_sold_within_10pct"] == 100.0
        assert stats["avg_bidder_count"] == 1.0


# ─────────────────────────────────────────────────────────────────────────────
# LOW COMPETITION SCORE TESTS
# ─────────────────────────────────────────────────────────────────────────────

class TestLowCompetitionScore:

    def test_score_in_valid_range(self, auction):
        scorer = LowCompetitionScorer()
        stats = {"status": "INSUFFICIENT_DATA", "sample_size": 0, "min_required": 30}
        r = scorer.score(auction, stats)
        assert 0 <= r["score"] <= 100
        assert r["confidence"] == "LOW"
        assert "MODEL ESTIMATE" in r["note"]

    def test_zero_bidders_scores_high(self, auction):
        auction.bidder_count = 0
        scorer = LowCompetitionScorer()
        stats = {"status": "INSUFFICIENT_DATA", "sample_size": 0, "min_required": 30}
        r = scorer.score(auction, stats)
        assert r["components"]["current_bidder_count"] == 95

    def test_many_bidders_scores_low(self, auction):
        auction.bidder_count = 8
        scorer = LowCompetitionScorer()
        stats = {"status": "INSUFFICIENT_DATA", "sample_size": 0, "min_required": 30}
        r = scorer.score(auction, stats)
        assert r["components"]["current_bidder_count"] == 20

    def test_historical_data_raises_confidence(self, auction):
        scorer = LowCompetitionScorer()
        stats = {
            "status": "OK", "sample_size": 40,
            "avg_bidder_count": 1.2, "median_final_min_ratio": 1.03,
            "pct_sold_within_10pct": 60,
        }
        r = scorer.score(auction, stats)
        assert r["confidence"] == "HIGH"
        assert r["components"]["historical_bidder_count"] == 75
        assert r["score"] >= 70


# ─────────────────────────────────────────────────────────────────────────────
# WIN PROBABILITY TESTS
# ─────────────────────────────────────────────────────────────────────────────

class TestWinProbability:

    def test_insufficient_data_returns_none_not_a_guess(self):
        engine = MinBidWinProbability()
        r = engine.estimate(
            {"status": "INSUFFICIENT_DATA", "min_required": 30}, current_bid_ratio=1.0
        )
        assert r["at_minimum"] is None
        assert r["within_10pct"] is None
        assert r["status"] == "INSUFFICIENT_DATA"
        assert "MODEL ESTIMATE" in r["note"]

    def test_probabilities_from_real_stats(self):
        engine = MinBidWinProbability()
        r = engine.estimate({
            "status": "OK", "sample_size": 50,
            "pct_sold_at_minimum": 30.0,
            "pct_sold_within_10pct": 45.0,
            "pct_sold_within_25pct": 62.0,
        }, current_bid_ratio=1.0)
        assert r["at_minimum"] == 30.0
        assert r["within_10pct"] == 45.0
        assert r["significant_competition"] == 38.0


# ─────────────────────────────────────────────────────────────────────────────
# DEAL SCORE TESTS
# ─────────────────────────────────────────────────────────────────────────────

class TestDealScore:

    def test_strong_deal_gets_high_grade(self):
        scorer = DealScorer()
        r = scorer.score(
            minimum_bid=Decimal("87000"),
            market_value=Decimal("222000"),   # 61% discount
            arv=Decimal("250000"),
            monthly_rent=Decimal("1800"),     # ~24% gross yield
            repair_base=Decimal("20000"),
            low_competition_score=85,
            flip_profit=Decimal("80000"),
            risk_score=40,
        )
        assert r["deal_score"] >= 70
        assert r["grade"] in ("A+", "A", "B")

    def test_weak_deal_gets_low_grade(self):
        scorer = DealScorer()
        r = scorer.score(
            minimum_bid=Decimal("200000"),
            market_value=Decimal("210000"),   # only 5% discount
            arv=Decimal("215000"),
            monthly_rent=Decimal("1200"),
            repair_base=Decimal("50000"),
            low_competition_score=25,
            flip_profit=Decimal("2000"),
            risk_score=85,
        )
        assert r["deal_score"] < 60
        assert r["grade"] in ("C", "D", "F")

    def test_missing_data_does_not_inflate_score(self):
        scorer = DealScorer()
        r = scorer.score(
            minimum_bid=None, market_value=None, arv=None,
            monthly_rent=None, repair_base=None,
            low_competition_score=50, flip_profit=None, risk_score=50,
        )
        assert r["components"]["discount_to_market"] == 0
        assert r["components"]["rental_economics"] == 0
        assert r["components"]["flip_economics"] == 0
        assert r["deal_score"] < 50


# ─────────────────────────────────────────────────────────────────────────────
# API TESTS
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.django_db
class TestAPI:

    def setup_method(self):
        self.client = APIClient()

    def test_auction_list(self, auction):
        resp = self.client.get("/api/auctions/")
        assert resp.status_code == 200
        assert resp.data["count"] >= 1

    def test_auction_detail(self, auction):
        resp = self.client.get(f"/api/auctions/{auction.id}/")
        assert resp.status_code == 200
        assert resp.data["source_id"] == "TEST-001"
        assert "events" in resp.data
        assert "risk" in resp.data

    def test_filter_by_county(self, auction):
        resp = self.client.get("/api/auctions/?county=DELAWARE")
        assert resp.status_code == 200
        assert resp.data["count"] >= 1

    def test_filter_by_zip(self, auction):
        resp = self.client.get("/api/auctions/?zip_code=19026")
        assert resp.data["count"] >= 1
        resp2 = self.client.get("/api/auctions/?zip_code=99999")
        assert resp2.data["count"] == 0

    def test_filter_by_min_bid_range(self, auction):
        resp = self.client.get("/api/auctions/?minimum_bid_max=90000")
        assert resp.data["count"] >= 1
        resp2 = self.client.get("/api/auctions/?minimum_bid_min=200000")
        assert resp2.data["count"] == 0

    def test_one_bidder_endpoint(self, auction):
        resp = self.client.get("/api/auctions/one-bidder/")
        assert resp.status_code == 200
        assert len(resp.data) >= 1

    def test_closing_soon_endpoint(self, auction):
        resp = self.client.get("/api/auctions/closing-soon/?hours=720")
        assert resp.status_code == 200

    def test_history_endpoint(self, auction):
        AuctionEvent.objects.create(
            auction=auction, event_type=AuctionEventType.DISCOVERED,
            new_value={"x": 1},
        )
        resp = self.client.get(f"/api/auctions/{auction.id}/history/")
        assert resp.status_code == 200
        assert len(resp.data["events"]) == 1


# ─────────────────────────────────────────────────────────────────────────────
# PARSER TESTS
# ─────────────────────────────────────────────────────────────────────────────

class TestBid4AssetsParser:

    def test_money_parsing(self):
        from apps.sources.bid4assets import Bid4AssetsAdapter
        p = Bid4AssetsAdapter._parse_money
        assert p("$130,610.83") == Decimal("130610.83")
        assert p("87,074") == Decimal("87074")
        assert p("UNKNOWN — VERIFY") is None
        assert p("") is None
        assert p(None) is None

    def test_percentage_parsing(self):
        from apps.sources.bid4assets import Bid4AssetsAdapter
        p = Bid4AssetsAdapter._parse_percentage
        assert p("10%") == Decimal("10")
        assert p("Buyer's Premium: 7.5%") == Decimal("7.5")
        assert p("UNKNOWN — VERIFY") is None

    def test_overtime_parsing(self):
        from apps.sources.bid4assets import Bid4AssetsAdapter
        p = Bid4AssetsAdapter._parse_overtime
        assert p("5 minutes") == 5
        assert p("1 hour") == 60
        assert p("no overtime info") is None

    def test_zip_cleaning(self):
        from apps.sources.bid4assets import Bid4AssetsAdapter
        c = Bid4AssetsAdapter._clean_zip
        assert c("19026-3612") == "19026"
        assert c("PA 19026") == "19026"
        assert c("") == ""

    def test_county_mapping(self):
        from apps.sources.bid4assets import Bid4AssetsAdapter
        m = Bid4AssetsAdapter._map_county
        assert m("Delaware County") == County.DELAWARE
        assert m("montgomery") == County.MONTGOMERY
        assert m("Lancaster") == County.OTHER_PA


class TestDelawareCountyParser:

    SAMPLE_ENTRY = """24. McCabe Weisberg & Conway LLC
$130,610.83
$13,061.08
Upper Darby Twp. 25-011860
James M Kemble
Christina L Kemble
4127 Garrett Road,,
"""

    def test_entry_parsing(self):
        from apps.sources.delaware_county import DelawareCountyAdapter
        adapter = DelawareCountyAdapter()
        entry = adapter._parse_entry(self.SAMPLE_ENTRY, "September 18, 2026", "hash123")
        assert entry["entry_number"] == "24"
        assert entry["debt_amount"] == pytest.approx(130610.83)
        assert entry["hand_money"] == pytest.approx(13061.08)
        # Min bid = 2/3 of debt per PA law
        assert entry["minimum_bid"] == pytest.approx(130610.83 * 0.6667, rel=1e-3)
        assert "Garrett Road" in entry["primary_address"]

    def test_stayed_status_detected(self):
        from apps.sources.delaware_county import DelawareCountyAdapter
        adapter = DelawareCountyAdapter()
        raw = "13. Portnoff Law Associates Ltd\nSTAYED\n$2,489.62\n$3,000.00\nChester 14-069259\n"
        entry = adapter._parse_entry(raw, "September 18, 2026", "h")
        assert entry["status"] == "STAYED"

    def test_continued_status_detected(self):
        from apps.sources.delaware_county import DelawareCountyAdapter
        adapter = DelawareCountyAdapter()
        raw = "11. The Manley Law Firm LLC\nCONTINUED TO OCTOBER 16 2026 (1/30)\n$134,622.69\n$13,462.27\n"
        entry = adapter._parse_entry(raw, "September 18, 2026", "h")
        assert "CONTINUED" in entry["status"]


# ─────────────────────────────────────────────────────────────────────────────
# CRAWLER SAFETY TESTS
# ─────────────────────────────────────────────────────────────────────────────

class TestCrawlerSafety:

    def test_robots_txt_respected_by_default(self, settings):
        assert settings.CRAWLER["RESPECT_ROBOTS_TXT"] is True

    def test_crawl_delay_configured(self, settings):
        assert settings.CRAWLER["CRAWL_DELAY_SECONDS"] >= 1

    def test_user_agent_identifies_bot(self, settings):
        ua = settings.CRAWLER["USER_AGENT"]
        assert "AuctionIntelBot" in ua
        assert "contact:" in ua

    def test_rate_limiter_enforces_delay(self):
        import time
        from apps.sources.base import RateLimiter
        url = "https://example.com/test"
        RateLimiter._last_request.clear()
        t0 = time.time()
        RateLimiter.wait(url)   # first call — no wait
        RateLimiter.wait(url)   # second call — must wait
        elapsed = time.time() - t0
        assert elapsed >= 1  # some delay enforced
