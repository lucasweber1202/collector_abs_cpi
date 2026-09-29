"""ABS target invariants on synthetic workbooks in the official layout."""

from __future__ import annotations

from datetime import date

import pytest

from scripts.extract import SourceData, parse_workbook
from scripts.validate import TargetValidationError, validate_release
from tests.abs_workbook import table3, table17


def _data(shift: float = 0.0, quarterly_gap: float = 0.0) -> SourceData:
    monthly = parse_workbook(table3(shift=shift), "u", date(2026, 8, 26))
    headline = {
        o.reference_date: o.value
        for o in monthly.observations
        if o.series_id == "ABS_CPI_A130393720C"
    }
    quarters: dict[date, float] = {}
    for q in (date(2025, 9, 30), date(2025, 12, 31), date(2026, 3, 31), date(2026, 6, 30)):
        months = [
            v for d, v in headline.items() if d.year == q.year and q.month - 2 <= d.month <= q.month
        ]
        quarters[date(q.year, q.month, 1)] = round(sum(months) / 3, 2) + quarterly_gap
    quarterly = parse_workbook(table17(quarters), "u", date(2026, 8, 26), "17")
    return SourceData(
        monthly.observations + quarterly.observations, monthly.catalog | quarterly.catalog
    )


def test_consistent_release_passes() -> None:
    report = validate_release(_data())
    assert report.months_checked == 20 and report.quarters_linked == 4


def test_group_contributions_that_do_not_add_up_fail() -> None:
    with pytest.raises(TargetValidationError, match="Group contributions"):
        validate_release(_data(shift=0.2))


def test_quarterly_that_is_not_the_monthly_mean_fails() -> None:
    with pytest.raises(TargetValidationError, match="monthly mean"):
        validate_release(_data(quarterly_gap=0.05))
