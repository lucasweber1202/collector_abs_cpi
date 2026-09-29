"""Official ABS CPI from the current monthly release workbooks.

Table 3 (``640103.xlsx``) supplies the monthly index numbers and the official
index-points contribution of every group, sub-group and expenditure class to
the all-groups index. Table 17 (``6401017.xlsx``) supplies the quarterly
all-groups index for Australia back to 1948. Percentage changes and changes in
contribution are derived series and are not stored.
"""

from __future__ import annotations

import calendar
import hashlib
import html
import io
import logging
import math
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any
from urllib.parse import urljoin

import httpx
import openpyxl

from scripts.config import REQUEST_TIMEOUT, USER_AGENT
from scripts.releases import ReleaseEvidence
from scripts.time_series import Observation

# Canonical metadata vocabulary produced by this source.
FREQUENCIES: frozenset[str] = frozenset({"monthly", "quarterly"})
UNITS: frozenset[str] = frozenset({"index", "other"})
ECO_GROUPS: frozenset[str] = frozenset({"consumer_prices"})


logger = logging.getLogger(__name__)
ROOT = "https://www.abs.gov.au"
RELEASE_ROOT = (
    ROOT + "/statistics/economy/price-indexes-and-inflation/consumer-price-index-australia"
)
NATIVE_ID = re.compile(r"A[0-9]{7,9}[A-Z]")
MONTHLY_ALL_GROUPS = "A130393720C"
QUARTERLY_ALL_GROUPS = "A2325846C"
MIN_HISTORY_MONTHS = 18
MAX_STALE_MONTHS = {"monthly": 3, "quarterly": 6}
MIN_PAYLOAD_BYTES = 50_000
HEADER_LABELS = ("Unit", "Series Type", "Data Type", "Frequency")
INDEX_PREFIX = "Index Numbers ;"
CONTRIBUTION_PREFIX = "Contribution to All groups CPI Index Number ;"
FREQ_MAP = {"Month": "monthly", "Quarter": "quarterly"}


class SourceLayoutError(ValueError):
    """The ABS release page or workbook no longer has the audited layout."""


class SourceAccessError(RuntimeError):
    """The source answered with something other than the requested file."""


@dataclass(frozen=True)
class Release:
    """Official identity of one monthly CPI release, read from its page."""

    page_url: str
    published: date
    reference_month: date
    table3_url: str
    table17_url: str


@dataclass(frozen=True)
class SourceData:
    observations: list[Observation]
    catalog: dict[str, dict[str, Any]]
    releases: tuple[ReleaseEvidence, ...] = ()


def build_series_id(native: str) -> str:
    if not NATIVE_ID.fullmatch(native):
        raise ValueError(f"Invalid ABS ID: {native}")
    return f"ABS_CPI_{native}"


def parse_series_id(series_id: str) -> str:
    if not series_id.startswith("ABS_CPI_"):
        raise ValueError(f"Invalid ABS CPI ID: {series_id}")
    native = series_id.removeprefix("ABS_CPI_")
    if build_series_id(native) != series_id:
        raise ValueError(f"Invalid ABS CPI ID: {series_id}")
    return native


def parse_release_page(markup: str, page: str, reference_month: date) -> Release:
    """Read the release date and the two audited workbook links from the page."""
    text = html.unescape(markup)
    table3 = re.search(r'href="([^"]+/640103\.xlsx)"', text)
    table17 = re.search(r'href="([^"]+/6401017\.xlsx)"', text)
    released = re.search(r'>Released</div>\s*<div class="field__item">\s*(\d{2}/\d{2}/\d{4})', text)
    if table3 is None or table17 is None or released is None:
        raise SourceLayoutError(f"ABS release layout changed: {page}")
    return Release(
        page,
        datetime.strptime(released.group(1), "%d/%m/%Y").replace(tzinfo=UTC).date(),
        reference_month,
        urljoin(ROOT, table3.group(1)),
        urljoin(ROOT, table17.group(1)),
    )


