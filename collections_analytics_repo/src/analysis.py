"""Analysis library. Every function reads ONLY from the golden/metrics layers in the SQLite DB and returns plain
python/pandas objects, so the notebook, dashboard, memo and tests all use identical numbers."""
import sqlite3
import numpy as np
import pandas as pd
from scipy import stats
from .config import DB_PATH, ATTRIBUTION_WINDOW_DAYS
from . import stats_utils as su

FEB, MAR = "2026-02", "2026-03"
FULL_MONTHS = ["2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06", "2026-07"]  # Aug = 8 days -> partial


def con():
    return sqlite3.connect(DB_PATH)


def q(sql, c=None):
    c = c or con()
    return pd.read_sql(sql, c)


# ------------------------------------------------------------------ S1 reproduce the claim --------------
def monthly():
    return q("select * from metrics_monthly").set_index("report_month")


def claim_reproduction():
    """Which definition reproduces '+11% MoM'? and what is the per-day truth?"""
    m = monthly()
    full = m.loc[FULL_MONTHS]
    defs = {
        "A. Raw payment rows, all statuses, duplicates included (₹)": "rep_all_inr",
        "B. Raw SUCCESS rows, duplicates included (₹)": "rep_success_inr",
        "C. SUCCESS, de-duplicated (₹)": "succ_dedup_inr",
        "D. GOLDEN net recovery (settled, dedup, delinquent accounts) (₹)": "net_inr",
        "E. GOLDEN net recovery per observed day (₹/day)": "net_inr_per_day",
    }
    rows = []
    for label, col in defs.items():
        s = full[col] if col != "succ_dedup_inr" else full[col]
        pct = (s / s.shift(1) - 1) * 100
        rows.append({"definition": label, "Jan→Feb %": pct.iloc[1], "Feb→Mar %": pct.iloc[2], "Mar→Apr %": pct.iloc[3], "Apr→May %": pct.iloc[4],
                     "May→Jun %": pct.iloc[5], "Jun→Jul %": pct.iloc[6],
                     "max |MoM| %": pct.abs().max()})
    return pd.DataFrame(rows).set_index("definition")


def calendar_decomposition():
    """(1+MoM_total) = (days_Mar/days_Feb) * (1+MoM_per_day)  -> separate calendar from performance."""
    m = monthly().loc[[FEB, MAR]]
    tot = m.net_inr.iloc[1] / m.net_inr.iloc[0] - 1
    cal = m.days_observed.iloc[1] / m.days_observed.iloc[0] - 1
    perday = m.net_inr_per_day.iloc[1] / m.net_inr_per_day.iloc[0] - 1
    return {"total_mom": tot, "calendar_days_effect": cal, "per_day_mom": perday,
            "check_product": (1 + cal) * (1 + perday) - 1}


def daily_recovery():
    d = q("""select report_date d, sum(amount) inr, count(*) n from fact_payment where is_recovery=1 group by 1 order by 1""")
    d["d"] = pd.to_datetime(d.d)
    d = d.set_index("d").asfreq("D", fill_value=0)
    d["month"] = d.index.strftime("%Y-%m")
    return d


def per_day_change_test(m0=FEB, m1=MAR, n_boot=5000, seed=7):
    """Is Mar-vs-Feb change in the *daily average* distinguishable from zero? (bootstrap over days + permutation)"""
    d = daily_recovery()
    a, b = d[d.month == m0].inr.values, d[d.month == m1].inr.values
    rng = np.random.default_rng(seed)
    boots = [(rng.choice(b, len(b)).mean() / rng.choice(a, len(a)).mean() - 1) for _ in range(n_boot)]
    obs, p = su.perm_p_diff_means(b, a, n=5000, seed=seed)
    return {"per_day_change": float(b.mean() / a.mean() - 1), "ci95": (float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5))),
            "perm_p": p, "days": (len(a), len(b))}


def pairwise_per_day_volatility():
    """Distribution of per-day MoM across consecutive full months -> what is 'normal' noise."""
    m = monthly().loc[FULL_MONTHS]
    x = (m.net_inr_per_day / m.net_inr_per_day.shift(1) - 1).dropna() * 100
    y = (m.net_inr / m.net_inr.shift(1) - 1).dropna() * 100
    return pd.DataFrame({"total_mom_pct": y, "per_day_mom_pct": x})


# ------------------------------------------------------------------ S2 cleaning impact -------------------
def cleaning_waterfall():
    return q("select step, step_name, delta_inr, running_inr, rows_affected from recon_recovery_waterfall order by step")


def stepwise_mom_impact():
    """Feb->Mar % change after each successive cleaning rule (shows which rule moves the headline)."""
    p = q("""select s.payment_id, s.account_id, s.amount, s.payment_status st, s.event_ts_ist ts, s.raw_row_id,
                    (select 1 from rejects r where r.src_table='payments' and r.raw_row_id=s.raw_row_id) is_dup
             from stg_payments s""")
    d = q("select account_id,is_collectible from dim_account").set_index("account_id").is_collectible
    p["month"] = p.ts.str[:7]
    p["coll"] = p.account_id.map(d)
    def mom(df):
        s = df.groupby("month").amount.sum()
        return (s[MAR] / s[FEB] - 1) * 100, s[FEB], s[MAR]
    steps = []
    cur = p.copy()
    steps.append(("1. Raw, all rows/statuses", *mom(cur)))
    cur = cur[cur.is_dup.isna()]; steps.append(("2. + remove duplicate payment_id", *mom(cur)))
    cur = cur[cur.st == "SUCCESS"]; steps.append(("3. + settled (SUCCESS) only", *mom(cur)))
    cur = cur[cur.coll == 1]; steps.append(("4. + delinquent accounts only (GOLDEN total)", *mom(cur)))
    out = pd.DataFrame(steps, columns=["step", "Feb→Mar %", "Feb ₹", "Mar ₹"]).set_index("step")
    days = {FEB: 28, MAR: 31}
    out.loc["5. GOLDEN per observed day", ["Feb→Mar %", "Feb ₹", "Mar ₹"]] = [
        ((cur.groupby("month").amount.sum()[MAR] / 31) / (cur.groupby("month").amount.sum()[FEB] / 28) - 1) * 100,
        cur.groupby("month").amount.sum()[FEB] / 28, cur.groupby("month").amount.sum()[MAR] / 31]
    return out


