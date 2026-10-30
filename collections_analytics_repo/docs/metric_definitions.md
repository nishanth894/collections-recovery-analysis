# Metric definitions (golden layer)

All metrics: IST calendar month, window 2026-01-01 → 2026-08-08, August excluded from MoM (8 days). Money in ₹. Ratios compared in **percentage points (pp)**, money in **% change** *and* **per observed day**.
Source of each: `sql/05_metrics.sql` (`metrics_monthly`). "Naive" = how a stack over raw tables would compute it (`rep_*` columns).

| Metric | Numerator | Denominator | Eligibility | Window | Why this definition |
|---|---|---|---|---|---|
| **Net recovery (₹)** | Σ `amount` of payments with `payment_status='SUCCESS'`, de-duplicated on `payment_id` | – | Account `dpd ≥ 1` (delinquent); in window | IST month of `event_ts_ist` | Raw sums count duplicates (+1.9%), non-settled rows (FAILED/PENDING/REVERSED, ≈29% of raw ₹) and regular EMIs on current accounts |
| **Net recovery per day** | Net recovery | Observed days in month (28/31/30…) | same | month | Removes the calendar: (1+MoM total) = (days ratio)·(1+MoM per day) |
| **Recovery rate (%)** | Net recovery | Σ `outstanding_amount` of **all** delinquent accounts (fixed base; numerator and denominator on the same population) | `dpd ≥ 1` | month | Variants stored: targeted base, worked base, as-of-eligible base (consistent numerator). `rep_recovery_rate_mismatched_denominator_pct` shows the trap: all payments ÷ shrinking eligible base |
| **Recovery per account** | Net recovery | (a) delinquent accounts in base, (b) accounts worked that month | `dpd ≥ 1` | month | (a) comparable over time, (b) intensity-adjusted; both shown |
| **Contact rate (call)** | Answered outbound calls | Outbound calls | de-duplicated on `call_id`; in window | month | `call_status='ANSWERED'` only; duration ignored (unrelated to status) |
| **Contact rate (account)** — *primary* | Accounts with ≥1 answered outbound call | Accounts with ≥1 outbound call | same | month | Robust to dialer retry volume (predictive dialers inflate attempts) |
| **RPC rate** | Dispositions that reached the borrower (all codes except `NO_CONTACT`, `WRONG_NUMBER`) | All dispositions | in window | month | Disposition table analysed standalone: `call_id` link to calls is invalid (account agrees in ≈0% of rows) |
| **PTP rate** | Dispositions `PTP` ∪ `PROMISE_TO_PAY` (canonical) | RPC dispositions | in window | month of disposition | Alias merge; legacy-code-only gives ≈ half |
| **PTP kept rate (status)** | PTPs with status `KEPT` | `KEPT + BROKEN` (resolved) | by PTP creation month | cohort | Excludes `OPEN` (4,128 stale past-due) and `CANCELLED`; naive `KEPT/all` is ≈24% |
| **PTP kept rate (payment-verified)** | Matured PTPs with a SUCCESS payment on the account between PTP time and promised date + 3 days | Matured PTPs (`promised_date ≤ cut-off`) | all statuses | cohort | Cross-checks the status field against money (≈4% → status not corroborated) |
| **Recovery per agent-hour** | Net recovery | Σ `session_hours` (all channels) of `agent_sessions` in login month | – | month | Payments cannot be attributed to individual agents (attribution = chance) so total-level; voice-only hours also stored |
| **Cost per ₹ recovered** | – | – | – | – | **Not computable: no cost data.** Proxies: `agent_hours_per_lakh_recovered`, `outbound_calls_per_lakh_recovered` |
| **Channel conversion (7-day)** | Touches followed by a recovery payment on the same account within 7 days | Touches of that channel | contact touches: answered outbound call / non-failed WhatsApp-SMS event / field visit | window | Reported with a **placebo baseline** (touch date randomised): lift = observed ÷ placebo |

**Percentage change vs percentage-point change.** Contact 22.35% → 23.63% is **+1.28 pp** (+5.7% relative). Never quote the relative change of a ratio next to a pp change.
