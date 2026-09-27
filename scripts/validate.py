"""Validate the official ABS CPI release before any of it is persisted.

Checks use only published ABS figures and fail the run before the write
transaction:

* the all-groups index-points contribution equals the all-groups index;
* the contributions of the 11 CPI groups add up to the all-groups index within
  publication rounding (each is published to two decimals), every month;
* from the September 2025 quarter -- the first full quarter of the complete
  monthly CPI -- the quarterly all-groups index (Table 17) equals the mean of
  its three monthly indexes (Table 3) within rounding.

Groups are the first Table 3 column carrying each of the 11 official group
names; ABS lists each group before its sub-groups, and two groups
(Communication, Education) share their name with a lower-level series.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date

from scripts.extract import MONTHLY_ALL_GROUPS, QUARTERLY_ALL_GROUPS, SourceData, build_series_id

logger = logging.getLogger(__name__)
GROUPS = (
    "Food and non-alcoholic beverages",
    "Alcohol and tobacco",
    "Clothing and footwear",
    "Housing",
    "Furnishings, household equipment and services",
    "Health",
    "Transport",
    "Communication",
    "Recreation and culture",
    "Education",
    "Insurance and financial services",
)
SUFFIX = ": contribution to All groups CPI"
GROUP_SUM_TOLERANCE = 0.06  # 11 values rounded to 0.005, plus the total's own rounding
IDENTITY_TOLERANCE = 0.005
LINKAGE_TOLERANCE = 0.011
LINKAGE_FROM = date(2025, 9, 30)


class TargetValidationError(ValueError):
    """The release breaks a validated target invariant."""


@dataclass(frozen=True)
class ValidationReport:
    months_checked: int
    max_group_gap: float
    quarters_linked: int
    max_linkage_gap: float


def _group_contributions(data: SourceData) -> dict[str, str]:
    found: dict[str, str] = {}
    for sid, entry in data.catalog.items():  # catalogue order is workbook column order
        name = str(entry["name"])
        if name.endswith(SUFFIX):
            group = name.removesuffix(SUFFIX)
            if group in GROUPS and group not in found:
                found[group] = sid
    missing = sorted(set(GROUPS) - set(found))
    if missing:
        raise TargetValidationError(f"Group contributions missing: {missing}")
    return found


def validate_release(data: SourceData) -> ValidationReport:
    values = {(o.series_id, o.reference_date): o.value for o in data.observations}
    headline = build_series_id(MONTHLY_ALL_GROUPS)
    total = next(
        (sid for sid, e in data.catalog.items() if e["name"] == "All groups CPI" + SUFFIX), None
    )
    if total is None:
        raise TargetValidationError("All-groups contribution series missing")
    groups = _group_contributions(data)
    months = sorted(d for (sid, d) in values if sid == total)
    worst = 0.0
    for month in months:
        index = values.get((headline, month))
        if index is None or abs(values[(total, month)] - index) > IDENTITY_TOLERANCE:
            raise TargetValidationError(f"All-groups contribution {values[(total, month)]} != index {index} at {month}")
        try:
            gap = abs(sum(values[(sid, month)] for sid in groups.values()) - index)
        except KeyError as exc:
            raise TargetValidationError(f"Group contribution missing at {month}: {exc}") from exc
        worst = max(worst, gap)
        if gap > GROUP_SUM_TOLERANCE:
            raise TargetValidationError(f"Group contributions miss all groups by {gap:.3f} at {month}")
    quarterly = build_series_id(QUARTERLY_ALL_GROUPS)
    linked = 0
    worst_link = 0.0
    for (sid, quarter), value in sorted(values.items()):
        if sid != quarterly or quarter < LINKAGE_FROM:
            continue
        months_in = [date(quarter.year, quarter.month - k, 1) for k in (2, 1, 0)]
        monthly = [v for (s, d), v in values.items() if s == headline and (d.year, d.month) in {(m.year, m.month) for m in months_in}]
        if len(monthly) != 3:
            continue
        gap = abs(sum(monthly) / 3 - value)
        worst_link = max(worst_link, gap)
        linked += 1
        if gap > LINKAGE_TOLERANCE:
            raise TargetValidationError(f"Quarterly CPI {value} is not the monthly mean at {quarter} (gap {gap:.3f})")
    if not months or not linked:
        raise TargetValidationError("Nothing to validate: contributions or linkage quarters missing")
    report = ValidationReport(len(months), worst, linked, worst_link)
    logger.info("Target validation: %s", report)
    return report