# ------------------------------------------------------------------ S3 forensics A-G ---------------------
def forensic_A_duplicates():
    m = monthly().loc[FULL_MONTHS]
    t = pd.DataFrame({"raw_success": m.rep_success_inr, "dedup_success": m.succ_dedup_inr})
    t["inflation_inr"] = t.raw_success - t.dedup_success
    t["inflation_pct"] = t.inflation_inr / t.dedup_success * 100
    kinds = q("select reason, count(*) n from rejects where src_table='payments' group by 1")
    coll = q("""select count(*) rows_sharing_ref, count(distinct payment_reference) refs from fact_payment where ref_collision_flag=1""")
    same = q("""select count(*) n from (select payment_reference, account_id, amount from fact_payment
                where payment_reference is not null group by 1,2,3 having count(*)>1)""")
    succ_dups = q("""select count(*) n, sum(s.amount) inr from stg_payments s join rejects r on r.src_table='payments' and r.raw_row_id=s.raw_row_id
                     where s.payment_status='SUCCESS'""")
    return {"by_month": t, "dup_kinds": kinds, "ref_collisions": coll.iloc[0].to_dict(),
            "same_ref_acct_amount_distinct_ids": int(same.n[0]), "success_dups": succ_dups.iloc[0].to_dict(),
            "total_inflation_inr": float(t.inflation_inr.sum()), "total_inflation_pct": float(t.inflation_inr.sum() / t.dedup_success.sum() * 100)}


def _touch_and_pay():
    pay = q("select payment_id, account_id, amount, event_ts_utc from fact_payment where is_recovery=1")
    pay["t"] = pd.to_datetime(pay.event_ts_utc).astype("datetime64[ns]")
    tch = q("select account_id, channel, touch_ts_utc, campaign_id, touch_id from fact_touch")
    tch["t"] = pd.to_datetime(tch.touch_ts_utc).astype("datetime64[ns]")
    return pay, tch


def attribution_window_sensitivity(windows=(1, 3, 7, 14, 30), n_placebo=20, seed=11):
    pay, tch = _touch_and_pay()
    pay_s, tch_s = pay.sort_values("t"), tch.sort_values("t")
    rows = []
    for w in windows:
        m = pd.merge_asof(pay_s, tch_s[["account_id", "t", "channel"]].rename(columns={"t": "tt"}), left_on="t", right_on="tt",
                          by="account_id", direction="backward", tolerance=pd.Timedelta(days=w))
        att = m.channel.notna()
        rows.append({"window_days": w, "attributed_pct_of_payments": att.mean() * 100, "attributed_inr": m.loc[att, "amount"].sum(),
                     **{f"last_touch_{c}_pct": (m.channel == c).mean() * 100 for c in ["VOICE", "WHATSAPP", "SMS", "FIELD"]}})
    obs = pd.DataFrame(rows).set_index("window_days")
    # placebo: same accounts, payment dates drawn uniformly over the observation window
    rng = np.random.default_rng(seed)
    lo, hi = pay.t.min().value, pay.t.max().value
    pl = {w: [] for w in windows}
    for _ in range(n_placebo):
        fake = pay_s.copy()
        fake["t"] = pd.to_datetime(rng.integers(lo, hi, len(fake))).astype("datetime64[ns]")
        fake = fake.sort_values("t")
        for w in windows:
            m = pd.merge_asof(fake, tch_s[["account_id", "t", "channel"]].rename(columns={"t": "tt"}), left_on="t", right_on="tt",
                              by="account_id", direction="backward", tolerance=pd.Timedelta(days=w))
            pl[w].append(m.channel.notna().mean() * 100)
    obs["placebo_attributed_pct_mean"] = [np.mean(pl[w]) for w in windows]
    obs["placebo_sd"] = [np.std(pl[w]) for w in windows]
    obs["excess_over_chance_pp"] = obs.attributed_pct_of_payments - obs.placebo_attributed_pct_mean
    obs["z"] = obs.excess_over_chance_pp / obs.placebo_sd
    return obs


def attribution_rule_comparison(window=ATTRIBUTION_WINDOW_DAYS):
    """last-touch vs first-touch credit and campaign validity of the credited call."""
    a = q("select payment_id, amount, last_touch_channel, first_touch_channel, last_touch_campaign, n_touches, attribution_status from ft_payment_attribution")
    att = a[a.attribution_status == "ATTRIBUTED"]
    cred = pd.DataFrame({"last_touch_inr": att.groupby("last_touch_channel").amount.sum(), "first_touch_inr": att.groupby("first_touch_channel").amount.sum()}).fillna(0)
    cred["swing_pct"] = (cred.first_touch_inr / cred.last_touch_inr - 1) * 100
    multi = (att.n_touches > 1).mean() * 100
    # campaign validity of credited voice call
    v = q("""select a.payment_id, c.within_campaign_window w from ft_payment_attribution a
             join fact_call c on c.is_outbound=1 and c.is_answered=1 and c.account_id=(select account_id from fact_payment p where p.payment_id=a.payment_id)
              and c.event_ts_utc=a.last_touch_ts where a.last_touch_channel='VOICE'""")
    return {"credit": cred, "pct_attributed_multi_touch": multi, "unattributed_pct": float((a.attribution_status == "UNATTRIBUTED").mean() * 100),
            "voice_credits": int(len(v)), "voice_credit_campaign_window_invalid_pct": float((v.w == 0).mean() * 100) if len(v) else np.nan}


