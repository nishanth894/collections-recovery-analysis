"""Validation + reconciliation tests. Run AFTER `python -m src.run_pipeline` and `python -m src.build_reports`.
   python -m unittest discover -s tests -v"""
import json, sqlite3, unittest
import numpy as np
import pandas as pd
from src.config import DB_PATH, RAW_DIR, REPORTS_DIR, ROOT, RAW_TABLES
from src.load_raw import sha256

OFF = {"Asia/Kolkata": 330, "Asia/Dubai": 240, "UTC": 0}
FULL = ["2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06", "2026-07"]


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.con = sqlite3.connect(DB_PATH)

    def q(self, s):
        return pd.read_sql(s, self.con)


class TestRawImmutability(Base):
    def test_raw_files_match_manifest(self):
        man = json.loads((REPORTS_DIR / "raw_manifest.json").read_text())
        for f, v in man.items():
            self.assertEqual(sha256(RAW_DIR / f), v["sha256"], f"{f} changed since load")

    def test_raw_tables_in_db_equal_csv_rowcounts(self):
        for t in RAW_TABLES:
            n = self.con.execute(f"select count(*) from raw_{t}").fetchone()[0]
            self.assertEqual(n, len(pd.read_csv(RAW_DIR / f"{t}.csv")), t)


class TestConservationAndKeys(Base):
    def test_row_conservation(self):
        r = self.q("select * from recon_row_counts")
        bad = r[r.raw_rows != r.clean_rows + r.rejected_rows]
        self.assertTrue(bad.empty, bad.to_string())

    def test_primary_keys_unique(self):
        for tbl, key in [("fact_payment", "payment_id"), ("fact_call", "call_id"), ("dim_account", "account_id"), ("dim_agent", "agent_id"),
                         ("fact_attempt", "attempt_id"), ("fact_disposition", "disposition_id"), ("fact_ptp", "ptp_id"),
                         ("fact_field_visit", "visit_id"), ("fact_session", "session_id"), ("fact_targeting", "target_id"),
                         ("fact_complaint", "complaint_id"), ("dim_campaign", "campaign_id"), ("dim_vendor", "vendor_id")]:
            n, u = self.con.execute(f"select count(*), count(distinct {key}) from {tbl}").fetchone()
            self.assertEqual(n, u, f"{tbl}.{key} not unique")

    def test_foreign_keys(self):
        for tbl in ["fact_payment", "fact_call", "fact_attempt", "fact_disposition", "fact_ptp", "fact_message", "fact_field_visit", "fact_targeting", "fact_touch"]:
            n = self.con.execute(f"select count(*) from {tbl} where account_id not in (select account_id from dim_account)").fetchone()[0]
            self.assertEqual(n, 0, tbl)
        n = self.con.execute("select count(*) from fact_call where agent_key not in (select agent_id from dim_agent)").fetchone()[0]
        self.assertEqual(n, 0)
        n = self.con.execute("select count(*) from fact_call where vendor_id not in (select vendor_id from dim_vendor)").fetchone()[0]
        self.assertEqual(n, 0)

    def test_no_pii_in_golden(self):
        for t in ["dim_account", "dim_agent", "fact_payment", "fact_call"]:
            cols = [c[1].lower() for c in self.con.execute(f"pragma table_info({t})")]
            for pii in ("name", "phone", "email", "agent_name", "borrower_name"):
                self.assertNotIn(pii, cols, f"{t} exposes {pii}")

    def test_known_dq_counts(self):
        dq = self.q("select issue_id, rows_affected from dq_issue_log").set_index("issue_id").rows_affected
        self.assertEqual(dq["DQ-01"], 500); self.assertEqual(dq["DQ-07"], 1350); self.assertEqual(dq["DQ-19"], 600)
        self.assertEqual(dq["DQ-17"], 29000)


