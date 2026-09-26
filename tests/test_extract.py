"""Source-based checks for ABS CPI identities and index levels."""
from __future__ import annotations

import os
from datetime import date

import httpx
import pytest

from scripts.extract import build_series_id, collect, discover_workbook, parse_series_id


def test_id_roundtrip() -> None:
    assert parse_series_id(build_series_id("A130393720C")) == "A130393720C"
    with pytest.raises(ValueError):
        build_series_id("All groups")


@pytest.mark.skipif(os.getenv("ABS_LIVE_SMOKE") != "1", reason="opt-in source test")
def test_live_all_groups_and_discovery() -> None:
    with httpx.Client(timeout=30) as client:
        url, period = discover_workbook(client, date(2026, 9, 26))
    assert url.endswith("/640103.xlsx") and period == date(2026, 7, 31)
    result = collect()
    points = {o.reference_date: o.value for o in result.observations if o.series_id == build_series_id("A130393720C")}
    assert points[date(2026, 7, 31)] == 103.07
    assert len(result.catalog) >= 100
