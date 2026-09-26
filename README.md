# ABS monthly CPI target collector (work in progress)

Standalone Python 3.11 ingestion of source-original index levels from the official ABS monthly CPI Table 3 workbook. Dynamic release discovery; native ABS IDs; canonical metadata, time_series, logs and observation vintages.

Run with `COLLECTOR_DB_URL=postgresql+psycopg2://... python main.py`, or configure `PROD=true` and Databricks variables. `ABS_LIVE_SMOKE=1 pytest` checks the official workbook. See METHODOLOGY.md for coverage and target gaps.
