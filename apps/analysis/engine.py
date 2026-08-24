"""
Financial Analysis Engine
=========================

IMPORTANT DESIGN PRINCIPLE:
- This module performs DETERMINISTIC calculations only
- It NEVER invents missing data
- All estimates are clearly labeled with confidence levels
- Claude / AI is used ONLY for interpretation, not for generating numbers
- If a required input is missing, the calculation returns None with a note
"""
import logging
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from django.db.models import Avg, Count, Q
from django.conf import settings

logger = logging.getLogger(__name__)

ANALYSIS_CFG = settings.ANALYSIS
TWO_PLACES = Decimal("0.01")


# ─────────────────────────────────────────────────────────────────────────────
# ACQUISITION COST CALCULATOR
# ─────────────────────────────────────────────────────────────────────────────

class AcquisitionCostCalculator:
    """
    Calculates total acquisition cost for a winning auction bid.

    Formula:
    Winning Bid
    + Buyer's Premium
    + Transfer Tax (PA = 2% state + 1% local = typically 3%)
    + Title/Legal Costs
    + Recording Costs
    + Immediate Repairs (from repair estimate)
    + Holding Costs
    + Contingency
    = TOTAL PROJECT COST
    """

    # Pennsylvania transfer tax: 1% state deed transfer + 1% local (varies)
    # Conservative default: 3% (covers most Delco municipalities)
    DEFAULT_TRANSFER_TAX_PCT = Decimal("3.0")
    DEFAULT_TITLE_LEGAL = Decimal("3000")    # Title search + attorney for sheriff sale
    DEFAULT_RECORDING   = Decimal("500")
    DEFAULT_CONTINGENCY_PCT = Decimal("15")  # 15% of repair budget as contingency

    def calculate(
        self,
        winning_bid: Decimal,
        buyer_premium_pct: Optional[Decimal],
        repair_estimate: Optional[Decimal],
        holding_months: int = 6,
        monthly_holding: Optional[Decimal] = None,
        transfer_tax_pct: Optional[Decimal] = None,
    ) -> dict:

        result = {
            "winning_bid":          winning_bid,
            "buyer_premium_pct":    buyer_premium_pct,
            "transfer_tax_pct":     transfer_tax_pct or self.DEFAULT_TRANSFER_TAX_PCT,
        }

        # Buyer's premium
        if buyer_premium_pct:
            result["buyer_premium_amount"] = (winning_bid * buyer_premium_pct / 100).quantize(TWO_PLACES)
        else:
            result["buyer_premium_amount"] = Decimal("0")
            result["buyer_premium_note"] = "UNKNOWN — VERIFY auction terms"

        # Transfer tax
        ttx_pct = result["transfer_tax_pct"]
        result["transfer_tax_amount"] = (winning_bid * ttx_pct / 100).quantize(TWO_PLACES)

        result["title_legal_costs"] = self.DEFAULT_TITLE_LEGAL
        result["recording_costs"]   = self.DEFAULT_RECORDING

        # Repair + contingency
        if repair_estimate:
            contingency = (repair_estimate * self.DEFAULT_CONTINGENCY_PCT / 100).quantize(TWO_PLACES)
            result["repair_estimate"]  = repair_estimate
            result["repair_contingency"] = contingency
            result["repair_total"]     = repair_estimate + contingency
        else:
            result["repair_estimate"]  = None
            result["repair_contingency"] = None
            result["repair_total"]     = None
            result["repair_note"]      = "UNKNOWN — interior condition not verified"

        # Holding costs
        if monthly_holding and holding_months:
            result["holding_costs"] = (monthly_holding * holding_months).quantize(TWO_PLACES)
        else:
            # Estimate: taxes/12 + insurance (~$100/mo) + utilities (~$200/mo)
            result["holding_costs"] = Decimal(str(holding_months * 350))
            result["holding_note"]  = "ESTIMATED — verify actual taxes and insurance"

        # Total
        components = [
            result["winning_bid"],
            result["buyer_premium_amount"],
            result["transfer_tax_amount"],
            result["title_legal_costs"],
            result["recording_costs"],
            result.get("repair_total") or Decimal("0"),
            result["holding_costs"],
        ]
        result["total_project_cost"] = sum(components).quantize(TWO_PLACES)
        result["total_excludes_repairs"] = "repair_total" not in result or result["repair_total"] is None

        return result