def discover_release(client: httpx.Client, today: date) -> Release:
    """Find the latest published monthly release page; never a hardcoded month."""
    for offset in range(4):
        index = today.year * 12 + today.month - 1 - offset
        year, month0 = divmod(index, 12)
        page = f"{RELEASE_ROOT}/{calendar.month_abbr[month0 + 1].lower()}-{year}"
        response = client.get(page)
        if response.status_code == 404:
            continue
        response.raise_for_status()
        month_end = date(year, month0 + 1, calendar.monthrange(year, month0 + 1)[1])
        return parse_release_page(response.text, page, month_end)
    raise SourceAccessError("No recent ABS CPI monthly release")


def discover_workbook(client: httpx.Client, today: date) -> tuple[str, date]:
    """Table 3 URL and the release's reference month (kept for callers/tests)."""
    release = discover_release(client, today)
    return release.table3_url, release.reference_month


def check_payload(response: httpx.Response) -> bytes:
    """Refuse an HTML challenge or error page before it can be parsed as XLSX."""
    response.raise_for_status()
    blob = response.content
    content_type = response.headers.get("content-type", "").lower()
    head = blob[:512].lstrip().lower()
    if "text/html" in content_type or head.startswith((b"<!doctype", b"<html")):
        raise SourceAccessError(f"ABS returned HTML instead of a workbook: {response.url}")
    if not blob.startswith(b"PK\x03\x04"):
        raise SourceAccessError(f"ABS workbook is not an XLSX file: {response.url}")
    if len(blob) < MIN_PAYLOAD_BYTES:
        raise SourceAccessError(f"ABS workbook is implausibly small ({len(blob)} bytes)")
    return blob


def _month_end(value: object) -> date:
    assert isinstance(value, datetime | date)
    day = value.date() if isinstance(value, datetime) else value
    return date(day.year, day.month, calendar.monthrange(day.year, day.month)[1])


def _descriptor(
    native: str, text: str, unit: str, frequency: str, url: str, published: date
) -> dict[str, Any]:
    name = text.split(";")[1].strip()
    if text.startswith(CONTRIBUTION_PREFIX):
        return {
            "name": f"{name}: contribution to All groups CPI",
            "description": f"{text} Index Points; ABS ID {native}",
            "country": "AUD",
            "frequency": frequency,
            "unit": "other",
            "eco_group": "consumer_prices",
            "source_url": url,
            "last_publish_date": published,
        }
    return {
        "name": name,
        "description": f"{text} ABS ID {native}",
        "country": "AUD",
        "frequency": frequency,
        "unit": unit,
        "eco_group": "consumer_prices",
        "source_url": url,
        "last_publish_date": published,
    }


