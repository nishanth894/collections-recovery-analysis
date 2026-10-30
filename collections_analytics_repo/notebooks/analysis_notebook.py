# %% [markdown]
# # Collections recovery — is "+11% MoM" real?
# **Reproducible analysis notebook.** Every number is computed from the SQL golden layer (`data/db/collections.sqlite`) by the tested
# functions in `src/analysis.py`; this notebook shows the reasoning and the evidence in the order a reviewer would ask for it.
# Run `make all` first (or `python -m src.run_pipeline`).
#
# **Classification used throughout:** *Fact* = arithmetic identity/ count reproducible from data · *Strong evidence* = large, robust, survives multiple-testing & sensitivity checks ·
# *Correlation* = association without causal design · *Hypothesis* = plausible but not testable with this data.

# %%
import os, sys, pickle, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.abspath(".."))
import numpy as np, pandas as pd, matplotlib.pyplot as plt
from IPython.display import display
pd.set_option("display.width", 200); pd.set_option("display.max_columns", 30); pd.set_option("display.float_format", lambda v: f"{v:,.3f}")
from src import analysis as A
from src.config import REPORTS_DIR
R = pickle.load(open(REPORTS_DIR / ".results.pkl", "rb")) if (REPORTS_DIR / ".results.pkl").exists() else A.run_all()
CR = 1e7
print("loaded results:", len(R), "objects")

# %% [markdown]
# ## 1. What does the data actually cover?
# The brief promises ~12 months. Check coverage before anything else.

# %%
con = A.con()
cov = pd.read_sql("""select 'payments' t, min(event_ts_ist) mn, max(event_ts_ist) mx, count(*) n from fact_payment
union all select 'calls', min(event_ts_ist), max(event_ts_ist), count(*) from fact_call
union all select 'targeting', min(target_date), max(target_date), count(*) from fact_targeting
union all select 'accounts opened', min(opened_at), max(opened_at), count(*) from dim_account""", con)
display(cov)
print("-> events cover 1 Jan to 8 Aug 2026 (~7.3 months). August has 8 days: excluded from MoM comparisons. No accounts opened in the window.")

# %% [markdown]
# ## 2. Raw → Rejected/Corrected → Golden
# `raw = golden + rejected/superseded` holds for every table (asserted in tests).

# %%
display(pd.read_sql("select tbl, raw_rows, rejected_rows, clean_rows as golden_rows from recon_row_counts", con))
display(pd.read_sql("select issue_id, area, issue, rows_affected, base_rows from dq_issue_log", con))

# %% [markdown]
# ## 3. Reproduce the claim — which definition gives +11%?
# The dataset contains no "reported" metric table, so we replay plausible definitions. Percent change ≠ percentage-point change: ratios (contact rate, recovery rate) are reported in **pp**, money in **%**.

# %%
display(R["claim"])
cal = R["calendar"]
print(f"Feb→Mar golden total: {cal['total_mom']*100:+.2f}%   = calendar days {cal['calendar_days_effect']*100:+.2f}%  ×  per-day {cal['per_day_mom']*100:+.2f}%")
print("identity check (1+cal)(1+perday)-1 =", f"{cal['check_product']*100:+.2f}%")
print("per-day bootstrap CI95:", [f"{x*100:+.1f}%" for x in R['per_day_test']['ci95']], " permutation p =", round(R['per_day_test']['perm_p'], 3))

# %%
fig, ax = plt.subplots(1, 2, figsize=(11, 3.4)); m = R["monthly"].loc[A.FULL_MONTHS]
ax[0].bar(m.index.str[5:], m.net_inr / CR, color=["#c0392b" if x == "2026-03" else "#1f3a5f" for x in m.index]); ax[0].set_title("Total net recovery (₹ Cr)")
ax[1].bar(m.index.str[5:], m.net_inr_per_day / 1e5, color="#d98e04"); ax[1].set_title("Per observed day (₹ lakh)")
for a in ax: a.spines[["top", "right"]].set_visible(False)
plt.tight_layout(); plt.show()