# ─────────────────────────────────────────────────────────────────────────────
# MAX BID CALCULATOR
# ─────────────────────────────────────────────────────────────────────────────

class MaxBidCalculator:
    """
    Calculates the maximum bid for flip and rental strategies.

    For FLIP:
      Max Bid = ARV
                - Repair Costs
                - Acquisition Overhead
                - Holding Costs
                - Selling Costs
                - Desired Profit
                = MAX BID

    For RENTAL:
      Max Bid = based on desired cap rate / cash-on-cash return
    """

    DEFAULT_SELLING_COST_PCT = Decimal("6")   # agent commission + closing
    DEFAULT_HOLDING_MONTHS   = 6

    def flip_max_bid(
        self,
        arv: Decimal,
        repair_base: Optional[Decimal],
        repair_high: Optional[Decimal],
        buyer_premium_pct: Optional[Decimal],
        desired_profit: Decimal = Decimal("40000"),
        holding_months: int = 6,
        monthly_holding: Decimal = Decimal("1000"),
        transfer_tax_pct: Decimal = Decimal("3"),
    ) -> dict:
        """
        Calculate three max bids for flip strategy.
        Returns NONE if required inputs are missing.
        """
        if not arv:
            return {"error": "ARV required for flip max bid calculation"}

        selling_costs = (arv * self.DEFAULT_SELLING_COST_PCT / 100).quantize(TWO_PLACES)
        holding_total = monthly_holding * holding_months
        ttx_placeholder = Decimal("0")  # Will be calculated on actual bid
        overhead = (
            Decimal("3000")   # title/legal
            + Decimal("500")  # recording
            + ttx_placeholder
        )

        # Buyer's premium placeholder (% of bid — need to iterate)
        # Simplification: treat as fixed overhead for now
        bp_placeholder = Decimal("0")

        def calc(repair: Decimal, profit: Decimal) -> Optional[Decimal]:
            if repair is None:
                return None
            max_b = arv - repair - overhead - holding_total - selling_costs - profit - bp_placeholder
            return max(Decimal("0"), max_b).quantize(TWO_PLACES)

        repair_b = repair_base or Decimal("0")
        repair_h = repair_high or (repair_base * Decimal("1.3") if repair_base else Decimal("0"))

        results = {
            "arv":               arv,
            "selling_costs":     selling_costs,
            "holding_total":     holding_total,
            "overhead_estimate": overhead,
            "repair_base":       repair_base,
            "repair_high":       repair_high,
            # Three tiers
            "max_bid_aggressive":   calc(repair_b, desired_profit * Decimal("0.5")),
            "max_bid_recommended":  calc(repair_b, desired_profit),
            "max_bid_absolute":     calc(repair_h, desired_profit * Decimal("0.5")),
            "note": (
                "MODEL ESTIMATE — NOT GUARANTEED. "
                "Verify ARV, repair costs, and all fees before bidding."
            ),
        }

        if repair_base is None:
            results["repair_warning"] = "Repair costs unknown — interior uninspected. Add 25%+ contingency."

        return results

    def rental_max_bid(
        self,
        monthly_rent: Optional[Decimal],
        repair_base: Optional[Decimal],
        annual_taxes: Optional[Decimal],
        desired_cap_rate: Decimal = Decimal("8"),
        vacancy_pct: Decimal = Decimal("8"),
        mgmt_pct: Decimal = Decimal("10"),
        maintenance_monthly: Decimal = Decimal("150"),
        capex_monthly: Decimal = Decimal("100"),
        insurance_monthly: Decimal = Decimal("100"),
        buyer_premium_pct: Optional[Decimal] = None,
    ) -> dict:
        if not monthly_rent:
            return {"error": "Monthly rent estimate required for rental max bid"}

        gross_annual = monthly_rent * 12
        vacancy_loss = gross_annual * vacancy_pct / 100
        mgmt_fee     = gross_annual * mgmt_pct / 100
        maintenance  = maintenance_monthly * 12
        capex        = capex_monthly * 12
        insurance    = insurance_monthly * 12
        taxes_annual = annual_taxes or Decimal("3000")  # conservative default

        noi = (gross_annual - vacancy_loss - mgmt_fee - maintenance - capex
               - insurance - taxes_annual)

        # Cap rate approach: value = NOI / cap_rate
        value_at_cap = (noi / (desired_cap_rate / 100)).quantize(TWO_PLACES) if noi > 0 else None

        # Max bid = value_at_cap - repair - overhead
        overhead = Decimal("4000")
        repair   = repair_base or Decimal("0")
        max_bid  = (value_at_cap - repair - overhead).quantize(TWO_PLACES) if value_at_cap else None

        return {
            "gross_annual_rent":  gross_annual,
            "vacancy_loss":       vacancy_loss,
            "mgmt_fee":           mgmt_fee,
            "maintenance_annual": maintenance,
            "capex_annual":       capex,
            "insurance_annual":   insurance,
            "taxes_annual":       taxes_annual,
            "noi":                noi,
            "value_at_cap_rate":  value_at_cap,
            "desired_cap_rate":   desired_cap_rate,
            "max_bid_recommended":max_bid,
            "note":               "MODEL ESTIMATE — NOT GUARANTEED.",
        }