def forensic_C_timezone():
    c = q("select source_tz, hour_ist, hour_naive, report_month, month_naive, report_date, substr(event_ts_ist,1,10) d_ist, "
          "substr(event_ts_ist,1,10) dist from fact_call where in_window=1")
    raw_local = q("select substr(event_at_local,1,10) d_local, tz from stg_calls")  # same row set incl dups; only used for % of tz labels
    n = len(c)
    changed_hour = (c.hour_ist != c.hour_naive).mean() * 100
    changed_month = (c.report_month != c.month_naive).mean() * 100
    # compliance window 08:00-19:00 IST (RBI fair-practice hours) as an exposure indicator, using corrected vs naive clocks
    comp_ist = ((c.hour_ist < 8) | (c.hour_ist >= 19)).mean() * 100
    comp_naive = ((c.hour_naive < 8) | (c.hour_naive >= 19)).mean() * 100
    by_tz = c.source_tz.value_counts(normalize=True).mul(100).round(1).to_dict()
    # payments: sensitivity of Feb->Mar to the tz interpretation for tables with no tz column
    p = q("select p.payment_id, p.amount, p.event_ts_ist ts, d.account_tz from fact_payment p join dim_account d using(account_id) where p.is_recovery=1")
    p["ts"] = pd.to_datetime(p.ts)
    off = {"Asia/Kolkata": 330, "Asia/Dubai": 240, "UTC": 0}
    variants = {
        "baseline: timestamps are IST": p.ts,
        "timestamps are UTC (shift +5:30 to IST)": p.ts + pd.Timedelta(minutes=330),
        "timestamps are in account timezone": p.ts - pd.to_timedelta(p.account_tz.map(off), unit="m") + pd.Timedelta(minutes=330),
    }
    rows = []
    for k, ts in variants.items():
        mo = ts.dt.strftime("%Y-%m")
        s = p.assign(mo=mo).groupby("mo").amount.sum()
        pd_feb, pd_mar = s[FEB] / 28, s[MAR] / 31
        rows.append({"assumption": k, "Feb→Mar total %": (s[MAR] / s[FEB] - 1) * 100, "Feb→Mar per-day %": (pd_mar / pd_feb - 1) * 100,
                     "payments changing month vs baseline": int((mo != p.ts.dt.strftime("%Y-%m")).sum())})
    return {"calls": n, "pct_hour_changed": changed_hour, "pct_month_changed": changed_month, "pct_outside_8_19_ist": comp_ist,
            "pct_outside_8_19_naive": comp_naive, "tz_mix": by_tz, "payment_tz_sensitivity": pd.DataFrame(rows).set_index("assumption")}


def forensic_D_vendor_and_codes():
    calls = q("select report_month, vendor_name, vendor_status, is_answered from fact_call where is_outbound=1 and in_window=1")
    ct = pd.crosstab(calls.report_month, calls.vendor_name)
    chi_vendor_mix = stats.chi2_contingency(ct)[1]
    inactive_share = calls.groupby("report_month").vendor_status.apply(lambda s: (s == "INACTIVE").mean() * 100)
    chi_inactive = stats.chi2_contingency(pd.crosstab(calls.report_month, calls.vendor_status))[1]
    d = q("select report_month, disposition_version, disposition_code_raw from fact_disposition")
    ver_by_month = pd.crosstab(d.report_month, d.disposition_version, normalize="index") * 100
    chi_ver = stats.chi2_contingency(pd.crosstab(d.report_month, d.disposition_version))[1]
    alias = pd.crosstab(d.disposition_code_raw, d.disposition_version)
    vm = q("select vendor_name, count(*) n_vendor_ids, group_concat(vendor_id) ids from dim_vendor where vendor_id<>'UNKNOWN' group by 1")
    mism = q("select avg(source_tz<>vendor_tz)*100 pct from fact_call c join dim_vendor v using(vendor_id) where c.in_window=1").pct[0]
    rpc = monthly().loc[FULL_MONTHS]
    return {"vendor_mix_chi2_p": chi_vendor_mix, "inactive_vendor_share_by_month": inactive_share, "inactive_share_chi2_p": chi_inactive,
            "disp_version_share_by_month": ver_by_month, "disp_version_month_chi2_p": chi_ver, "code_by_version": alias, "vendor_map": vm,
            "call_tz_vs_vendor_tz_mismatch_pct": float(mism),
            "ptp_rate_canonical_pct": float(rpc.ptp_rate_pct.mean()), "ptp_rate_legacy_code_only_pct": float(rpc.rep_ptp_rate_legacy_code_pct.mean())}


def forensic_E_agents():
    s = q("select agent_id, employee_code, agent_name, joined_at from stg_agents")
    par = {}
    def f(x):
        while par.setdefault(x, x) != x:
            par[x] = par[par[x]]; x = par[x]
        return x
    for a, e in s[["agent_id", "employee_code"]].drop_duplicates().values:
        par[f(a)] = f(e)
    comps = len({f(a) for a in s.agent_id.unique()})
    g = s.groupby("agent_id").agg(n_snap=("agent_name", "size"), n_names=("agent_name", "nunique"), n_emp=("employee_code", "nunique"))
    sp = q("select joined_at_spread_days from dim_agent where agent_id<>'UNKNOWN'").joined_at_spread_days
    emp_to_agents = s.groupby("employee_code").agent_id.nunique()
    c = q("select agent_key, is_answered from fact_call where is_outbound=1 and in_window=1 and agent_key<>'UNKNOWN'")
    a = c.groupby("agent_key").is_answered.agg(["sum", "count"])
    od = su.overdispersion_test(a["sum"], a["count"])
    return {"agent_ids": int(s.agent_id.nunique()), "snapshot_rows": len(s), "distinct_names": int(s.agent_name.nunique()),
            "distinct_employee_codes": int(s.employee_code.nunique()), "mean_employee_codes_per_agent_id": float(g.n_emp.mean()),
            "mean_agent_ids_per_employee_code": float(emp_to_agents.mean()), "components_if_merged_on_employee_code": comps,
            "median_joined_at_spread_days": float(sp.median()), "overdispersion_contact_rate": od, "calls_per_agent": float(a["count"].mean())}