def parse_workbook(blob: bytes, url: str, published: date, table: str = "3") -> SourceData:
    """Parse original index numbers and index-points contributions for Australia."""
    workbook = openpyxl.load_workbook(io.BytesIO(blob), read_only=True, data_only=True)
    sheets = [name for name in workbook.sheetnames if name.startswith("Data")]
    if not sheets:
        raise SourceLayoutError(f"ABS Table {table} has no Data sheet")
    snapshot = hashlib.sha256(blob).hexdigest()
    catalog: dict[str, dict[str, Any]] = {}
    observations: list[Observation] = []
    seen: set[tuple[str, date]] = set()
    for sheet in sheets:
        rows = iter(workbook[sheet].values)
        header = [next(rows) for _ in range(10)]
        if tuple(row[0] for row in header[1:5]) != HEADER_LABELS or header[9][0] != "Series ID":
            raise SourceLayoutError(f"ABS Table {table} {sheet} header changed")
        columns: dict[int, str] = {}
        for i, native in enumerate(header[9]):
            text = str(header[0][i] or "")
            if i == 0 or header[2][i] != "Original" or not text.endswith(";  Australia ;"):
                continue
            is_index = (
                text.startswith(INDEX_PREFIX)
                and header[1][i] == "Index Numbers"
                and header[3][i] == "INDEX"
            )
            is_contribution = (
                text.startswith(CONTRIBUTION_PREFIX) and header[1][i] == "Index Points"
            )
            if table == "17":
                is_contribution = False
                is_index = is_index and native == QUARTERLY_ALL_GROUPS
            if not is_index and not is_contribution:
                continue
            frequency = FREQ_MAP.get(str(header[4][i]))
            if (
                frequency is None
                or (table == "3" and frequency != "monthly")
                or (table == "17" and frequency != "quarterly")
            ):
                raise SourceLayoutError(f"Unexpected ABS frequency {header[4][i]!r} for {native}")
            sid = build_series_id(str(native))
            if sid in catalog:
                raise SourceLayoutError(f"ABS series listed twice: {native}")
            catalog[sid] = _descriptor(str(native), text, "index", frequency, url, published)
            columns[i] = sid
        for row in rows:
            if not isinstance(row[0], datetime | date):
                continue
            ref = _month_end(row[0])
            for i, sid in columns.items():
                raw = row[i]
                if raw is None:
                    continue
                if not isinstance(raw, int | float) or not math.isfinite(raw):
                    raise ValueError(f"Invalid ABS value {raw!r} for {sid} at {ref}")
                if (sid, ref) in seen:
                    raise ValueError(f"Duplicate ABS economic key: {sid} {ref}")
                seen.add((sid, ref))
                observations.append(Observation(sid, ref, float(raw), snapshot))
    required = MONTHLY_ALL_GROUPS if table == "3" else QUARTERLY_ALL_GROUPS
    if build_series_id(required) not in catalog:
        raise SourceLayoutError(f"ABS Table {table} all-groups series {required} missing")
    return SourceData(observations, catalog)


def filter_usable_series(data: SourceData, reference_month: date) -> SourceData:
    """Drop short or stale histories, judged against the release's own month."""
    dates: dict[str, list[date]] = {}
    for obs in data.observations:
        dates.setdefault(obs.series_id, []).append(obs.reference_date)
    usable: set[str] = set()
    for sid, points in dates.items():
        first, last = min(points), max(points)
        age = (reference_month.year - last.year) * 12 + reference_month.month - last.month
        history = (last.year - first.year) * 12 + last.month - first.month
        if (
            age <= MAX_STALE_MONTHS[data.catalog[sid]["frequency"]]
            and history >= MIN_HISTORY_MONTHS
        ):
            usable.add(sid)
        else:
            logger.info("Dropped %s: age=%d months, history=%d months", sid, age, history)
    if build_series_id(MONTHLY_ALL_GROUPS) not in usable:
        raise SourceLayoutError("ABS all-groups CPI unavailable")
    return SourceData(
        [o for o in data.observations if o.series_id in usable],
        {sid: v for sid, v in data.catalog.items() if sid in usable},
    )


def collect() -> SourceData:
    """Fetch Table 3 and Table 17 of the latest release and parse both."""
    with httpx.Client(timeout=REQUEST_TIMEOUT, headers={"User-Agent": USER_AGENT}) as client:
        release = discover_release(client, datetime.now(UTC).date())
        table3 = check_payload(client.get(release.table3_url))
        table17 = check_payload(client.get(release.table17_url))
    monthly = parse_workbook(table3, release.table3_url, release.published, "3")
    quarterly = parse_workbook(table17, release.table17_url, release.published, "17")
    merged = SourceData(
        monthly.observations + quarterly.observations, monthly.catalog | quarterly.catalog
    )
    result = filter_usable_series(merged, release.reference_month)
    evidence = []
    for name, url, part in (
        ("table3_monthly", release.table3_url, monthly),
        ("table17_quarterly", release.table17_url, quarterly),
    ):
        ids = frozenset(part.catalog) & frozenset(result.catalog)
        latest = max(o.reference_date for o in result.observations if o.series_id in ids)
        evidence.append(ReleaseEvidence(name, url, release.published, latest, ids))
    logger.info(
        "ABS CPI %s released %s: %d series, %d observations",
        release.reference_month,
        release.published,
        len(result.catalog),
        len(result.observations),
    )
    return SourceData(result.observations, result.catalog, tuple(evidence))
