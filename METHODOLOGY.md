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

## Official baskets, hierarchy and effective shares

`weight_sources.py` discovers the latest ABS annual weight update workbook.
Table 5 contains explicit group/subgroup/class label columns: these determine
parentage, including repeated labels, rather than guessing from series codes.
The stored `cpi_hierarchy` has 133 nodes (132 monthly indices and quarterly
headline). Every contribution identity is checked against its index identity.

`original_weights` preserves the seven published annual baskets (2019–2025,
917 cells) in percent, unchanged, with price-reference quarter and vintage.
The Table 3 contribution levels also remain unchanged in `time_series`.
`weights` stores closing-period component shares: contribution to all groups
of the child divided by the sum of its siblings' contributions. Siblings sum
to 1. Headlines carry weight 1 for every observed period. These are shares of
index contributions, **not coefficients for SUMPRODUCT of index levels**.
Within an unchanged basket, prior-period shares aggregate component index
relatives; closing-period shares reconstruct the parent relative through
`1 / SUM(weight(t) / (index(t)/index(t-1)))`. Reweighting/chain-link boundaries
must be handled using the original annual basket and published contributions.

Official contributions cover December 2024 onward. Earlier component shares
are not fabricated. Historical quarterly headline has no published child
indices in this selection and has weight 1. Validation checks all monthly
headline/group contributions (rounding tolerance 0.06), child contributions
at every hierarchy level (0.005 per rounded cell), and monthly/quarterly
headline linkage from September 2025 (tolerance 0.011).

`python -m scripts.export_validation_xlsx --output /path/validation.xlsx`
exports stored latest-vintage `time_series`, `weights`, `original_weights`
and `cpi_hierarchy`, one sheet per table; it never downloads a fresh release.
Use the hierarchy and raw contributions to audit aggregation and the baskets
to audit transformations; weights alone do not remove chain-link boundaries.

## Release monitoring

Empty headline history triggers immediate historical ingestion. Once populated,
the default waits for the next calendar month, polling every 30 seconds for up
to 900 seconds (`COLLECTOR_POLL_INTERVAL`, `COLLECTOR_MAX_WAIT`). A timeout is
normal and persists a success log. `--no-watch` or an explicit `--start-date`
forces a single pass. Existing release classification remains in place.

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