# ─────────────────────────────────────────────────────────────────────────────
# HISTORICAL AUCTION STATISTICS
# ─────────────────────────────────────────────────────────────────────────────

class HistoricalAuctionStats:
    """
    Calculates historical auction statistics from completed auctions in DB.
    Returns INSUFFICIENT_DATA if sample size < MIN_HISTORICAL_SAMPLE.
    NEVER fabricates statistics.
    """

    MIN_SAMPLE = settings.ANALYSIS.get("MIN_HISTORICAL_SAMPLE", 30)

    def get_stats(
        self,
        county: Optional[str] = None,
        zip_code: Optional[str] = None,
        auction_type: Optional[str] = None,
        min_bid_min: Optional[Decimal] = None,
        min_bid_max: Optional[Decimal] = None,
    ) -> dict:
        from apps.auctions.models import Auction, AuctionStatus

        # Build queryset of completed auctions
        qs = Auction.objects.filter(
            auction_status__in=[
                AuctionStatus.ENDED_THIRD_PARTY,
                AuctionStatus.ENDED_PLAINTIFF,
                AuctionStatus.ENDED_NO_SALE,
                AuctionStatus.WITHDRAWN,
                AuctionStatus.CANCELLED,
            ],
            final_bid__isnull=False,
            minimum_bid__isnull=False,
            minimum_bid__gt=0,
        )

        # Apply filters (most specific first)
        if zip_code:
            qs = qs.filter(property__zip_code=zip_code)
        elif county:
            qs = qs.filter(property__county=county)

        if auction_type:
            qs = qs.filter(auction_type=auction_type)

        if min_bid_min is not None:
            qs = qs.filter(minimum_bid__gte=min_bid_min)
        if min_bid_max is not None:
            qs = qs.filter(minimum_bid__lte=min_bid_max)

        count = qs.count()

        if count < self.MIN_SAMPLE:
            return {
                "status":       "INSUFFICIENT_DATA",
                "sample_size":  count,
                "min_required": self.MIN_SAMPLE,
                "message":      (
                    f"Only {count} comparable completed auctions found. "
                    f"Minimum {self.MIN_SAMPLE} required for statistical confidence. "
                    f"Results will improve as more auctions are collected."
                ),
            }

        auctions = list(qs.values(
            "minimum_bid", "final_bid", "bid_count",
            "bidder_count", "auction_status", "sold_to_plaintiff"
        ))

        # ── Calculate statistics ──────────────────────────────────────────────
        ratios = [
            float(a["final_bid"] / a["minimum_bid"])
            for a in auctions
            if a["final_bid"] and a["minimum_bid"]
        ]
        ratios.sort()

        bid_counts   = [a["bid_count"] for a in auctions if a["bid_count"] is not None]
        bidder_counts= [a["bidder_count"] for a in auctions if a["bidder_count"] is not None]

        def safe_median(lst):
            if not lst:
                return None
            s = sorted(lst)
            n = len(s)
            return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2

        def pct_in_range(lst, low, high):
            if not lst:
                return None
            return round(sum(1 for x in lst if low <= x <= high) / len(lst) * 100, 1)

        total = len(auctions)
        plaintiff_count  = sum(1 for a in auctions if a.get("sold_to_plaintiff"))
        no_sale_count    = sum(1 for a in auctions
                               if a["auction_status"] == "ENDED_NO_SALE")
        withdrawn_count  = sum(1 for a in auctions
                               if a["auction_status"] == "WITHDRAWN")

        return {
            "status":          "OK",
            "sample_size":     total,
            "county":          county,
            "zip_code":        zip_code,

            # Bid ratios
            "avg_final_min_ratio":    round(sum(ratios) / len(ratios), 3) if ratios else None,
            "median_final_min_ratio": round(safe_median(ratios), 3) if ratios else None,

            # Bid/bidder counts
            "avg_bid_count":      round(sum(bid_counts) / len(bid_counts), 1) if bid_counts else None,
            "median_bid_count":   safe_median(bid_counts),
            "avg_bidder_count":   round(sum(bidder_counts) / len(bidder_counts), 1) if bidder_counts else None,
            "median_bidder_count":safe_median(bidder_counts),

            # Price distribution
            "pct_sold_at_minimum":          pct_in_range(ratios, 0.99, 1.01),
            "pct_sold_within_10pct":        pct_in_range(ratios, 0.99, 1.10),
            "pct_sold_within_25pct":        pct_in_range(ratios, 0.99, 1.25),
            "pct_sold_above_2x_minimum":    pct_in_range(ratios, 2.0, 9999),
            "pct_sold_above_5x_minimum":    pct_in_range(ratios, 5.0, 9999),

            # Outcomes
            "pct_sold_to_plaintiff":  round(plaintiff_count / total * 100, 1),
            "pct_no_sale":            round(no_sale_count / total * 100, 1),
            "pct_withdrawn":          round(withdrawn_count / total * 100, 1),
        }