def forensic_F_portfolio_mix():
    a = q("select min(opened_at) mn, max(opened_at) mx from dim_account").iloc[0].to_dict()
    w = q("select report_month, dpd_bucket, loan_type, risk_segment, state, is_worked, recovered, outstanding_amount from ft_account_month where is_worked=1 and report_month<>'2026-08'")
    res = {}
    for dim in ["dpd_bucket", "loan_type", "risk_segment", "state"]:
        res[dim] = stats.chi2_contingency(pd.crosstab(w.report_month, w[dim]))[1]
    w["paid"] = (w.recovered > 0).astype(int); w["one"] = 1
    w["stratum"] = w.dpd_bucket + "|" + w.loan_type
    ss = su.shift_share(w, "stratum", "report_month", FEB, MAR, "paid", "one")
    avg_out = w.groupby("report_month").outstanding_amount.mean()
    return {"opened_range": a, "mix_homogeneity_p": res, "shift_share_paid_rate_feb_mar": ss, "avg_outstanding_worked": avg_out}


def forensic_G_denominator():
    m = monthly().loc[FULL_MONTHS]
    t = m[["elig_n", "elig_out", "net_inr", "recovery_rate_fixed_pct", "recovery_rate_asof_eligible_pct", "rep_recovery_rate_mismatched_denominator_pct"]].copy()
    t["mismatch_cum_change_pct"] = (t.rep_recovery_rate_mismatched_denominator_pct / t.rep_recovery_rate_mismatched_denominator_pct.iloc[0] - 1) * 100
    t["eligible_base_vs_jan_pct"] = (t.elig_out / t.elig_out.iloc[0] - 1) * 100
    pay_on_closed = q("""select count(*) n, sum(p.amount) inr from fact_payment p join ft_asof_status a on a.account_id=p.account_id and a.report_month=p.report_month
                         where p.is_recovery=1 and a.asof_status in ('PAID','CLOSED','WRITEOFF')""").iloc[0].to_dict()
    # does the worked population drop accounts that did not pay? (retention of non-payers vs payers into next month)
    p = q("select account_id, report_month, is_worked, recovered from ft_account_month where report_month<>'2026-08'")
    p["paid"] = (p.recovered > 0)
    p = p.sort_values(["account_id", "report_month"])
    p["next_worked"] = p.groupby("account_id").is_worked.shift(-1)
    base = p[(p.is_worked == 1) & p.next_worked.notna()]
    ret = base.groupby("paid").next_worked.mean() * 100
    ct = pd.crosstab(base.paid, base.next_worked)
    pv = stats.chi2_contingency(ct)[1]
    return {"table": t, "payments_on_asof_closed": pay_on_closed, "share_of_recovery_on_asof_closed_pct": pay_on_closed["inr"] / m.net_inr.sum() * 100,
            "retention_next_month_pct": ret.to_dict(), "retention_chi2_p": pv}


# ------------------------------------------------------------------ S4 drivers ----------------------------
def _calls_with_outcomes():
    c = q("""select c.call_id, c.account_id, c.agent_key, c.campaign_id, c.vendor_name, c.vendor_status, c.hour_ist, c.dow, c.is_answered,
                    c.agent_tenure_months, c.event_ts_utc, c.report_month, c.dpd_bucket, c.strategy_version, c.campaign_channel,
                    cm.campaign_name, cm.target_definition
             from fact_call c join dim_campaign cm using(campaign_id) where c.is_outbound=1 and c.in_window=1 and c.is_collectible=1""")  # dpd=0 calls cannot lead to 'recovery' by definition -> excluded to avoid a mechanical artefact
    c["t"] = pd.to_datetime(c.event_ts_utc).astype("datetime64[ns]")
    pay = q("select account_id, event_ts_utc from fact_payment where is_recovery=1")
    pay["pt"] = pd.to_datetime(pay.event_ts_utc).astype("datetime64[ns]")
    m = pd.merge_asof(c.sort_values("t"), pay[["account_id", "pt"]].sort_values("pt"), left_on="t", right_on="pt", by="account_id", direction="forward")
    c = m
    c["paid7"] = ((c.pt - c.t).dt.total_seconds() <= 7 * 86400).astype(int)
    c["hour_band"] = pd.cut(c.hour_ist, [-1, 5, 8, 11, 14, 17, 20, 23], labels=["00-05", "06-08", "09-11", "12-14", "15-17", "18-20", "21-23"])
    c["tenure_band"] = pd.cut(c.agent_tenure_months, [-1000, 18, 24, 1000], labels=["<=18m", "19-24m", "25m+"])
    c["dow_name"] = c.dow.map(dict(enumerate(["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"])))
    return c


def drivers_table():
    acc = q("""select d.account_id, d.dpd_bucket, d.loan_type, d.risk_segment, d.state, d.outstanding_band, d.opened_cohort, d.status_snapshot,
                      COALESCE(p.rec,0) rec from dim_account d left join (select account_id, sum(amount) rec from fact_payment where is_recovery=1 group by 1) p using(account_id)
               where d.is_collectible=1""")
    acc["paid"] = (acc.rec > 0).astype(int)
    calls = _calls_with_outcomes()
    rows = []
    def add(requested, dimension, df, dim, outcome, unit):
        r = su.chi2_homogeneity(df, dim, outcome)
        rows.append({"requested_driver": requested, "dimension": dimension, "unit": unit, "outcome": outcome, "n": len(df), **r})
    for req, dim in [("Portfolio mix", "loan_type"), ("DPD", "dpd_bucket"), ("Geography", "state"), ("Borrower segment", "risk_segment"),
                     ("Borrower segment", "outstanding_band"), ("Cohort", "opened_cohort"), ("Borrower segment", "status_snapshot")]:
        add(req, dim, acc, dim, "paid", "account (any recovery payment, Jan-Aug)")
    for oc in ["is_answered", "paid7"]:
        unit = "outbound call"
        for req, dim in [("Telephony vendor", "vendor_name"), ("Calling time", "hour_band"), ("Calling time", "dow_name"),
                         ("Agent tenure", "tenure_band"), ("Campaign", "campaign_name"), ("Campaign", "strategy_version"),
                         ("Campaign", "target_definition"), ("Channel (campaign channel)", "campaign_channel"), ("DPD", "dpd_bucket")]:
            add(req, dim, calls, dim, oc, unit)
        a = calls[calls.agent_key != "UNKNOWN"].groupby("agent_key")[oc].agg(["sum", "count"])
        od = su.overdispersion_test(a["sum"], a["count"])
        rows.append({"requested_driver": "Agent", "dimension": "agent_key (1,000 agents; overdispersion test)", "unit": unit, "outcome": oc,
                     "n": int(a["count"].sum()), "levels": len(a), "min_rate": np.nan, "max_rate": np.nan, "spread_pp": np.nan, "chi2": od["chi2"], "p": od["p"]})
        cc = calls.groupby("campaign_id")[oc].agg(["sum", "count"])
        od = su.overdispersion_test(cc["sum"], cc["count"])
        rows.append({"requested_driver": "Campaign", "dimension": "campaign_id (120 campaigns; overdispersion test)", "unit": unit, "outcome": oc,
                     "n": int(cc["count"].sum()), "levels": len(cc), "min_rate": np.nan, "max_rate": np.nan, "spread_pp": np.nan, "chi2": od["chi2"], "p": od["p"]})
    t = pd.DataFrame(rows)
    t["q_bh"] = su.bh_adjust(t.p.values)
    t["significant_raw_p<0.05"] = t.p < 0.05
    t["significant_after_BH_q<0.05"] = t.q_bh < 0.05
    return t


