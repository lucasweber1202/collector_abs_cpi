# ABS monthly CPI target collector

Standalone Python 3.11 collector of the official ABS monthly CPI (Table 3:
index numbers and index-points contributions for all 132 groups, sub-groups and
expenditure classes) plus the quarterly all-groups CPI back to 1948 (Table 17).
Dynamic release discovery, native ABS IDs, target validation before writing,
release monitoring, canonical `metadata`, `time_series` and `logs`.

Run with `COLLECTOR_DB_URL=postgresql+psycopg2://... python main.py`, or set
`PROD=true` and the Databricks variables. Tests: `pytest` (Spark grammar needs
`java`); `COLLECTOR_TEST_PG_URL=<disposable PostgreSQL>` enables the PostgreSQL
write-path tests and `ABS_LIVE_SMOKE=1` the live official release check. See
METHODOLOGY.md.