# %% [markdown]
# **Conclusion 1 (Fact):** raw SETTLED payment rows reproduce ≈ +11% for Feb→Mar; the golden total gives +10.5%; per observed day it is ≈ 0%. The claim is a 28-vs-31-day artefact plus definitional looseness.
#
# ### Impact of each cleaning rule on the Feb→Mar headline

# %%
display(R["stepwise"]); display(R["waterfall"])

# %% [markdown]
# ## 4. Forensics (A–G)
# ### A. Duplicate payments — and why a repeated `payment_reference` is NOT a duplicate

# %%
a = R["A"]; display(a["by_month"]); display(a["dup_kinds"])
print("reference collisions (different account/amount):", a["ref_collisions"], "| same ref+account+amount under distinct ids:", a["same_ref_acct_amount_distinct_ids"])

# %% [markdown]
# ### B. Attribution-window bias — is a payment "caused" by the last touch?
# Placebo: keep each payment's account but draw its date at random. If real payments follow touches no more often than placebo payments, attribution is coincidence.

# %%
display(R["B_window"]); display(R["B_rules"]["credit"])
print("voice credits whose campaign window excludes the call (%):", round(R["B_rules"]["voice_credit_campaign_window_invalid_pct"], 1))

# %% [markdown]
# ### C. Timezones

# %%
c = R["C"]
print({k: (round(v, 2) if isinstance(v, float) else v) for k, v in c.items() if k != "payment_tz_sensitivity"})
display(c["payment_tz_sensitivity"])

# %% [markdown]
# ### D. Vendor / disposition-code mapping

# %%
d = R["D"]; display(d["code_by_version"]); display(d["vendor_map"])
print("version×month χ² p:", round(d["disp_version_month_chi2_p"], 3), "| vendor mix p:", round(d["vendor_mix_chi2_p"], 3),
      "| PTP rate canonical vs legacy-code-only:", round(d["ptp_rate_canonical_pct"], 1), round(d["ptp_rate_legacy_code_only_pct"], 1))

# %% [markdown]
# ### E. Agent identity   ·   F. Portfolio mix   ·   G. Denominator

# %%
print("E agents:", R["E"])
print("F mix:", {k: (round(v, 3) if isinstance(v, float) else v) for k, v in R["F"].items() if k != "avg_outstanding_worked"})
display(R["G"]["table"].round(2))
print({k: v for k, v in R["G"].items() if k != "table"})

# %% [markdown]
# ## 5. Independent metric definitions (golden) vs naive
# See `docs/metric_definitions.md` for numerator / denominator / eligibility / window of each metric.

# %%
cols = ["net_inr", "net_inr_per_day", "recovery_rate_fixed_pct", "recovery_per_account_base", "recovery_per_worked_account", "contact_rate_call_pct", "rep_contact_rate_pct",
        "contact_rate_account_pct", "rpc_rate_pct", "ptp_rate_pct", "rep_ptp_rate_legacy_code_pct", "ptp_kept_rate_resolved_pct", "rep_ptp_kept_rate_naive_pct",
        "ptp_payment_verified_rate_pct", "agent_hours_all", "recovery_per_agent_hour", "agent_hours_per_lakh_recovered"]
display(R["monthly"].loc[A.FULL_MONTHS, cols].T)
display(R["trends"])
print("Cost per ₹ recovered: NOT COMPUTABLE - no cost data supplied. Proxy shown: agent-hours and outbound calls per ₹ lakh recovered.")

# %% [markdown]
# ## 6. Drivers — 13 requested dimensions, 29 tests, one FDR correction
# Outcome definitions: account-level "paid at least once"; call-level "answered" and "recovery payment within 7 days after the call" (delinquent accounts only — calls to dpd=0 accounts can never lead to *recovery*, which would create a spurious DPD effect; this artefact was caught and removed).

# %%
drv = R["drivers"]; display(drv[["requested_driver", "dimension", "unit", "outcome", "n", "levels", "spread_pp", "p", "q_bh"]].sort_values("p"))
print("significant raw p<0.05:", int(drv['significant_raw_p<0.05'].sum()), "| after Benjamini-Hochberg:", int(drv['significant_after_BH_q<0.05'].sum()), "of", len(drv))
print("Not available in data: client, language (no such fields).")

