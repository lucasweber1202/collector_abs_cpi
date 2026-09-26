"""Official ABS CPI index levels from the current monthly release workbook."""
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
from scripts.time_series import Observation

logger = logging.getLogger(__name__)
ROOT = "https://www.abs.gov.au"
RELEASE_ROOT = ROOT + "/statistics/economy/price-indexes-and-inflation/consumer-price-index-australia"
NATIVE_ID = re.compile(r"A[0-9]{9}[A-Z]")
MIN_HISTORY_MONTHS = 18
MAX_STALE_MONTHS = 3


@dataclass(frozen=True)
class SourceData:
    observations: list[Observation]
    catalog: dict[str, dict[str, Any]]


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


def discover_workbook(client: httpx.Client, today: date) -> tuple[str, date]:
    """Find Table 3 in the latest published monthly release."""
    for offset in range(4):
        index = today.year * 12 + today.month - 1 - offset
        year, month0 = divmod(index, 12)
        page = f"{RELEASE_ROOT}/{calendar.month_abbr[month0 + 1].lower()}-{year}"
        response = client.get(page)
        if response.status_code == 404:
            continue
        response.raise_for_status()
        match = re.search(r'href="([^"]+/640103\.xlsx)"', html.unescape(response.text))
        if match is None:
            raise ValueError(f"ABS Table 3 link missing: {page}")
        return urljoin(ROOT, match.group(1)), date(year, month0 + 1, calendar.monthrange(year, month0 + 1)[1])
    raise ValueError("No recent ABS CPI monthly release")


def parse_workbook(blob: bytes, url: str, published_period: date) -> SourceData:
    """Use only source-original index-number columns, never percentage changes."""
    workbook = openpyxl.load_workbook(io.BytesIO(blob), read_only=True, data_only=True)
    if "Data1" not in workbook:
        raise ValueError("ABS CPI Data1 sheet missing")
    rows = iter(workbook["Data1"].values)
    header = [next(rows) for _ in range(10)]
    if tuple(row[0] for row in header[1:5]) != ("Unit", "Series Type", "Data Type", "Frequency"):
        raise ValueError("ABS CPI header changed")
    snapshot = hashlib.sha256(blob).hexdigest()
    columns: dict[int, dict[str, Any]] = {}
    for i, native in enumerate(header[9]):
        if i == 0 or header[1][i] != "Index Numbers" or header[2][i] != "Original" or header[3][i] != "INDEX":
            continue
        if header[4][i] != "Month":
            raise ValueError(f"Unexpected frequency for {native}")
        sid = build_series_id(str(native))
        descriptor = str(header[0][i])
        if not descriptor.startswith("Index Numbers ;") or not descriptor.endswith(";  Australia ;"):
            raise ValueError(f"Unexpected ABS CPI descriptor: {descriptor}")
        columns[i] = {"series_id": sid, "name": descriptor.split(";")[1].strip(),
                      "description": descriptor, "country": "AUD", "frequency": "monthly",
                      "unit": "index", "eco_group": "consumer_prices", "source_url": url,
                      "last_publish_date": published_period}
    observations: list[Observation] = []
    seen: set[tuple[str, date]] = set()
    for row in rows:
        if not isinstance(row[0], datetime | date):
            continue
        month = row[0].date() if isinstance(row[0], datetime) else row[0]
        ref = date(month.year, month.month, calendar.monthrange(month.year, month.month)[1])
        for i, meta in columns.items():
            raw = row[i]
            if raw is None:
                continue
            if not isinstance(raw, int | float) or not math.isfinite(raw):
                raise ValueError(f"Invalid ABS value: {raw!r}")
            key = meta["series_id"], ref
            if key in seen:
                raise ValueError(f"Duplicate ABS economic key: {key}")
            seen.add(key)
            observations.append(Observation(meta["series_id"], ref, float(raw), snapshot))
    usable: set[str] = set()
    dates: dict[str, list[date]] = {}
    for obs in observations:
        dates.setdefault(obs.series_id, []).append(obs.reference_date)
    for sid, points in dates.items():
        first, last = min(points), max(points)
        age = (published_period.year - last.year) * 12 + published_period.month - last.month
        history = (last.year - first.year) * 12 + last.month - first.month
        if age <= MAX_STALE_MONTHS and history >= MIN_HISTORY_MONTHS:
            usable.add(sid)
    if not usable or not any(columns[i]["name"] == "All groups CPI" and columns[i]["series_id"] in usable for i in columns):
        raise ValueError("ABS all-groups CPI unavailable")
    return SourceData([o for o in observations if o.series_id in usable],
                      {v["series_id"]: v for v in columns.values() if v["series_id"] in usable})


def collect() -> SourceData:
    with httpx.Client(timeout=REQUEST_TIMEOUT, headers={"User-Agent": USER_AGENT}) as client:
        url, published_period = discover_workbook(client, datetime.now(UTC).date())
        response = client.get(url)
        response.raise_for_status()
    result = parse_workbook(response.content, url, published_period)
    logger.info("ABS CPI: %d series, %d observations from %s", len(result.catalog), len(result.observations), url)
    return result