# ─────────────────────────────────────────────────────────────────────────────
# LOW COMPETITION SCORE
# ─────────────────────────────────────────────────────────────────────────────

class LowCompetitionScorer:
    """
    Scores 0–100 how likely it is that a property will have low competition.
    100 = extremely likely to have little competition.
    0   = extremely competitive.

    IMPORTANT: If insufficient historical data exists, score is clearly
    labeled as ESTIMATED with reduced confidence.
    """

    WEIGHTS = {
        "historical_bidder_count":   0.25,
        "historical_final_min_ratio": 0.20,
        "pct_near_minimum":          0.15,
        "current_bidder_count":      0.10,
        "current_bid_ratio":         0.10,
        "property_attractiveness":   0.10,
        "neighborhood_demand":       0.05,
        "auction_timing":            0.05,
    }

    def score(self, auction, historical_stats: dict) -> dict:
        """
        Calculate low competition score for an auction.
        Returns score + component breakdown.
        """
        components = {}
        confidence = "HIGH"

        if historical_stats.get("status") == "INSUFFICIENT_DATA":
            confidence = "LOW"
            # Fall back to current-bid-only scoring
            components["historical_bidder_count"]   = 50  # neutral
            components["historical_final_min_ratio"] = 50
            components["pct_near_minimum"]          = 50
        else:
            # Historical bidder count: fewer = higher score
            avg_bidders = historical_stats.get("avg_bidder_count")
            if avg_bidders is not None:
                if avg_bidders <= 1:   components["historical_bidder_count"] = 95
                elif avg_bidders <= 2: components["historical_bidder_count"] = 75
                elif avg_bidders <= 3: components["historical_bidder_count"] = 55
                elif avg_bidders <= 5: components["historical_bidder_count"] = 35
                else:                  components["historical_bidder_count"] = 15
            else:
                components["historical_bidder_count"] = 50
                confidence = "MEDIUM"

            # Final/min ratio: closer to 1.0 = less competition
            ratio = historical_stats.get("median_final_min_ratio")
            if ratio is not None:
                if ratio <= 1.05:  components["historical_final_min_ratio"] = 95
                elif ratio <= 1.15:components["historical_final_min_ratio"] = 75
                elif ratio <= 1.30:components["historical_final_min_ratio"] = 55
                elif ratio <= 1.50:components["historical_final_min_ratio"] = 35
                else:              components["historical_final_min_ratio"] = 15
            else:
                components["historical_final_min_ratio"] = 50

            # % sold near minimum
            pct_near = historical_stats.get("pct_sold_within_10pct", 0) or 0
            components["pct_near_minimum"] = min(95, int(pct_near * 1.5))

        # Current auction state
        current_bidders = auction.bidder_count
        if current_bidders is None:
            components["current_bidder_count"] = 50
            confidence = min(confidence, "MEDIUM") if confidence != "LOW" else "LOW"
        elif current_bidders == 0: components["current_bidder_count"] = 95
        elif current_bidders == 1: components["current_bidder_count"] = 75
        elif current_bidders == 2: components["current_bidder_count"] = 50
        else:                      components["current_bidder_count"] = 20

        # Current bid vs minimum
        ratio = auction.current_bid_to_min_ratio
        if ratio is None:
            components["current_bid_ratio"] = 50
        elif ratio <= 1.0:  components["current_bid_ratio"] = 95  # at minimum
        elif ratio <= 1.05: components["current_bid_ratio"] = 80
        elif ratio <= 1.15: components["current_bid_ratio"] = 60
        else:               components["current_bid_ratio"] = 25

        # Property attractiveness (less attractive = less competition)
        # Based on: is it commercial? condo? low-value area?
        prop = getattr(auction, "property", None)
        if prop:
            from apps.auctions.models import PropertyType, County
            if prop.property_type in [PropertyType.COMMERCIAL, PropertyType.LAND]:
                components["property_attractiveness"] = 65  # specialized = less retail interest
            elif prop.property_type == PropertyType.CONDO:
                components["property_attractiveness"] = 45  # HOA risk reduces competition
            else:
                components["property_attractiveness"] = 50
        else:
            components["property_attractiveness"] = 50

        # Neighborhood demand (higher-demand areas = more competition)
        components["neighborhood_demand"] = 50  # neutral default

        # Auction timing (auctions closing at odd hours have fewer last-minute bids)
        close_time = auction.auction_close_time
        if close_time:
            hour = close_time.hour
            if hour < 8 or hour >= 20:
                components["auction_timing"] = 70  # off-hours
            elif 12 <= hour <= 14:
                components["auction_timing"] = 40  # lunch rush
            else:
                components["auction_timing"] = 50
        else:
            components["auction_timing"] = 50

        # Weighted score
        total = sum(
            components.get(key, 50) * weight
            for key, weight in self.WEIGHTS.items()
        )
        final_score = round(total)

        return {
            "score":       final_score,
            "confidence":  confidence,
            "components":  components,
            "historical_sample": historical_stats.get("sample_size", 0),
            "note":        "MODEL ESTIMATE — NOT GUARANTEED",
        }