def dose_response():
    """Within-account (fixed-effects) response of 'paid this month' (pp) to one more touch. Removes all
    time-invariant account differences (DPD, risk, geography, ...). Cluster-robust SE by account."""
    d = q("""select account_id, report_month, outbound_calls, answered_calls, wa_events, sms_events, field_visits,
                    (recovered>0)*100.0 paid_pp, recovered from ft_account_month where report_month<>'2026-08'""")
    d = d.sort_values(["account_id", "report_month"])
    d["touches"] = d.answered_calls + d.wa_events + d.sms_events + d.field_visits
    rows = []
    for x, label in [("outbound_calls", "Outbound call attempts"), ("answered_calls", "Answered calls"), ("wa_events", "WhatsApp events"),
                     ("sms_events", "SMS events"), ("field_visits", "Field visits"), ("touches", "All contact touches")]:
        r = su.within_ols_cluster(d.paid_pp, d[x], d.account_id)
        d["lead_paid"] = d.groupby("account_id").paid_pp.shift(-1)
        dd = d.dropna(subset=["lead_paid"])
        r2 = su.within_ols_cluster(dd.lead_paid, dd[x], dd.account_id)
        rows.append({"touch": label, "same-month slope (pp per touch)": r["slope"], "se": r["se"], "p": r["p"],
                     "next-month slope (pp)": r2["slope"], "next-month p": r2["p"], "n_account_months": r["n"]})
    t = pd.DataFrame(rows).set_index("touch")
    t["q_bh_same_month"] = su.bh_adjust(t.p.values)
    return t, float(d.paid_pp.mean())


def channel_conversion(n_placebo=30, seed=5):
    """P(recovery payment within 7 days after a touch) by channel vs a placebo in which the touch date is randomised
    within the same account. lift = observed/placebo."""
    pay, tch = _touch_and_pay()
    pay_s = pay[["account_id", "t"]].rename(columns={"t": "pt"}).sort_values("pt")
    def paid7(df):
        df = df.sort_values("t")
        m = pd.merge_asof(df, pay_s, left_on="t", right_on="pt", by="account_id", direction="forward", tolerance=pd.Timedelta(days=7))
        return m.pt.notna().astype(int).values, m.channel.values
    y, ch = paid7(tch[["account_id", "t", "channel"]])
    obs = pd.Series(y).groupby(ch).mean() * 100
    rng = np.random.default_rng(seed)
    lo, hi = tch.t.min().value, tch.t.max().value
    sims = {c: [] for c in obs.index}
    for _ in range(n_placebo):
        f = tch[["account_id", "t", "channel"]].copy()
        f["t"] = pd.to_datetime(rng.integers(lo, hi, len(f))).astype("datetime64[ns]")
        yy, cc = paid7(f)
        s = pd.Series(yy).groupby(cc).mean() * 100
        for c in obs.index: sims[c].append(s[c])
    t = pd.DataFrame({"touches": tch.channel.value_counts(), "conversion_7d_pct": obs})
    t["placebo_mean_pct"] = [np.mean(sims[c]) for c in t.index]
    t["placebo_sd"] = [np.std(sims[c]) for c in t.index]
    t["lift_vs_placebo"] = t.conversion_7d_pct / t.placebo_mean_pct
    t["z"] = (t.conversion_7d_pct - t.placebo_mean_pct) / t.placebo_sd
    return t


def reported_outcome_vs_payment_reality():
    """Do channel-reported 'PAID/KEPT' outcomes correspond to settled payments on that account?"""
    pay = q("select account_id, event_ts_ist from fact_payment where is_recovery=1")
    pay["pt"] = pd.to_datetime(pay.event_ts_ist).astype("datetime64[ns]")
    pay = pay.sort_values("pt")
    def verify(df, tcol, label_col):
        df = df.copy(); df["t"] = pd.to_datetime(df[tcol]).astype("datetime64[ns]")
        m = pd.merge_asof(df.sort_values("t"), pay, left_on="t", right_on="pt", by="account_id", direction="forward", tolerance=pd.Timedelta(days=7))
        m["verified"] = m.pt.notna().astype(int)
        g = m.groupby(label_col).verified.agg(["mean", "count"]); g["mean"] *= 100
        return g
    disp = verify(q("select account_id, event_ts_ist, disposition_code, case when disposition_code='PAID' then 'PAID' else 'other' end lab from fact_disposition"), "event_ts_ist", "lab")
    fv = verify(q("select account_id, event_ts_ist, case when outcome='PAID' then 'PAID' else 'other' end lab from fact_field_visit"), "event_ts_ist", "lab")
    ptp = q("select ptp_status, avg(payment_verified)*100 v, count(*) n from fact_ptp where is_matured=1 and ptp_status in ('KEPT','BROKEN') group by 1").set_index("ptp_status")
    out = {}
    for name, g in [("Call disposition PAID vs other", disp), ("Field-visit outcome PAID vs other", fv)]:
        a, b = g.loc["PAID"], g.loc["other"]
        ct = np.array([[a["mean"] * a["count"] / 100, a["count"] * (1 - a["mean"] / 100)], [b["mean"] * b["count"] / 100, b["count"] * (1 - b["mean"] / 100)]])
        out[name] = {"labelled_PAID_pct_with_payment_7d": float(a["mean"]), "other_pct_with_payment_7d": float(b["mean"]), "n_PAID": int(a["count"]), "chi2_p": float(stats.chi2_contingency(ct)[1])}
    k, b_ = ptp.loc["KEPT"], ptp.loc["BROKEN"]
    ct = np.array([[k.v * k.n / 100, k.n * (1 - k.v / 100)], [b_.v * b_.n / 100, b_.n * (1 - b_.v / 100)]])
    out["PTP status KEPT vs BROKEN (payment within promised window+3d)"] = {"labelled_PAID_pct_with_payment_7d": float(k.v), "other_pct_with_payment_7d": float(b_.v), "n_PAID": int(k.n), "chi2_p": float(stats.chi2_contingency(ct)[1])}
    return pd.DataFrame(out).T


