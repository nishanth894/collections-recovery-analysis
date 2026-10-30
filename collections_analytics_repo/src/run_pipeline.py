"""Raw -> Staging -> Clean -> Golden -> Feature -> Metrics (+ reconciliation). Usage: python -m src.run_pipeline"""
import sqlite3, time
import pandas as pd
from .config import DB_PATH, SQL_DIR, PIPELINE_SQL, GOLDEN_DIR, REPORTS_DIR
from .load_raw import load_raw

GOLDEN_TABLES = ["dim_account", "dim_agent", "dim_campaign", "dim_vendor", "dim_month", "fact_payment", "fact_call", "fact_attempt",
                 "fact_disposition", "fact_ptp", "fact_message", "fact_field_visit", "fact_session", "fact_targeting", "fact_complaint",
                 "fact_touch", "ft_payment_attribution", "ft_account_month", "metrics_monthly", "recon_row_counts",
                 "recon_recovery_waterfall", "dq_issue_log", "rejects"]


def run_sql_file(con, path):
    buf = ""
    for line in path.read_text().splitlines(keepends=True):
        buf += line
        if sqlite3.complete_statement(buf):
            st, buf = buf.strip(), ""
            if st and not all((not l.strip()) or l.strip().startswith("--") for l in st.splitlines()):
                con.execute(st)
    con.commit()


def run(export=True, verbose=True):
    t0 = time.time()
    load_raw()
    con = sqlite3.connect(DB_PATH)
    for f in PIPELINE_SQL:
        t = time.time(); run_sql_file(con, SQL_DIR / f)
        if verbose: print(f"  {f:24s} {time.time()-t:5.1f}s")
    if export:
        GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
        for t in GOLDEN_TABLES:
            pd.read_sql(f"select * from {t}", con).to_csv(GOLDEN_DIR / f"{t}.csv", index=False)
        REPORTS_DIR.mkdir(exist_ok=True)
        pd.read_sql("select * from dq_issue_log", con).to_csv(REPORTS_DIR / "dq_issue_log.csv", index=False)
        pd.read_sql("select * from recon_row_counts", con).to_csv(REPORTS_DIR / "recon_row_counts.csv", index=False)
        pd.read_sql("select * from recon_recovery_waterfall", con).to_csv(REPORTS_DIR / "recon_recovery_waterfall.csv", index=False)
        pd.read_sql("select * from metrics_monthly", con).to_csv(REPORTS_DIR / "metrics_monthly.csv", index=False)
    con.close()
    if verbose: print(f"pipeline complete in {time.time()-t0:.1f}s -> {DB_PATH}")


if __name__ == "__main__":
    run()