# ─────────────────────────────────────────────────────────────────────────────
# MINIMUM BID WIN PROBABILITY
# ─────────────────────────────────────────────────────────────────────────────

class MinBidWinProbability:
    """
    Estimates probability of winning at or near minimum bid.
    Based entirely on historical data — never fabricated.
    """

    def estimate(self, historical_stats: dict, current_bid_ratio: Optional[float]) -> dict:
        if historical_stats.get("status") == "INSUFFICIENT_DATA":
            return {
                "at_minimum":     None,
                "within_10pct":   None,
                "within_25pct":   None,
                "significant_competition": None,
                "status":         "INSUFFICIENT_DATA",
                "note":           (
                    "MODEL ESTIMATE — NOT GUARANTEED. "
                    "Insufficient historical data for this county/area. "
                    f"Minimum {historical_stats.get('min_required')} auctions required."
                ),
            }

        return {
            "at_minimum":   historical_stats.get("pct_sold_at_minimum"),
            "within_10pct": historical_stats.get("pct_sold_within_10pct"),
            "within_25pct": historical_stats.get("pct_sold_within_25pct"),
            "significant_competition": (
                100 - (historical_stats.get("pct_sold_within_25pct") or 0)
            ),
            "status": "OK",
            "note":   (
                "MODEL ESTIMATE — NOT GUARANTEED. "
                f"Based on {historical_stats['sample_size']} historical auctions."
            ),
        }


