"""Published ABS annual baskets/hierarchy and monthly effective aggregation shares.

The annual Table 5 identifies hierarchy by its three label columns. Published
percentages remain untouched in original_weights. Monthly weights use the
published index-points contributions, normalized within each explicit parent.
No hierarchy is guessed from a repeated label or the order of a time-series file.
"""

from __future__ import annotations

import calendar
import html
import io
import math
import re
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import date
from urllib.parse import urljoin

import httpx
import openpyxl

from scripts.config import REQUEST_TIMEOUT, USER_AGENT
from scripts.extract import SourceData, SourceLayoutError, _http_get, check_payload
from scripts.original_weights import HierarchyNode
from scripts.weights import WeightObservation

WEIGHT_PAGE = "https://www.abs.gov.au/statistics/economy/price-indexes-and-inflation/annual-weight-update-cpi-and-living-cost-indexes/latest-release"
MONTHS = {name.lower(): n for n, name in enumerate(calendar.month_name) if name}


@dataclass(frozen=True)
class BaseWeight:
    series_id: str
    parent_id: str | None
    base_period: date
    percent: float


def _label(value: str) -> str:
    """Case-independent source label, with only whitespace normalized."""
    return " ".join(value.lower().split())


def parse_baskets(blob: bytes, data: SourceData) -> tuple[list[BaseWeight], list[HierarchyNode]]:
    """Map Table 5's explicit hierarchy columns to the monthly native identities."""
    book = openpyxl.load_workbook(io.BytesIO(blob), read_only=True, data_only=True)
    if "Table 5" not in book:
        raise SourceLayoutError("ABS weighting pattern Table 5 missing")
    rows = list(book["Table 5"].iter_rows(max_col=24, values_only=True))
    regimes: dict[int, date] = {}
    for col in range(3, 24, 3):
        year_header = rows[5][col]
        if not isinstance(year_header, str) or not re.fullmatch(r"\d{4} weights", year_header):
            continue
        m = re.search(r"in ([A-Za-z]+) quarter (\d{4})", str(rows[6][col]))
        if m is None or m[1].lower() not in MONTHS:
            raise SourceLayoutError("ABS basket reference quarter missing")
        month, year = MONTHS[m[1].lower()], int(m[2])
        regimes[col] = date(year, month, calendar.monthrange(year, month)[1])
    if not regimes:
        raise SourceLayoutError("ABS basket regimes missing")
    by_name: dict[str, deque[str]] = defaultdict(deque)
    for sid, fields in data.catalog.items():
        if fields["unit"] == "index" and fields["frequency"] == "monthly":
            by_name[_label(str(fields["name"]))].append(sid)
    root = "ABS_CPI_A130393720C"
    nodes = [
        HierarchyNode(root, root.removeprefix("ABS_CPI_"), None, 0, str(data.catalog[root]["name"]))
    ]
    stack = {0: root}
    originals: list[BaseWeight] = []
    for row in rows[7:]:
        populated = [
            (i + 1, cell)
            for i, cell in enumerate(row[:3])
            if isinstance(cell, str) and cell.strip()
        ]
        if len(populated) != 1:
            continue
        level, label = populated[0]
        if _label(label).startswith("all groups"):
            continue
        key = _label(label)
        if not by_name.get(key):
            # Notes below the classification are not hierarchy members.
            if not any(isinstance(row[col + level - 1], int | float) for col in regimes):
                continue
            raise SourceLayoutError(f"ABS basket identity has no monthly index: {label}")
        sid = by_name[key].popleft()
        parent = stack.get(level - 1)
        if parent is None:
            raise SourceLayoutError(f"ABS hierarchy has no parent for {label}")
        stack[level] = sid
        for deeper in range(level + 1, 4):
            stack.pop(deeper, None)
        nodes.append(
            HierarchyNode(
                sid, sid.removeprefix("ABS_CPI_"), parent, level, str(data.catalog[sid]["name"])
            )
        )
        for col, base in regimes.items():
            value = row[col + level - 1]
            if value in (None, ""):
                continue
            if (
                not isinstance(value, int | float)
                or not math.isfinite(value)
                or not 0 <= value <= 100
            ):
                raise SourceLayoutError(f"Invalid published ABS basket weight: {label} {base}")
            originals.append(BaseWeight(sid, parent, base, float(value)))
    if len(nodes) != 132 or {n.level for n in nodes} != {0, 1, 2, 3}:
        raise SourceLayoutError(f"ABS hierarchy changed: {len(nodes)} nodes")
    if any(by_name[key] for key in by_name if key != _label(str(data.catalog[root]["name"]))):
        raise SourceLayoutError("Monthly CPI contains unmapped basket identities")
    quarterly = "ABS_CPI_A2325846C"
    if quarterly in data.catalog:
        nodes.append(
            HierarchyNode(quarterly, "A2325846C", None, 0, str(data.catalog[quarterly]["name"]))
        )
    return originals, nodes