class TestFinancialReconciliation(Base):
    def test_waterfall_ties_out(self):
        w = self.q("select * from recon_recovery_waterfall order by step")
        self.assertAlmostEqual(w.delta_inr.iloc[0] + w.delta_inr.iloc[1:5].sum(), w.running_inr.iloc[5], places=2)

    def test_raw_to_golden_success_reconciles(self):
        raw = pd.read_csv(RAW_DIR / "payments.csv")
        succ_raw = raw.loc[raw.payment_status == "SUCCESS", "amount"].sum()
        dup_succ = self.q("""select sum(s.amount) x from stg_payments s join rejects r on r.src_table='payments' and r.raw_row_id=s.raw_row_id
                             where s.payment_status='SUCCESS'""").x[0]
        gold = self.q("select sum(amount) x from fact_payment where is_success=1").x[0]
        self.assertAlmostEqual(succ_raw - dup_succ, gold, places=2)

    def test_monthly_sums_equal_total(self):
        tot = self.q("select sum(amount) x from fact_payment where is_recovery=1").x[0]
        m = self.q("select sum(net_inr) x from metrics_monthly").x[0]
        self.assertAlmostEqual(tot, m, places=2)

    def test_independent_pandas_recovery_by_month(self):
        pay = pd.read_csv(RAW_DIR / "payments.csv", parse_dates=["event_at"])
        acc = pd.read_csv(RAW_DIR / "accounts.csv")
        p = pay.drop_duplicates("payment_id")
        p = p[(p.payment_status == "SUCCESS") & (p.event_at >= "2026-01-01") & (p.event_at < "2026-08-09")]
        p = p.merge(acc[["account_id", "dpd"]], on="account_id")
        p = p[p.dpd >= 1]
        exp = p.groupby(p.event_at.dt.strftime("%Y-%m")).amount.sum()
        got = self.q("select report_month, net_inr from metrics_monthly").set_index("report_month").net_inr
        for m in exp.index:
            self.assertAlmostEqual(exp[m], got[m], places=1, msg=m)

    def test_independent_pandas_contact_rate(self):
        c = pd.read_csv(RAW_DIR / "calls.csv", parse_dates=["event_at"])
        c["utc"] = c.event_at - pd.to_timedelta(c.timezone.map(OFF), unit="m")
        c["ist"] = c.utc + pd.Timedelta(minutes=330)
        c = c.sort_values(["call_id", "utc"]).drop_duplicates("call_id")
        c = c[(c.direction == "OUTBOUND") & (c.ist >= "2026-01-01") & (c.ist < "2026-08-09")]
        exp = c.groupby(c.ist.dt.strftime("%Y-%m")).apply(lambda g: (g.call_status == "ANSWERED").mean() * 100)
        got = self.q("select report_month, contact_rate_call_pct from metrics_monthly").set_index("report_month").contact_rate_call_pct
        for m in FULL:
            self.assertAlmostEqual(exp[m], got[m], places=6, msg=m)

    def test_independent_pandas_ptp_kept_rate(self):
        p = pd.read_csv(RAW_DIR / "promises_to_pay.csv", parse_dates=["event_at"])
        exp = p.groupby(p.event_at.dt.strftime("%Y-%m")).apply(lambda g: (g.status == "KEPT").sum() / ((g.status == "KEPT") | (g.status == "BROKEN")).sum() * 100)
        got = self.q("select report_month, ptp_kept_rate_resolved_pct from metrics_monthly").set_index("report_month").ptp_kept_rate_resolved_pct
        for m in FULL:
            self.assertAlmostEqual(exp[m], got[m], places=6, msg=m)

    def test_no_duplicate_payment_ids_and_reference_collisions_kept(self):
        self.assertEqual(self.con.execute("select count(*)-count(distinct payment_id) from clean_payments").fetchone()[0], 0)
        self.assertGreater(self.con.execute("select sum(ref_collision_flag) from clean_payments").fetchone()[0], 0)  # not treated as dups


