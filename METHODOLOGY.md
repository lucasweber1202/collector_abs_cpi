# ABS monthly CPI target collector — methodology

Authority: `guimasuko/collector_template` main `4bc65765cedd9c14aec196cff382df6dfb318c77`;
`AUD` is part of its `metadata.country` vocabulary and is what this collector
emits.

## Source

The latest monthly release page of
[Consumer Price Index, Australia](https://www.abs.gov.au/statistics/economy/price-indexes-and-inflation/consumer-price-index-australia/jul-2026)
is discovered by probing the four most recent months. From the page the
collector reads the **Released** date (e.g. 26/08/2026 for July 2026) and the
links to Table 3 (`640103.xlsx`) and Table 17 (`6401017.xlsx`). Both files are
checked before parsing: HTML/challenge pages are refused whatever their
`Content-Type`, the body must carry the XLSX `PK\x03\x04` magic and a plausible
size, and every `Data*` sheet must keep the audited ten-row header
(`Unit`, `Series Type`, `Data Type`, `Frequency`, …, `Series ID`). Layout drift
raises `SourceLayoutError` before any write.

## Series

`series_id = ABS_CPI_<ABS series ID>`, reversible with `parse_series_id`. Only
`Original` series for `Australia` (weighted average of eight capital cities).

| Family | Table | Count | Unit | Frequency |
| --- | --- | ---: | --- | --- |
| Index numbers: all groups, 11 groups, 33 sub-groups, 87 expenditure classes | 3 | 132 | `index` (Sep 2025 = 100) | monthly |
| Contribution to All groups CPI (index points), same 132 identities | 3 | 132 | `other` (index points) | monthly |
| All groups CPI, quarterly (`A2325846C`) | 17 | 1 | `index` | quarterly |

Percentage changes and changes in contribution are derived and not stored.
Month-start workbook dates are stored as month ends. July 2026 release: 265
series, 10,721 observations, September 1948 – July 2026. All groups
(`A130393720C`): May 102.09, June 102.03, July 103.07. The monthly all-groups
series starts April 2024; contributions start December 2024; the quarterly
series gives the long history. Default start date is 1948-01-01.

## Official weights in effect and target validation

ABS publishes, every month, the index-points contribution of each group,
sub-group and expenditure class to the all-groups index. That is the official
aggregation weight in effect (a component's contribution divided by the
all-groups index is its effective share), so it is stored as published rather
than derived. `scripts/validate.py` runs before the write transaction:

- the all-groups contribution equals the all-groups index (±0.005);
- the 11 group contributions add up to the all-groups index every month
  (±0.06; 20 months checked, largest gap 0.02 on the July 2026 release);
- from the September 2025 quarter (first full quarter of the complete monthly
  CPI) the quarterly all-groups equals the mean of its three monthly indexes
  (±0.011; 4 quarters, largest gap 0.007). Earlier quarters were compiled from
  the quarterly CPI and are not forced to match.

Hierarchy: the 11 groups are the first column carrying each official group
name. Sub-group/class parentage is not published as codes in these files and
is not inferred by name order (two names repeat across levels), so no
hierarchy table is stored.

## Release monitoring

`scripts/releases.py` classifies each workbook on every run from the page's
Released date and the latest covered period, compared with `metadata` before
the run, plus the rows changed: `first_release`, `same_release`,
`new_release`, `revised_source` or `layout_changed`. An unchanged rerun on a
later day is `same_release`; a Released date that goes backwards fails the run.

## Point in time

- `vintage_date` is the UTC collection date; a backfill is never dated to the
  reference month or the release date.
- `last_publish_date` is the page's Released date (previously the reference
  month end was used, which confused period and publication).
- ABS workbooks carry current revised history only. Earlier release vintages
  are not reconstructed. Later changes become new vintages; same-day changes
  overwrite that day's vintage (template rule).

## Verification (2026-09-27)

- PostgreSQL 16.13, live `main.py`: run 1 wrote 10,721 observations and 265
  metadata rows (`first_release`); run 2 wrote nothing (`same_release`).
- `tests/test_postgres_integration.py`: canonical tables, idempotent rerun,
  later-day vintage, same-day overwrite, metadata MERGE with NULL in every
  nullable column, time-series MERGE, run log, release classification.
- All emitted SQL parses with the Spark SQL grammar (pyspark 4.1.1).
  **Databricks corporate runtime: not verified.**

## Masuko authority verification

Pinned authority: `guimasuko/collector_template@4bc65765cedd9c14aec196cff382df6dfb318c77`. Physical `.github/` and `.vscode/` paths are checked against Git blobs. `.gitignore` and `scripts/databricks_engine.py` have no physical path in the template tree; they are canonical fenced blocks in `GUIDELINES.md` sections 8.1 and 8.9. The guideline Git blob is `089fbbca6a2241d3f02777b82631fbf81d49f6e0`; the two derived file blobs are `f0d1368264d24d7959d3137d618930a06f33795e` and `73821f7a530ab5cca2f5313180d71c17173e6e59`. `tests/test_architecture.py` checks all local blobs on every run. For independent source derivation, check out the exact authority commit and run `MASUKO_TEMPLATE_DIR=/path/to/collector_template python -m pytest -q tests/test_architecture.py`. This checks the guideline blob, extracts both fenced blocks and checks their hashes.
