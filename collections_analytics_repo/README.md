# Collections analytics — "Is the +11% month-on-month recovery claim real?"

**Answer: no.** The +11% is reproduced by summing raw SUCCESS payment rows Feb→Mar (+11.0%), but March has 31 days vs February's 28 (+10.7% from the calendar alone).
On cleaned data, **recovery per observed day changed −0.2%** (95% CI −6.7% … +6.7%). Duplicate payments overstate recovery by 1.9%; non-settled rows and payments on current accounts make raw payment totals ₹191.7 Cr vs ₹119.8 Cr of true net recovery.
**₹10 Cr recommendation:** better borrower targeting, released in tranches behind a randomised holdout (break-even = +5.0% recovery on a ₹199 Cr/yr run-rate; effect not estimable from current data).
Read `reports/executive_memo.pdf` (2 pages) and open `reports/dashboard.html`.

## Repository layout
```
src/            load_raw.py  run_pipeline.py  analysis.py  stats_utils.py  build_reports.py  dq_report.py  memo.py  config.py
sql/            01_staging … 06_reconciliation.sql   (pipeline, executed in order)   analysis/*.sql (analytical + DQ-monitoring queries)
notebooks/      analysis_notebook.py (source)  build_notebook.py  analysis.ipynb (executed, outputs embedded)
tests/          test_pipeline.py (22 reconciliation/validation tests)  test_stats_utils.py (6 unit tests)
reports/        executive_memo.pdf  dashboard.html/.png  data_quality_report.md  architecture.png/.svg  result_*.csv  figures/
docs/           metric_definitions.md  assumptions.md  architecture.md  architecture.dot
data_raw/       ← NOT committed: place the 17 CSVs here          data/ ← derived DB + golden CSVs, NOT committed (.gitignore)
```

## Setup & run (Python ≥3.10, SQLite ≥3.35, graphviz `dot` for the diagram)
```bash
pip install -r requirements.txt
unzip collections_30k_dataset.zip -d data_raw/        # raw data stays local; never commit it
make all          # = pipeline + reports + notebook + test   (≈4 min)
# or step by step
python -m src.run_pipeline                    # Raw→Staging→Clean→Golden→Feature→Metrics, exports data/golden/*.csv   (~25 s)
python -m src.build_reports                   # runs all analyses; dashboard, figures, result_*.csv, architecture diagram  (~2 min)
python -m src.dq_report && python -m src.memo # data_quality_report.md, executive_memo.pdf
python notebooks/build_notebook.py            # executes the notebook -> notebooks/analysis.ipynb
python -m unittest discover -s tests -v       # 28 tests
```
Open `notebooks/analysis.ipynb` in Jupyter to re-run interactively (`analysis_notebook.py` is the source in percent format).

## Golden dataset
`data/golden/*.csv` (and tables in `data/db/collections.sqlite`): `dim_account, dim_agent, dim_campaign, dim_vendor, dim_month, fact_payment, fact_call, fact_attempt, fact_disposition, fact_ptp, fact_message, fact_field_visit, fact_session, fact_targeting, fact_complaint, fact_touch`, features (`ft_*`), `metrics_monthly`, `rejects`, `dq_issue_log`, reconciliation tables. PII (names, phones, emails) is **not** carried into golden.

## Method in one paragraph
Raw is loaded unchanged as text (SHA-256 manifest). SQL layers type and time-normalise, deduplicate with reason-coded rejects (raw = golden + rejected, tested), build conformed facts on `account_id` (the only valid join key), and compute metrics with explicit numerator/denominator/eligibility. Analyses use transparent methods only: chi-square/overdispersion tests with Benjamini–Hochberg correction, within-account fixed-effects dose-response, placebo-randomised attribution, shift-share mix decomposition, permutation change-point scan, difference-in-differences as a diagnostic, and power calculations for the proposed experiment.

## Key assumptions & limitations (full list: `docs/assumptions.md`)
Data cover 1 Jan–8 Aug 2026 (not 12 months) · timestamps without a timezone column assumed IST (robustness tested) · no cost, client, language or agentic-voice data → cost per ₹ and those drivers are *not computable* · agent identity and the call↔attempt↔disposition links are unreliable · many fields behave like independent random draws, so "no effect" means "no *detectable* effect" · the strategy-change effect is **not identifiable** (design: randomised holdout, see memo).

## Data protection
`data_raw/`, `data/` and DB files are git-ignored (tested). Publish only code, SQL, docs and the aggregate `reports/` outputs, and only after authorisation.
