PY ?= python3
.PHONY: all data pipeline reports notebook test clean
all: pipeline reports notebook test
data:            ## place the 17 CSVs in data_raw/ (unzip collections_30k_dataset.zip there)
	@test -f data_raw/payments.csv || (echo "put raw CSVs in data_raw/" && exit 1)
pipeline: data   ## Raw -> Staging -> Clean -> Golden -> Feature -> Metrics (+ golden CSV export)
	$(PY) -m src.run_pipeline
reports:         ## analysis, dashboard, architecture diagram, DQ report, memo
	$(PY) -m src.build_reports && $(PY) -m src.dq_report && $(PY) -m src.memo
notebook:
	$(PY) notebooks/build_notebook.py
test:
	$(PY) -m unittest discover -s tests -v
clean:
	rm -rf data/db data/golden reports/.results.pkl
