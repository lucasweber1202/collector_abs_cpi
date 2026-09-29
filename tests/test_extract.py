"""ABS identities, release page, payload checks, parsing and the live release."""

from __future__ import annotations

import os
from datetime import date

import httpx
import pytest

from scripts.extract import (
    SourceAccessError,
    SourceLayoutError,
    build_series_id,
    check_payload,
    collect,
    parse_release_page,
    parse_series_id,
    parse_workbook,
)
from tests.abs_workbook import table3, table17

PAGE = (
    '<a href="/statistics/x/jul-2026/640103.xlsx">t3</a><a href="/statistics/x/jul-2026/6401017.xlsx">t17</a>'
    '<div class="field__label">Released</div><div class="field__item"> 26/08/2026</div>'
)


def test_id_roundtrip() -> None:
    assert parse_series_id(build_series_id("A130393720C")) == "A130393720C"
    assert parse_series_id(build_series_id("A2325846C")) == "A2325846C"
    with pytest.raises(ValueError):
        build_series_id("All groups")


def test_release_date_comes_from_the_page_not_the_reference_month() -> None:
    release = parse_release_page(PAGE, "https://www.abs.gov.au/p", date(2026, 7, 31))
    assert release.published == date(2026, 8, 26)
    assert release.reference_month == date(2026, 7, 31)
    assert release.table3_url == "https://www.abs.gov.au/statistics/x/jul-2026/640103.xlsx"
    with pytest.raises(SourceLayoutError):
        parse_release_page(PAGE.replace("Released", "Issued"), "p", date(2026, 7, 31))


def test_parse_keeps_index_and_contribution_but_not_percent_changes() -> None:
    data = parse_workbook(table3(), "https://www.abs.gov.au/t3.xlsx", date(2026, 8, 26))
    assert build_series_id("A130393721F") not in data.catalog
    headline = data.catalog[build_series_id("A130393720C")]
    contribution = data.catalog[build_series_id("A130393723K")]
    assert (headline["unit"], headline["frequency"], headline["country"]) == (
        "index",
        "monthly",
        "AUD",
    )
    assert contribution["unit"] == "other" and "Index Points" in contribution["description"]
    assert headline["last_publish_date"] == date(2026, 8, 26)
    first = min(o.reference_date for o in data.observations)
    assert first == date(2024, 12, 31)  # month-start dates map to month ends


def test_table17_keeps_only_the_australian_all_groups_quarterly() -> None:
    data = parse_workbook(
        table17({date(1948, 9, 1): 2.6, date(2026, 6, 1): 102.31}), "u", date(2026, 8, 26), "17"
    )
    assert list(data.catalog) == [build_series_id("A2325846C")]
    assert data.catalog[build_series_id("A2325846C")]["frequency"] == "quarterly"
    assert {o.reference_date for o in data.observations} == {date(1948, 9, 30), date(2026, 6, 30)}


def test_missing_all_groups_is_a_layout_error() -> None:
    with pytest.raises(SourceLayoutError):
        parse_workbook(table17({date(2026, 6, 1): 1.0}), "u", date(2026, 8, 26), "3")


def _response(body: bytes, content_type: str) -> httpx.Response:
    return httpx.Response(
        200,
        content=body,
        headers={"content-type": content_type},
        request=httpx.Request("GET", "https://www.abs.gov.au/f.xlsx"),
    )


def test_payload_check_rejects_html_and_non_xlsx() -> None:
    with pytest.raises(SourceAccessError, match="HTML"):
        check_payload(_response(b"<!DOCTYPE html><title>blocked</title>" * 3000, "text/html"))
    with pytest.raises(SourceAccessError, match="not an XLSX"):
        check_payload(_response(b"x" * 60000, "application/octet-stream"))
    with pytest.raises(SourceAccessError, match="small"):
        check_payload(
            _response(
                b"PK\x03\x04tiny",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        )


@pytest.mark.skipif(os.getenv("ABS_LIVE_SMOKE") != "1", reason="opt-in source test")
def test_live_release() -> None:
    from scripts.validate import validate_release

    result = collect()
    points = {
        o.reference_date: o.value
        for o in result.observations
        if o.series_id == build_series_id("A130393720C")
    }
    assert points[date(2026, 7, 31)] == 103.07
    assert points[date(2026, 6, 30)] == 102.03
    quarterly = {
        o.reference_date: o.value
        for o in result.observations
        if o.series_id == build_series_id("A2325846C")
    }
    assert min(quarterly) == date(1948, 9, 30)
    assert len(result.catalog) >= 250
    assert {e.published for e in result.releases} == {date(2026, 8, 26)}
    report = validate_release(result)
    assert report.max_group_gap <= 0.06 and report.quarters_linked >= 4
