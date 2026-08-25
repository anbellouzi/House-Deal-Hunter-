I want you to redesign and harden the MAXIMUM BID calculation in my auction investment application.

Do NOT use AI-generated guesses for the final maximum bid.

The maximum bid must be calculated deterministically from verified/estimated financial inputs, with every assumption visible.

==================================================
1. CORE PRINCIPLE
==================================================

The maximum bid is NOT:

ARV × arbitrary percentage

and it is NOT:

ARV − repairs

Instead, calculate the maximum amount I can pay while still meeting my investment requirements after ALL expected costs.

The system must calculate three values:

1. CONSERVATIVE MAX BID
2. RECOMMENDED MAX BID
3. ABSOLUTE MAX BID

==================================================
2. INPUTS
==================================================

The calculation should use:

PROPERTY VALUE

- Estimated current market value
- Estimated ARV
- Low ARV
- Base ARV
- High ARV

AUCTION

- Current bid
- Minimum/upset bid
- Buyer premium
- Deposit requirements
- Transfer taxes
- Recording fees
- Closing costs
- Legal/title costs
- Other auction-specific fees

RENOVATION

- Low repair estimate
- Base repair estimate
- High repair estimate
- Renovation contingency percentage

HOLDING

- Monthly property taxes
- Monthly insurance
- Utilities
- HOA
- Property management during renovation
- Expected renovation duration
- Expected selling/lease-up period

FINANCING

- Loan-to-value
- Interest rate
- Loan term
- Loan origination fees
- Points
- Financing costs

RENTAL

- Expected monthly rent
- Vacancy rate
- Property management %
- Maintenance %
- CapEx reserve %
- Property taxes
- Insurance
- HOA
- Other recurring expenses

FLIP

- ARV
- Selling commission
- Seller closing costs
- Transfer taxes
- Holding costs
- Financing costs
- Desired profit
- Required ROI

INVESTOR REQUIREMENTS

Make these configurable settings:

minimum rental cash flow
minimum cash-on-cash return
minimum flip profit
minimum flip ROI
maximum renovation budget
maximum total cash invested
minimum equity cushion
risk tolerance

==================================================
3. IMPORTANT DISTINCTION
==================================================

Separate:

BID PRICE

from:

TOTAL PROJECT COST

Example:

Winning bid:
$50,000

Buyer premium:
$750

Closing/title/legal:
$4,000

Renovation:
$30,000

Contingency:
$5,000

Holding:
$5,000

Total project cost:
$94,750

The algorithm must NEVER treat the $50,000 bid as the total investment.

==================================================
4. RENTAL MAXIMUM BID
==================================================

For a rental property, calculate the maximum bid based on BOTH:

A. Cash-flow requirement

AND

B. Required return/equity requirement

First calculate stabilized NOI.

Gross annual rent
− vacancy
− management
− maintenance
− CapEx
− property taxes
− insurance
− HOA
− other operating expenses
=
NOI

Then calculate annual debt service.

NOI
− annual debt service
=
Annual cash flow

Monthly cash flow:

Annual cash flow / 12

The property must satisfy my minimum monthly cash-flow requirement.

For example:

Minimum required cash flow = $200/month

The maximum bid is the highest bid at which:

Monthly cash flow >= $200

==================================================
5. RENTAL RETURN REQUIREMENT
==================================================

Also calculate:

Cash-on-Cash Return =
Annual pre-tax cash flow / Total Cash Invested

The property must satisfy:

Cash-on-Cash Return >= investor minimum

For example:

Minimum CoC return = 8%

Make the required return configurable.

The maximum bid must satisfy BOTH:

minimum monthly cash flow

AND

minimum cash-on-cash return

Whichever produces the LOWER maximum bid controls.

==================================================
6. FINANCING
==================================================

Do NOT assume the same financing is available for every auction.

Create financing scenarios:

Scenario A:
Cash purchase

Scenario B:
Conventional investment loan

Scenario C:
Other financing if explicitly provided

For each scenario calculate:

loan amount
down payment
interest
monthly principal + interest
loan fees
cash required

If financing is unknown or unavailable:

mark:

FINANCING UNKNOWN — VERIFY

Do not invent financing availability.

==================================================
7. FLIP MAXIMUM BID
==================================================

For a flip:

ARV
− selling costs
− transfer taxes
− holding costs
− financing costs
− renovation
− contingency
− required profit
=
MAXIMUM TOTAL ACQUISITION COST

Then:

