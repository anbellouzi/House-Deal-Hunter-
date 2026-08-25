The current max-bid engine returns UNKNOWN whenever ARV, repairs, or buyer premium are missing.

I do NOT want to solve this by inventing values.

Build a PROPERTY ENRICHMENT PIPELINE that attempts to obtain the missing inputs from legitimate public sources before declaring MAX BID = UNKNOWN.

Do not change the deterministic max-bid calculation.

==================================================
1. ENRICHMENT PIPELINE
==================================================

Create:

PropertyEnrichmentService

Pipeline:

Auction
↓
Property identification
↓
Parcel/OPA matching
↓
County property records
↓
Tax records
↓
Deed/history
↓
Comparable sales
↓
Rental comparables
↓
Property characteristics
↓
Repair estimate
↓
Auction terms
↓
Financial model
↓
Maximum bid

==================================================
2. DELAWARE COUNTY
==================================================

Use Delaware County's official public sources where available.

Use parcel/OPA as the primary identifier.

Do not rely exclusively on address matching.

Store:

source
source_url
retrieved_at
confidence

for every enriched field.

==================================================
3. ARV
==================================================

Do not require an official ARV field.

Calculate estimated market value using comparable sales.

Find comparable properties based on:

same ZIP
nearby geographic distance
property type
bedrooms
bathrooms
square footage
lot size
year built
recent sale date

Create:

low_value
base_value
high_value
confidence

Do not call the result an exact ARV unless the methodology supports it.

Use:

estimated_market_value

and:

estimated_arv

where appropriate.

Require a configurable minimum number of usable comps.

If insufficient comps:

ARV = UNKNOWN

==================================================
4. RENT
==================================================

Find rental comparables.

Calculate:

low_rent
base_rent
high_rent
confidence

Use nearby comparable properties.

Do not generate rental values from LLM guesses.

If insufficient rental data:

RENT = UNKNOWN

==================================================
5. REPAIRS
==================================================

Create a repair estimation engine.

Inputs:

property type
square footage
year built
condition indicators
photos if available
property description
known violations

Calculate:

low_repair
base_repair
high_repair

Store every assumption.

If property condition is unknown, increase uncertainty.

Never represent a modeled repair estimate as an inspection.

Use:

REPAIR ESTIMATE — VERIFY

==================================================
6. AUCTION COSTS
==================================================

Do not globally hard-code buyer premium.

Create:

AuctionTermsService

For each auction source determine:

buyer premium
deposit
transfer taxes
recording fees
closing costs
payment deadline
other required fees

Every value must have:

source
retrieved_at
confidence

If unknown:

do not automatically make the entire deal UNKNOWN.

Instead calculate:

MAX BID BEFORE UNKNOWN AUCTION COSTS

and display:

⚠️ AUCTION COSTS REQUIRE VERIFICATION

==================================================
7. DELAWARE COUNTY AUCTION TYPES
==================================================

IMPORTANT:

Do NOT treat all Delaware County auctions identically.

Create separate logic for:

SHERIFF SALE
UPSET SALE
JUDICIAL SALE
REPOSITORY SALE

For Upset Sales specifically account for:

unpaid taxes
costs
municipal liens
claims
surviving mortgages/liens

Do not assume the upset price represents total acquisition cost.

For Sheriff Sales, use the current official sale information and current Conditions of Sale.

==================================================
8. LIEN / TITLE RISK
==================================================

Create:

TitleRiskAnalysis

Possible statuses:

UNKNOWN
LOW
MEDIUM
HIGH
CRITICAL

Do not claim that a public search proves clear title.

Flag:

potential surviving liens
mortgages
municipal claims
tax claims
federal lien concerns
ownership issues
recent deeds
judgments where publicly discoverable

Display:

TITLE REVIEW REQUIRED

when necessary.

==================================================
9. CONFIDENCE
==================================================

Create:

EnrichmentConfidenceScore = 0–100

Inputs:

ARV confidence
rent confidence
repair confidence
tax confidence
auction-cost confidence
property-data confidence
title-risk confidence

Do not hide uncertainty.

==================================================
10. MAX BID STATES
==================================================

The max-bid engine should return:

A. CALCULATED

Enough information exists.

B. PARTIAL

Some important inputs are unknown, but a useful range can still be calculated.

C. UNKNOWN

Too many critical inputs are missing.

For PARTIAL, show:

Maximum bid before unknown costs

and list every missing input.

==================================================
11. BID RANGE
==================================================

Instead of one number, calculate:

Conservative Max Bid
Recommended Max Bid
Absolute Max Bid

Also calculate:

Low ARV / High Repairs
Base ARV / Base Repairs
High ARV / Low Repairs

Show a sensitivity matrix.

==================================================
12. EXAMPLE OUTPUT
==================================================

Property:

123 Main Street

Estimated ARV:
$225,000
Confidence: 84%

Rent:
$1,950/month
Confidence: 88%

Repairs:
$35,000
Confidence: 60%

Taxes:
$4,200/year
Confidence: 95%

Buyer premium:
UNKNOWN

Then show:

Recommended Max Bid:
$XX,XXX

Confidence:
XX/100

Status:

🟡 PARTIAL — AUCTION COST VERIFICATION REQUIRED

Missing:

❌ Buyer premium
❌ Title verification

Do NOT return simply:

MAX BID = UNKNOWN

unless the missing data actually makes the calculation mathematically unreliable.

==================================================
13. DATABASE
==================================================

Create models/tables for:

PropertySource
ComparableSale
RentalComparable
RepairEstimate
AuctionTerms
TitleRisk
EnrichmentRun

Each must preserve:

source
source_url
retrieved_at
confidence

==================================================
14. IMPORTANT
==================================================

The system must distinguish:

FACT
ESTIMATE
ASSUMPTION
UNKNOWN

Example:

FACT:
County tax record says taxes = $4,200.

ESTIMATE:
Comparable sales imply value = $225,000.

ASSUMPTION:
Repair contingency = 20%.

UNKNOWN:
Buyer premium not found.

Never mix these categories.

==================================================
15. FINAL DASHBOARD
==================================================

For each auction display:

Minimum Bid
Current Bid

Estimated Value
Estimated Rent
Repair Estimate

Total Estimated Cost

Conservative Max Bid
Recommended Max Bid
Absolute Max Bid

Bid Ceiling Gap

Confidence Score

Title Risk

BID / WATCH / INVESTIGATE / AVOID

And a section:

WHAT WE KNOW
WHAT WE ESTIMATE
WHAT WE DON'T KNOW
WHAT MUST BE VERIFIED BEFORE BIDDING

Implement this without rewriting the existing crawler architecture.