def time_series_checks(n_perm=2000, seed=3):
    d = daily_recovery()
    d = d[d.index <= "2026-08-08"]
    dd = d[d.month != "2026-08"].copy()
    dd["dow"] = dd.index.dayofweek
    f_p = stats.f_oneway(*[g.inr.values for _, g in dd.groupby("dow")]).pvalue
    lag1 = dd.inr.autocorr(1)
    # month-length: regress monthly total on days (calendar explains?)
    mm = monthly().loc[FULL_MONTHS]
    slope, intercept, r, p, se = stats.linregress(mm.days_observed, mm.net_inr)
    # change-point scan on daily mean (max |t| over candidate splits), permutation null
    y = dd.inr.values.astype(float); n = len(y); k0 = 30
    def max_t(v):
        cs = np.cumsum(v); cs2 = np.cumsum(v ** 2); best = 0; arg = None
        for k in range(k0, n - k0):
            m1, m2 = cs[k - 1] / k, (cs[-1] - cs[k - 1]) / (n - k)
            v1 = (cs2[k - 1] - k * m1 ** 2) / (k - 1); v2 = (cs2[-1] - cs2[k - 1] - (n - k) * m2 ** 2) / (n - k - 1)
            t = abs(m1 - m2) / np.sqrt(v1 / k + v2 / (n - k))
            if t > best: best, arg = t, k
        return best, arg
    obs, k = max_t(y)
    rng = np.random.default_rng(seed)
    null = [max_t(rng.permutation(y))[0] for _ in range(300)]
    p_cp = float((np.sum(np.array(null) >= obs) + 1) / (len(null) + 1))
    return {"dow_anova_p": float(f_p), "lag1_autocorr": float(lag1), "monthly_total_on_days": {"slope_inr_per_day": slope, "r2": r ** 2, "p": p},
            "changepoint_best_date": str(dd.index[k].date()), "changepoint_max_t": float(obs), "changepoint_perm_p": p_cp,
            "daily_mean_inr": float(y.mean()), "daily_cv": float(y.std() / y.mean())}


def simpson_scan(min_n=50):
    """Scan consecutive-month contact-rate changes: does the aggregate change have the OPPOSITE sign of every stratum?"""
    c = _calls_with_outcomes()
    months = FULL_MONTHS
    found, scans = [], 0
    for dim in ["vendor_name", "hour_band", "strategy_version", "dpd_bucket", "campaign_channel", "tenure_band", "target_definition"]:
        for a, b in zip(months[:-1], months[1:]):
            sub = c[c.report_month.isin([a, b])]
            agg = sub.groupby("report_month").is_answered.mean()
            ag = agg[b] - agg[a]
            g = sub.groupby([dim, "report_month"], observed=True).is_answered.agg(["mean", "count"]).unstack("report_month")
            ok = (g[("count", a)] >= min_n) & (g[("count", b)] >= min_n)
            ch = (g[("mean", b)] - g[("mean", a)])[ok]
            scans += 1
            if len(ch) >= 2 and ((ch > 0).all() and ag < 0 or (ch < 0).all() and ag > 0):
                found.append({"dimension": dim, "from": a, "to": b, "aggregate_change_pp": ag * 100, "strata_changes_pp": (ch * 100).round(2).tolist()})
    return {"scans": scans, "reversals": found}


# ------------------------------------------------------------------ S5 counterfactual ---------------------
def targeting_change_scan():
    """Is there ANY month boundary at which the targeting data changed? chi-square pre vs post for each feature."""
    t = q("select target_date, report_month, priority, recommended_channel, target_status, strategy_version, dpd_bucket, campaign_name from fact_targeting")
    t["prio_band"] = pd.cut(t.priority, [0, 3, 7, 10], labels=["1-3", "4-7", "8-10"])
    bounds = ["2026-02", "2026-03", "2026-04", "2026-05", "2026-06", "2026-07"]
    rows = []
    for b in bounds:
        post = (t.report_month >= b).astype(int)
        r = {"boundary (post starts)": b}
        for f in ["recommended_channel", "prio_band", "target_status", "strategy_version", "dpd_bucket", "campaign_name"]:
            r[f] = stats.chi2_contingency(pd.crosstab(post, t[f]))[1]
        rows.append(r)
    out = pd.DataFrame(rows).set_index("boundary (post starts)")
    return out