Maximum Total Acquisition Cost
− non-purchase acquisition costs
=
MAXIMUM BID

Example:

ARV = $200,000

Selling costs = $16,000
Holding = $8,000
Financing = $6,000
Renovation = $35,000
Contingency = $7,000
Desired profit = $40,000

Maximum total acquisition cost:

$200,000
− $16,000
− $8,000
− $6,000
− $35,000
− $7,000
− $40,000
=
$88,000

Then subtract purchase-related costs that are separate from the bid to determine the maximum bid.

==================================================
8. TWO-WAY FLIP TEST
==================================================

Do NOT rely only on a desired-profit formula.

Also calculate required ROI.

For example:

Minimum flip ROI = 20%

ROI =
Net Profit / Total Cash Invested

The maximum bid must satisfy BOTH:

Required profit
AND
Required ROI

The lower maximum bid controls.

==================================================
9. CONSERVATIVE MAX BID
==================================================

Use:

Low ARV
High repair estimate
High contingency
Higher holding costs
Higher selling costs
Higher financing costs
Conservative rent
Higher vacancy
Higher operating expenses

This produces:

CONSERVATIVE MAX BID

This is the safest number.

==================================================
10. RECOMMENDED MAX BID
==================================================

Use:

Base ARV
Base repair estimate
Reasonable contingency
Expected holding costs
Expected financing costs
Expected rent

Then apply the investor's required return.

Produce:

RECOMMENDED MAX BID

This should be the primary number shown to the investor.

==================================================
11. ABSOLUTE MAX BID
==================================================

Use:

High ARV
Low/base repair estimate
Reasonable costs
But NEVER remove required contingency entirely.

Calculate the highest price that still barely satisfies the minimum investment criteria.

This is:

ABSOLUTE MAX BID

Display a strong warning:

⚠️ DO NOT EXCEED THIS BID

==================================================
12. AUCTION-SPECIFIC COSTS
==================================================

The calculation must support different counties and auction platforms.

Do NOT assume:

buyer premium = 1.5%

for every auction.

Instead:

buyer_premium = source-specific value

Likewise for:

deposit
transfer tax
recording fee
settlement deadline
legal fees
title costs

Every auction should have:

auction_cost_source

and:

auction_cost_confidence

==================================================
13. EQUITY CUSHION
==================================================

Calculate:

Equity Cushion =
Estimated Market Value
− Total Project Cost

Also calculate:

Equity Cushion % =
Equity Cushion / Estimated Market Value

For example:

Market Value = $180,000
Total Project Cost = $110,000

Equity = $70,000

Equity Cushion = 38.9%

Create configurable minimum equity cushion.

==================================================
14. ARV SAFETY TEST
==================================================

Do NOT use only the base ARV.

Calculate:

Low ARV scenario
Base ARV scenario
High ARV scenario

The recommended bid should remain reasonable under the low-ARV scenario.

If the deal only works using the high ARV:

FLAG:

🔴 DEAL DEPENDS ON HIGH ARV

==================================================
15. REPAIR SAFETY TEST
==================================================

Calculate:

Low repair scenario
Base repair scenario
High repair scenario

If the deal becomes unprofitable under the high repair scenario:

FLAG:

⚠️ REPAIR SENSITIVE

If the condition is unknown:

increase the contingency and lower the recommended maximum bid.

==================================================
16. BID WAR SIMULATION
==================================================

The application should show what happens if bidding increases.

For example:

Current bid: $20,000

Simulate:

$20K
$25K
$30K
$35K
$40K
$45K
$50K
$55K
$60K

For each bid show:

total project cost
monthly cash flow
cash-on-cash return
equity cushion
flip profit
flip ROI
deal score

Example:

BID       CASH FLOW    CoC       FLIP PROFIT
$20K      +$550        12.4%     $72K
$30K      +$475        10.1%     $62K
$40K      +$390         8.2%     $52K
$50K      +$300         6.5%     $42K
$60K      +$210         4.8%     $32K

This allows the investor to see exactly where the deal stops making sense.

==================================================
17. BID CEILING GAP
==================================================

Calculate:

Recommended Max Bid
− Current Bid

Example:

Current bid = $25,000
Recommended max = $52,000

Bid Ceiling Gap = $27,000

Display:

🔥 $27,000 OF BIDDING ROOM

But make clear:

This is NOT a prediction of the final bid.

It is simply the remaining amount before the investor's calculated ceiling.

==================================================
18. HARD STOP
==================================================

