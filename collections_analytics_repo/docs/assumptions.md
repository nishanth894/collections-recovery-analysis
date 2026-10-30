# Source-of-truth decisions, assumptions, exclusions

| ID | Decision / assumption | Evidence | Sensitivity tested |
|---|---|---|---|
| A-01 | `account_id` is the only join key | 100% of event `account_id`s exist in `accounts`; `borrower_id` on events matches `accounts.borrower_id` in ≈0% of rows; `call_id` links agree on account in ≈0% | n/a |
| A-02 | Accounts table is a single snapshot (static DPD/outstanding/status); `dpd≥1` defines "collectible" | no as-of DPD exists | recovery incl. dpd=0 shown in waterfall (₹11.8 Cr) |
| A-03 | Timestamps: tables with a `timezone` column (calls, sessions) converted with it; **all others assumed IST**; month = IST month | no tz column elsewhere | 3 payment-tz variants: Feb→Mar per-day change stays within ±0.2% |
| A-04 | Duplicate payment = same `payment_id` (500 groups). Same `payment_reference` is **not** a duplicate | 0 cases of same ref+account+amount under distinct ids | – |
| A-05 | Calls: duplicate `call_id` → keep earliest UTC timestamp, merge non-null `agent_id` (68 null-agent variants, 11 late re-ingests with +24..120h shifts) | – | – |
| A-06 | Recovery = SUCCESS only; PENDING/FAILED/REVERSED excluded | status semantics assumed | raw SUCCESS-only series reproduces +11% |
| A-07 | Borrowers: latest chronologically-valid version; PII not carried into golden | 11,015 ids in 30,600 rows with conflicting attributes | geography low-reliability (10% unmatched) |
| A-08 | Agents: `agent_id` canonical; latest snapshot attributes; earliest `joined_at` = tenure | employee_code merge collapses to 1 component | tenure analysis = Hypothesis |
| A-09 | Disposition `PROMISE_TO_PAY` ≡ `PTP`; RPC = any code except NO_CONTACT/WRONG_NUMBER | – | PTP rate with/without alias reported |
| A-10 | Calls to dpd=0 accounts excluded from call→payment outcome analysis | recovery excludes dpd=0 by construction (otherwise spurious DPD effect) | caught during analysis |
| A-11 | Observation cut-off 2026-08-08 23:59:59 IST; 5 calls outside window flagged and excluded | max timestamps of other tables | – |
| A-12 | Attribution window 7 days (default); 1/3/7/14/30 tested with placebo | – | Section B |
| A-13 | Benefit of incremental recovery counted at 100% of ₹ (gross); 50%/25% capture shown | fee/margin structure not supplied | scenarios |
| A-14 | ₹10 Cr treated as all-in cost; no opex/implementation cost invented | no cost data | break-even stated per capture rate |

**Exclusions** (all logged in `rejects` / flags, never silently dropped): duplicate payment rows (500), duplicate/re-ingested call rows (1,350), duplicate WhatsApp events (600), superseded borrower versions (19,585) and agent snapshots (29,000); recovery excludes non-settled, out-of-window and dpd=0 payments.