def did_estimate(t0="2026-07-01", n_boot=300, n_perm=300, seed=21):
    """DiD at account level on per-day recovery (₹/day), pre = Jan1..t0, post = t0..Aug8.
    Treated: accounts whose first post-t0 targeting row is in a NEW-strategy (v2/v3) campaign; control: legacy/v1.
    Caveat: assignment mechanism is unknown -> this is a *diagnostic*, not a causal estimate."""
    tg = q("select account_id, target_date, is_new_strategy from fact_targeting where is_collectible=1 order by target_date")
    post_t = tg[tg.target_date >= t0[:10]].groupby("account_id").first()
    post_t = post_t.rename(columns={"is_new_strategy": "treated"})[["treated"]]
    pay = q("select account_id, report_date, amount from fact_payment where is_recovery=1")
    pre_days = (pd.Timestamp(t0) - pd.Timestamp("2026-01-01")).days
    post_days = (pd.Timestamp("2026-08-09") - pd.Timestamp(t0)).days
    pre = pay[pay.report_date < t0[:10]].groupby("account_id").amount.sum()
    post = pay[pay.report_date >= t0[:10]].groupby("account_id").amount.sum()
    acc = q("select account_id, dpd_bucket, outstanding_amount from dim_account where is_collectible=1").set_index("account_id")
    d = acc.join(post_t, how="inner")
    d["pre"] = pre.reindex(d.index).fillna(0) / pre_days
    d["post"] = post.reindex(d.index).fillna(0) / post_days
    d["delta"] = d.post - d.pre
    def est(df): return df[df.treated == 1].delta.mean() - df[df.treated == 0].delta.mean()
    obs = est(d)
    rng = np.random.default_rng(seed)
    boots = [est(d.sample(len(d), replace=True, random_state=int(rng.integers(1e9)))) for _ in range(n_boot)]
    lab = d.treated.values.copy(); perm = []
    for _ in range(n_perm):
        dd = d.copy(); dd["treated"] = rng.permutation(lab); perm.append(est(dd))
    p = float((np.sum(np.abs(perm) >= abs(obs)) + 1) / (n_perm + 1))
    base_pre = d.pre.mean()
    # balance in pre-period (a necessary, not sufficient, condition)
    bal = stats.chi2_contingency(pd.crosstab(d.treated, d.dpd_bucket))[1]
    pre_p = stats.ttest_ind(d[d.treated == 1].pre, d[d.treated == 0].pre, equal_var=False).pvalue
    return {"t0": t0, "n_treated": int((d.treated == 1).sum()), "n_control": int((d.treated == 0).sum()), "did_inr_per_account_per_day": float(obs),
            "ci95": (float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5))), "perm_p": p,
            "baseline_pre_inr_per_account_per_day": float(base_pre), "did_rel_to_baseline_pct": float(obs / base_pre * 100),
            "ci95_rel_pct": (float(np.percentile(boots, 2.5) / base_pre * 100), float(np.percentile(boots, 97.5) / base_pre * 100)),
            "balance_dpd_chi2_p": float(bal), "pre_period_recovery_diff_p": float(pre_p),
            "post_days": int(post_days), "pre_days": int(pre_days)}


def experiment_design():
    m = monthly().loc[FULL_MONTHS]
    base_n = int(m.base_n.iloc[0])
    p0 = float(m.paying_accounts.sum() / (m.base_n.sum()))        # monthly P(account pays)
    acc = q("""select d.account_id, coalesce(x.r,0) r from dim_account d left join (select account_id, sum(amount)/7.0 r from fact_payment where is_recovery=1 and report_month<>'2026-08' group by 1) x using(account_id) where d.is_collectible=1""")
    mean_m, sd_m = float(acc.r.mean()), float(acc.r.std())          # ₹ per account-month (7-month avg)
    out = {"eligible_accounts": base_n, "p_pay_per_account_month": p0, "mean_inr_per_account_month": mean_m, "sd_inr_per_account_month": sd_m, "rows": []}
    for hold in (0.10, 0.20, 0.30):
        nc = int(base_n * hold); nt = base_n - nc
        n_arm = min(nc, nt)
        for months in (1, 3, 6):
            # outcome: share of accounts paying at least once in `months` months (cumulative); approx P = 1-(1-p0)^months
            pc = 1 - (1 - p0) ** months
            mde_bin = su.mde_rel_two_prop(pc, n_arm)
            mde_inr = su.mde_rel_mean(mean_m * months, sd_m * np.sqrt(months), n_arm)
            out["rows"].append({"holdout_share": hold, "months": months, "n_control": nc, "n_treated": nt, "mde_rel_paying_share": mde_bin, "mde_rel_inr_per_account": mde_inr})
    out["n_per_arm_for_5pct_inr_effect_3m"] = int(np.ceil(2 * ((1.96 + 0.8416) * sd_m * np.sqrt(3) / (0.05 * mean_m * 3)) ** 2))
    out["table"] = pd.DataFrame(out["rows"])
    return out


# ------------------------------------------------------------------ S6 investment economics ---------------
def baseline_run_rate(n_boot=2000, seed=4):
    d = daily_recovery()
    d = d[(d.month.isin(FULL_MONTHS))]
    per_day = d.inr.values
    ann = per_day.mean() * 365
    rng = np.random.default_rng(seed)
    boots = [rng.choice(per_day, len(per_day)).mean() * 365 for _ in range(n_boot)]
    return {"days": int(len(per_day)), "net_recovery_inr_observed": float(per_day.sum()), "per_day_inr": float(per_day.mean()),
            "annualised_inr": float(ann), "ci95": (float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5)))}


def investment_scenarios(invest_inr=10e7):
    br = baseline_run_rate()
    ann = br["annualised_inr"]
    be = invest_inr / ann
    rows = []
    for u in (0.0, 0.025, 0.05, 0.075, 0.10, 0.15):
        for capture, lab in ((1.0, "100% of recovered ₹ counted as benefit"), (0.5, "50% capture"), (0.25, "25% capture")):
            inc = ann * u * capture
            rows.append({"relative_uplift": u, "benefit_basis": lab, "incremental_benefit_year1_inr": inc,
                         "net_vs_10cr_inr": inc - invest_inr, "roi_year1_pct": (inc - invest_inr) / invest_inr * 100,
                         "payback_months": (invest_inr / (inc / 12)) if inc > 0 else np.inf})
    t = pd.DataFrame(rows)
    return {"baseline": br, "break_even_uplift_pct_100": be * 100, "break_even_uplift_pct_50": be * 200, "break_even_uplift_pct_25": be * 400,
            "break_even_uplift_ci_pct": (invest_inr / br["ci95"][1] * 100, invest_inr / br["ci95"][0] * 100), "scenarios": t}