Create:

BID STATUS

Possible values:

🟢 BID
🟢 BID UP TO $X
🟡 WATCH
🟠 INVESTIGATE
🔴 DO NOT BID

The system should automatically return:

DO NOT BID

if:

- maximum bid <= current bid
- expected cash flow is below minimum
- required ROI is not met
- severe risk exists
- ARV confidence is too low
- repair uncertainty is extreme
- title/legal issue is unresolved
- auction terms are unclear

==================================================
19. UNKNOWN DATA
==================================================

This is extremely important.

If required inputs are UNKNOWN:

Do NOT assume $0.

Do NOT assume average values.

Do NOT generate a fake maximum bid.

Instead return:

MAX BID = UNKNOWN

and show exactly which inputs are missing.

Example:

MAX BID: UNKNOWN

Missing:

❌ ARV
❌ Repair estimate
❌ Property taxes
❌ Auction buyer premium

REQUIRES DUE DILIGENCE

The system may provide a RANGE only if enough information exists to construct a defensible range.

==================================================
20. CONFIDENCE SCORE
==================================================

Create:

MAX BID CONFIDENCE = 0–100

Based on:

property data completeness
ARV confidence
rent confidence
repair confidence
auction cost confidence
tax confidence
financing confidence
title/legal information

Example:

MAX BID: $52,000

Confidence: 78/100

==================================================
21. FINAL OUTPUT
==================================================

For every property display:

CURRENT BID
MINIMUM BID

CONSERVATIVE MAX BID
RECOMMENDED MAX BID
ABSOLUTE MAX BID

BID CEILING GAP

ESTIMATED ARV
ESTIMATED RENT
REPAIR ESTIMATE
TOTAL PROJECT COST

MONTHLY CASH FLOW
CASH-ON-CASH RETURN
CAP RATE

FLIP PROFIT
FLIP ROI

EQUITY CUSHION

MAX BID CONFIDENCE

RISK SCORE

BID STATUS

==================================================
22. EXAMPLE
==================================================

Create a test property:

ARV = $200,000
Expected rent = $2,000/month
Repairs = $30,000
Contingency = 20%
Taxes = $3,600/year
Insurance = $1,500/year
HOA = $0
Vacancy = 5%
Management = 8%
Maintenance = 5%
CapEx = 5%

Financing:

25% down
7.5% interest
30-year term

Investor requirements:

Minimum cash flow = $200/month
Minimum CoC = 8%

Run the complete calculation.

Show the formulas and intermediate calculations.

==================================================
23. IMPLEMENTATION REQUIREMENT
==================================================

Put the deterministic calculations into Python.

Create a dedicated service such as:

auction_intel/services/max_bid.py

Use typed functions/classes.

Example:

calculate_rental_max_bid()

calculate_flip_max_bid()

calculate_conservative_max_bid()

calculate_recommended_max_bid()

calculate_absolute_max_bid()

calculate_equity_cushion()

calculate_bid_ceiling_gap()

calculate_max_bid_confidence()

Do NOT allow Claude/LLM output to directly determine these numbers.

Claude may explain the result, identify risks, and summarize the deal, but Python must calculate the financial values.

==================================================
24. TESTING
==================================================

Create comprehensive unit tests.

Test:

- Increasing bid decreases cash flow
- Increasing repairs decreases max bid
- Increasing ARV increases max bid
- Increasing rent increases rental max bid
- Increasing interest rate decreases max bid
- Increasing taxes decreases max bid
- Increasing vacancy decreases max bid
- Buyer premium is included
- Closing costs are included
- Contingency is included
- Required ROI is enforced
- Minimum cash flow is enforced
- Low ARV scenario works
- High repair scenario works
- Unknown inputs return UNKNOWN
- Current bid above max bid returns DO NOT BID
- Recommended max bid never exceeds absolute max bid

Also test that auction-specific buyer premiums and costs are never globally hard-coded.

==================================================
FINAL DELIVERABLE
==================================================

Review my existing implementation.

Do NOT rebuild unrelated parts.

Implement the maximum-bid engine.

Then show me one complete worked example using the test property above.

Show:

1. Formula
2. Inputs
3. Intermediate calculations
4. Conservative max bid
5. Recommended max bid
6. Absolute max bid
7. Rental analysis
8. Flip analysis
9. Bid ceiling gap
10. Confidence
11. Final BID/WATCH/DO NOT BID result

The final maximum bid must be mathematically reproducible from the displayed inputs.