def collect_baskets(data: SourceData) -> tuple[list[BaseWeight], list[HierarchyNode]]:
    """Discover the official weighting workbook rather than pinning a dated URL."""
    with httpx.Client(
        timeout=REQUEST_TIMEOUT, headers={"User-Agent": USER_AGENT}, follow_redirects=True
    ) as client:
        page = _http_get(client, WEIGHT_PAGE)
        page.raise_for_status()
        links = re.findall(r'href="([^"]+)"', html.unescape(page.text))
        candidates = [
            u
            for u in links
            if "annual-weight-update" in u
            and "Consumer%20Price%20Index" in u
            and u.endswith(".xlsx")
        ]
        if not candidates:
            raise SourceLayoutError("ABS weighting workbook link missing")
        blob = check_payload(_http_get(client, urljoin(str(page.url), candidates[0])))
    return parse_baskets(blob, data)


def derive_weights(data: SourceData, nodes: list[HierarchyNode]) -> list[WeightObservation]:
    """Normalize official monthly contributions within each published parent."""
    index_ids = [n.series_id for n in nodes if n.series_id != "ABS_CPI_A2325846C"]
    contributions = [
        sid
        for sid, f in data.catalog.items()
        if str(f["name"]).endswith(": contribution to All groups CPI")
    ]
    if len(index_ids) != len(contributions):
        raise SourceLayoutError("ABS contribution/index mapping changed")
    # Verify every label at every hierarchy position, including repeated labels.
    mapping = {}
    for sid, contribution in zip(index_ids, contributions):
        if (
            str(data.catalog[contribution]["name"]).removesuffix(": contribution to All groups CPI")
            != data.catalog[sid]["name"]
        ):
            raise SourceLayoutError(f"ABS contribution identity mismatch: {sid}")
        mapping[sid] = contribution
    values = {(o.series_id, o.reference_date): o.value for o in data.observations}
    children: dict[str, list[str]] = defaultdict(list)
    for node in nodes:
        if node.parent_id:
            children[node.parent_id].append(node.series_id)
    periods = sorted(
        {o.reference_date for o in data.observations if o.series_id == mapping[index_ids[0]]}
    )
    result: list[WeightObservation] = []
    for when in periods:
        for parent, kids in children.items():
            raw = [values.get((mapping[sid], when)) for sid in kids]
            if any(v is None or v < 0 for v in raw):
                raise SourceLayoutError(f"ABS component contribution missing: {parent} {when}")
            total = sum(float(v) for v in raw if v is not None)
            stated = values.get((mapping[parent], when))
            if stated is None or abs(total - stated) > 0.005 * (len(kids) + 1) + 1e-8 or total <= 0:
                raise SourceLayoutError(
                    f"ABS component contributions do not sum to parent: {parent} {when}"
                )
            result.extend(
                WeightObservation(sid, when, float(v) / total, "official-contributions")
                for sid, v in zip(kids, raw)
                if v is not None
            )
    for node in nodes:
        if node.parent_id is None:
            result.extend(
                WeightObservation(node.series_id, o.reference_date, 1.0, o.snapshot_id)
                for o in data.observations
                if o.series_id == node.series_id
            )
    return result
