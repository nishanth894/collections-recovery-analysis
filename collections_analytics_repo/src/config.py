"""Central configuration. All paths relative to repo root."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data_raw"            # NEVER committed (see .gitignore)
DB_PATH = ROOT / "data" / "db" / "collections.sqlite"
GOLDEN_DIR = ROOT / "data" / "golden"  # derived, row-level -> not committed
REPORTS_DIR = ROOT / "reports"
FIG_DIR = REPORTS_DIR / "figures"
SQL_DIR = ROOT / "sql"

# Analysis window (IST). Last timestamp present across event tables is 2026-08-08.
WINDOW_START = "2026-01-01 00:00:00"
WINDOW_END = "2026-08-08 23:59:59"
PARTIAL_MONTH = "2026-08"              # only 8 days observed -> excluded from MoM comparisons
ATTRIBUTION_WINDOW_DAYS = 7            # default; sensitivity tested in analysis
RAW_TABLES = [
    "accounts", "account_status_history", "agent_sessions", "agents", "borrowers",
    "call_attempts", "call_dispositions", "calls", "campaigns", "complaints",
    "daily_targeting", "field_visits", "payments", "promises_to_pay",
    "sms_events", "vendor_telephony", "whatsapp_events",
]
# SQL executed in this order by src/run_pipeline.py
PIPELINE_SQL = [
    "01_staging.sql", "02_clean.sql", "03_golden.sql",
    "04_features.sql", "05_metrics.sql", "06_reconciliation.sql",
]
