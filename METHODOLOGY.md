# Official ABS CPI monthly index levels

The source is [ABS CPI Table 3](https://www.abs.gov.au/statistics/economy/price-indexes-and-inflation/consumer-price-index-australia/jul-2026), discovered in the latest monthly release and downloaded as `640103.xlsx`. Only original monthly `Index Numbers` / `INDEX` columns are retained. Percentage changes and index point contributions are excluded. Series IDs embed native ABS time-series IDs. Month-start dates in the workbook map to their month-end reference dates without moving the economic period.

At July 2026: 132 series, 7,769 observations, September 2017–July 2026. All-groups ID `A130393720C`: May 102.09, June 102.03, July 103.07. The all-groups monthly series begins April 2024, while many components begin September 2017. The September 2025=100 re-reference and previous quarterly history require explicit reconciliation; current source does not provide historical publication vintages.

**Draft gate:** This is index ingestion, not a complete forecast target. Official weights, hierarchy map, quarterly linkage/rebasing, aggregation checks, validation workbook, release monitoring, PostgreSQL integration, and corporate Databricks runtime remain outstanding. AUD vocabulary awaits upstream template PR #1.