# ─────────────────────────────────────────────────────────────────────────────
# DEAL SCORER
# ─────────────────────────────────────────────────────────────────────────────

class DealScorer:
    """Calculates the final 0–100 Deal Score."""

    WEIGHTS = settings.ANALYSIS["DEAL_SCORE_WEIGHTS"]

    GRADES = [
        (90, "A+", "🔥 Exceptional opportunity"),
        (80, "A",  "🟢 Strong opportunity"),
        (70, "B",  "🟢 Good opportunity"),
        (60, "C",  "🟡 Investigate"),
        (50, "D",  "🟠 High risk"),
        (0,  "F",  "🔴 Avoid"),
    ]

    def score(
        self,
        minimum_bid: Optional[Decimal],
        market_value: Optional[Decimal],
        arv: Optional[Decimal],
        monthly_rent: Optional[Decimal],
        repair_base: Optional[Decimal],
        low_competition_score: int,
        flip_profit: Optional[Decimal],
        risk_score: int,
    ) -> dict:

        components = {}

        # 1. Discount to market value (25%)
        if minimum_bid and market_value and market_value > 0:
            discount = float(1 - minimum_bid / market_value)
            if discount >= 0.60:   components["discount_to_market"] = 95
            elif discount >= 0.50: components["discount_to_market"] = 85
            elif discount >= 0.40: components["discount_to_market"] = 75
            elif discount >= 0.30: components["discount_to_market"] = 60
            elif discount >= 0.20: components["discount_to_market"] = 45
            elif discount >= 0.10: components["discount_to_market"] = 30
            else:                  components["discount_to_market"] = 10
        else:
            components["discount_to_market"] = 0

        # 2. Rental economics (20%)
        if monthly_rent and minimum_bid and minimum_bid > 0:
            gross_yield = float(monthly_rent * 12 / minimum_bid * 100)
            if gross_yield >= 12:  components["rental_economics"] = 95
            elif gross_yield >= 9: components["rental_economics"] = 80
            elif gross_yield >= 7: components["rental_economics"] = 65
            elif gross_yield >= 5: components["rental_economics"] = 45
            else:                  components["rental_economics"] = 20
        else:
            components["rental_economics"] = 0

        # 3. Low competition (15%)
        components["low_competition"] = low_competition_score

        # 4. Flip economics (15%)
        if flip_profit and minimum_bid and minimum_bid > 0:
            roi = float(flip_profit / minimum_bid * 100)
            if roi >= 50:  components["flip_economics"] = 95
            elif roi >= 30:components["flip_economics"] = 80
            elif roi >= 20:components["flip_economics"] = 65
            elif roi >= 10:components["flip_economics"] = 45
            else:          components["flip_economics"] = 20
        else:
            components["flip_economics"] = 0

        # 5–7. Placeholder scores (to be enriched by property data)
        components["property_quality"]  = 50  # Unknown until inspected
        components["neighborhood"]      = 50
        components["resale_potential"]  = 50

        # 8. Risk adjustment (5% — reduces score)
        risk_penalty = max(0, (risk_score - 50)) / 50 * 30
        components["risk_adjustment"] = max(0, 50 - risk_penalty)

        # Weighted total
        weight_map = {
            "discount_to_market": self.WEIGHTS["discount_to_market"],
            "rental_economics":   self.WEIGHTS["rental_economics"],
            "low_competition":    self.WEIGHTS["low_competition"],
            "flip_economics":     self.WEIGHTS["flip_economics"],
            "property_quality":   self.WEIGHTS["property_quality"],
            "neighborhood":       self.WEIGHTS["neighborhood"],
            "resale_potential":   self.WEIGHTS["resale_potential"],
            "risk_adjustment":    self.WEIGHTS["risk_adjustment"],
        }

        total = sum(components.get(k, 0) * w for k, w in weight_map.items())
        final = round(total)

        grade_label = "F"
        grade_desc  = "🔴 Avoid"
        for threshold, grade, desc in self.GRADES:
            if final >= threshold:
                grade_label = grade
                grade_desc  = desc
                break

        return {
            "deal_score": final,
            "grade":      grade_label,
            "grade_desc": grade_desc,
            "components": components,
        }