# %% [markdown]
# ### Attempt frequency / channel intensity — within-account (fixed-effects) dose-response
# Removes every time-invariant account characteristic (DPD, risk, geography). Contemporaneous *and* next-month slopes. Reverse causality (agents chase likely payers) would bias slopes **up**, so a null is informative.

# %%
display(R["dose"]); print("baseline paid-this-month (pp):", round(R["dose_base_pp"], 2))
display(R["channel"])
display(R["reported_vs_real"])

# %% [markdown]
# ## 7. Statistical traps: Simpson, mix, survivorship, time series

# %%
print("Simpson scan:", R["simpson"]["scans"], "scans, reversals:", R["simpson"]["reversals"])
print("Mix vs rate (Feb→Mar paid rate on worked accounts):", R["F"]["shift_share_paid_rate_feb_mar"])
print("Survivorship (retention of non-payers vs payers):", R["G"]["retention_next_month_pct"], "p =", round(R["G"]["retention_chi2_p"], 3))
print("Time series:", R["ts"])

# %% [markdown]
# ## 8. Counterfactual — "what if the targeting strategy had not changed?"
# **Step 1 — Was there a change we can see?** Scan every month boundary for shifts in the targeting data.

# %%
tg = R["tgt_scan"]; display(tg)
from src import stats_utils as su
q = su.bh_adjust(tg.values.ravel()); print("36 tests: min raw p =", round(tg.values.min(), 3), "| min BH q =", round(q.min(), 2))

# %% [markdown]
# **Step 2 — Difference-in-differences as a diagnostic.** Treated = account first targeted after T0 by a new-strategy (v2/v3) campaign; control = legacy/v1.
# Outcome: ₹/account/day, pre vs post. Two candidate dates because the change date is not documented.
# *Identification assumptions:* parallel trends, no anticipation, assignment of campaign strategy independent of account potential outcomes. **None can be verified** (assignment rule unknown).

# %%
for k in ("did_jul", "did_apr"):
    r = R[k]; print({a: (round(b, 3) if isinstance(b, float) else b) for a, b in r.items() if a != "ci95_rel_pct"}, "| CI rel %:", [round(x, 1) for x in r["ci95_rel_pct"]])

# %% [markdown]
# **Verdict (Hypothesis):** estimates flip sign across plausible dates and CIs include 0 → effect **not identifiable**. Design a randomised holdout instead:

# %%
ex = R["experiment"]; print({k: v for k, v in ex.items() if k not in ("rows", "table")}); display(ex["table"])

# %% [markdown]
# ## 9. Investment — all six options, one recommendation

# %%
pd.set_option("display.max_colwidth", 400); display(R["grid"])
inv = R["invest"]; print("baseline:", {k: (round(v / CR, 1) if isinstance(v, float) else v) for k, v in inv["baseline"].items() if k != 'ci95'}, "₹ Cr (annualised from 212 days); CI ₹ Cr:", [round(x / CR, 1) for x in inv["baseline"]["ci95"]])
print("break-even uplift: 100% capture", round(inv["break_even_uplift_pct_100"], 2), "% | 50%:", round(inv["break_even_uplift_pct_50"], 1), "% | 25%:", round(inv["break_even_uplift_pct_25"], 1), "%")
display(inv["scenarios"].assign(incremental_benefit_year1_cr=lambda d: d.incremental_benefit_year1_inr / CR, net_vs_10cr_cr=lambda d: d.net_vs_10cr_inr / CR).drop(columns=["incremental_benefit_year1_inr", "net_vs_10cr_inr"]))

# %% [markdown]
# **Recommendation:** Option 4 (targeting), tranche-released behind a randomised holdout. Expected incremental recovery is **not reliably estimable** (evidenced central case ₹0); break-even is the stated uplift on the stated run-rate; downside = loss of the tranche deployed;
# range = scenario table. No cost estimate is invented: ₹10 Cr is treated as all-in. See `reports/executive_memo.pdf`.
#
# ## 10. Limitations
# Single account snapshot · timestamp semantics assumed for tables without tz · agent identity unresolved · no cost/client/language/agentic-voice data · several fields behave like independent random draws, so "no effect" means "no detectable effect".