class TestMetricIdentities(Base):
    def test_calendar_identity(self):
        m = self.q("select * from metrics_monthly").set_index("report_month")
        tot = m.loc["2026-03", "net_inr"] / m.loc["2026-02", "net_inr"]
        cal = 31 / 28
        pd_ = m.loc["2026-03", "net_inr_per_day"] / m.loc["2026-02", "net_inr_per_day"]
        self.assertAlmostEqual(tot, cal * pd_, places=9)

    def test_rates_bounded(self):
        m = self.q("select * from metrics_monthly where is_partial=0")
        for c in ["contact_rate_call_pct", "contact_rate_account_pct", "rpc_rate_pct", "ptp_rate_pct", "ptp_kept_rate_resolved_pct"]:
            self.assertTrue(m[c].between(0, 100).all(), c)

    def test_pp_vs_pct_view(self):
        v = self.q("select * from metrics_mom where report_month='2026-03'").iloc[0]
        m = self.q("select * from metrics_monthly").set_index("report_month")
        self.assertAlmostEqual(v.recovery_rate_mom_pp, round(m.loc["2026-03", "recovery_rate_fixed_pct"] - m.loc["2026-02", "recovery_rate_fixed_pct"], 4), places=4)


class TestDashboardMatchesSQL(Base):
    def test_dashboard_numbers(self):
        D = json.loads((REPORTS_DIR / "dashboard_data.json").read_text())
        m = self.q("select * from metrics_monthly").set_index("report_month").loc[FULL]
        self.assertEqual(D["net_cr"], (m.net_inr / 1e7).round(2).tolist())
        self.assertEqual(D["per_day_lakh"], (m.net_inr_per_day / 1e5).round(2).tolist())
        w = self.q("select * from recon_recovery_waterfall order by step")
        self.assertAlmostEqual(D["golden_total_cr"], w.running_inr.iloc[5] / 1e7, places=2)
        self.assertAlmostEqual(D["golden_total_feb_mar_pct"], (m.loc["2026-03", "net_inr"] / m.loc["2026-02", "net_inr"] - 1) * 100, places=2)
        html = (REPORTS_DIR / "dashboard.html").read_text()
        self.assertIn(f"{D['golden_total_feb_mar_pct']:+.1f}%", html)
        self.assertIn(f"{D['golden_per_day_feb_mar_pct']:+.1f}%", html)

    def test_dashboard_matches_notebook_pickle(self):
        import pickle
        R = pickle.load(open(REPORTS_DIR / ".results.pkl", "rb"))
        D = json.loads((REPORTS_DIR / "dashboard_data.json").read_text())
        self.assertAlmostEqual(D["break_even_uplift_pct"], R["invest"]["break_even_uplift_pct_100"], places=2)


class TestAnalysisSQL(Base):
    def test_all_analysis_sql_executes_and_matches(self):
        from src.config import SQL_DIR
        for f in sorted((SQL_DIR / "analysis").glob("*.sql")):
            df = self.q(f.read_text()); self.assertGreater(len(df), 0, f.name)
        c = self.q((SQL_DIR / "analysis" / "10_claim_reproduction.sql").read_text()).set_index("report_month")
        m = self.q("select * from metrics_monthly").set_index("report_month")
        self.assertAlmostEqual(c.loc["2026-03", "golden_per_day_mom_pct"], round((m.loc["2026-03", "net_inr_per_day"] / m.loc["2026-02", "net_inr_per_day"] - 1) * 100, 2), places=2)
        self.assertAlmostEqual(c.loc["2026-03", "raw_success_mom_pct"], 10.99, places=2)

    def test_dq_monitoring_checks_clean(self):
        from src.config import SQL_DIR
        d = self.q((SQL_DIR / "analysis" / "15_dq_monitoring_checks.sql").read_text())
        blockers = d[(d.severity == "BLOCK") & (d.violations > 0)]
        self.assertTrue(blockers.empty, blockers.to_string())


class TestRepoHygiene(unittest.TestCase):
    def test_raw_data_is_gitignored(self):
        gi = (ROOT / ".gitignore").read_text()
        for pat in ("data_raw/", "data/"):
            self.assertIn(pat, gi)


if __name__ == "__main__":
    unittest.main()