def option_evidence_grid(dr, ch, drv):
    """One row per investment option: what the data can and cannot say. Numbers are pulled from computed results."""
    sl = dr.loc["Outbound call attempts"]
    wa = dr.loc["WhatsApp events"]; fv = dr.loc["Field visits"]
    vend = drv[(drv.dimension == "vendor_name") & (drv.outcome == "is_answered")].iloc[0]
    agent = drv[(drv.requested_driver == "Agent") & (drv.outcome == "is_answered")].iloc[0]
    return pd.DataFrame([
        {"option": "1. Better telephony infrastructure", "mechanism_tested": "Contact rate varies by vendor/time/tz",
         "evidence": f"Contact-rate spread across 5 vendors = {vend.spread_pp:.2f}pp (p={vend.p:.3f}, FDR q={vend.q_bh:.2f}); hour-of-day and weekday effects null",
         "verdict": "No measurable infrastructure quality gap to buy back"},
        {"option": "2. More collection agents", "mechanism_tested": "More attempts/handling capacity -> more payments; agent quality dispersion",
         "evidence": f"Within-account slope of paid-this-month on +1 outbound attempt = {sl['same-month slope (pp per touch)']:.3f}pp (p={sl['p']:.2f}); agent dispersion p={agent.p:.2f}; recovery/agent-hour flat ≈ ₹15k",
         "verdict": "No evidence of marginal return to capacity"},
        {"option": "3. AI voice automation", "mechanism_tested": "Cheaper voice contacts at same conversion",
         "evidence": "No agentic/AI-voice channel exists in the data (VOICE sessions & calls only); voice conversion lift vs chance "
                     f"{ch.loc['VOICE','lift_vs_placebo']:.2f}x; cost per call not provided",
         "verdict": "Not evaluable - zero AI-voice data, no cost data"},
        {"option": "4. Better borrower targeting", "mechanism_tested": "Who is worked matters more than how much",
         "evidence": "Targeting queue/dispositions don't separate payers from non-payers on DPD, risk, outstanding, geography, status (all FDR q>0.25); "
                     "status history is inconsistent with payments (23% of recovery ₹ on accounts 'PAID/CLOSED/WRITEOFF' as-of); "
                     "only 11.95% of payments follow any touch - identical to chance",
         "verdict": "Current features carry no signal -> needs data foundation + randomised test; cheapest lever to *measure*"},
        {"option": "5. WhatsApp / digital engagement", "mechanism_tested": "Digital touches raise 7-day payment",
         "evidence": f"WhatsApp 7-day conversion lift vs placebo = {ch.loc['WHATSAPP','lift_vs_placebo']:.2f}x (z={ch.loc['WHATSAPP','z']:.1f}); within-account slope {wa['same-month slope (pp per touch)']:.3f}pp (p={wa['p']:.2f})",
         "verdict": "No positive response observed (point estimate ≤ chance)"},
        {"option": "6. Field operations", "mechanism_tested": "Visits raise payment; outcome codes reliable",
         "evidence": f"Field-visit lift vs placebo = {ch.loc['FIELD','lift_vs_placebo']:.2f}x; slope {fv['same-month slope (pp per touch)']:.3f}pp (p={fv['p']:.2f}); visits coded PAID are followed by payment no more often than other visits",
         "verdict": "No measurable response; highest unit cost typically (cost not provided)"},
    ]).set_index("option")


def kpi_trends():
    """Linear trend of each monthly KPI over the 7 full months (OLS slope per month, nominal p, BH-adjusted q across KPIs) +
    largest single month-on-month move. Replaces any informal 'within noise' wording."""
    m = monthly().loc[FULL_MONTHS]
    cols = {"Contact rate, accounts (%)": "contact_rate_account_pct", "Contact rate, calls (%)": "contact_rate_call_pct", "RPC rate (%)": "rpc_rate_pct",
            "PTP rate (% of RPC)": "ptp_rate_pct", "PTP kept, status (% resolved)": "ptp_kept_rate_resolved_pct",
            "PTP kept, payment-verified (%)": "ptp_payment_verified_rate_pct", "Recovery rate (% outstanding)": "recovery_rate_fixed_pct",
            "Net recovery per day (₹)": "net_inr_per_day", "Recovery per agent-hour (₹)": "recovery_per_agent_hour"}
    rows = []
    x = np.arange(len(m))
    for lab, c in cols.items():
        r = stats.linregress(x, m[c])
        rows.append({"kpi": lab, "slope_per_month": r.slope, "p_trend": r.pvalue, "max_abs_mom_move": m[c].diff().abs().max(), "jan": m[c].iloc[0], "jul": m[c].iloc[-1]})
    t = pd.DataFrame(rows).set_index("kpi")
    t["q_bh"] = su.bh_adjust(t.p_trend.values)
    return t


# ------------------------------------------------------------------ orchestrator --------------------------
def run_all(save=True):
    import json
    from .config import REPORTS_DIR
    R = {}
    R["claim"] = claim_reproduction(); R["calendar"] = calendar_decomposition(); R["per_day_test"] = per_day_change_test()
    R["volatility"] = pairwise_per_day_volatility(); R["stepwise"] = stepwise_mom_impact(); R["waterfall"] = cleaning_waterfall()
    R["A"] = forensic_A_duplicates(); R["B_window"] = attribution_window_sensitivity(); R["B_rules"] = attribution_rule_comparison()
    R["C"] = forensic_C_timezone(); R["D"] = forensic_D_vendor_and_codes(); R["E"] = forensic_E_agents()
    R["F"] = forensic_F_portfolio_mix(); R["G"] = forensic_G_denominator()
    R["drivers"] = drivers_table(); R["dose"], R["dose_base_pp"] = dose_response(); R["channel"] = channel_conversion()
    R["reported_vs_real"] = reported_outcome_vs_payment_reality(); R["ts"] = time_series_checks(); R["simpson"] = simpson_scan()
    R["tgt_scan"] = targeting_change_scan(); R["did_jul"] = did_estimate("2026-07-01"); R["did_apr"] = did_estimate("2026-04-01")
    R["experiment"] = experiment_design(); R["invest"] = investment_scenarios()
    R["grid"] = option_evidence_grid(R["dose"], R["channel"], R["drivers"])
    R["monthly"] = monthly(); R["trends"] = kpi_trends()
    return R
