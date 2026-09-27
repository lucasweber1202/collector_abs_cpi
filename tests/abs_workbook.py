"""Build small workbooks in the audited ABS time-series layout for tests."""

from __future__ import annotations

import io
from datetime import date

import openpyxl

LABELS = ["Unit", "Series Type", "Data Type", "Frequency", "Collection Month", "Series Start", "Series End", "No. Obs", "Series ID"]


def workbook(columns: list[tuple[str, str, str, str, str]], rows: list[tuple[date, list[float | None]]]) -> bytes:
    """columns: (description, unit, data_type, frequency, series_id)."""
    book = openpyxl.Workbook()
    index = book.active
    assert index is not None
    index.title = "Index"
    sheet = book.create_sheet("Data1")
    sheet.append([None, *[c[0] for c in columns]])
    sheet.append(["Unit", *[c[1] for c in columns]])
    sheet.append(["Series Type", *["Original"] * len(columns)])
    sheet.append(["Data Type", *[c[2] for c in columns]])
    sheet.append(["Frequency", *[c[3] for c in columns]])
    for label in LABELS[4:8]:
        sheet.append([label, *[None] * len(columns)])
    sheet.append(["Series ID", *[c[4] for c in columns]])
    for when, values in rows:
        sheet.append([when, *values])
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()


def table3(months: int = 20, shift: float = 0.0) -> bytes:
    """All groups, two groups (the rest folded into 'Housing'), their contributions."""
    columns = [
        ("Index Numbers ;  All groups CPI ;  Australia ;", "Index Numbers", "INDEX", "Month", "A130393720C"),
        ("Index Numbers ;  Food and non-alcoholic beverages ;  Australia ;", "Index Numbers", "INDEX", "Month", "A130395477A"),
        ("Percentage Change from Previous Period ;  All groups CPI ;  Australia ;", "Percent", "PERCENT", "Month", "A130393721F"),
        ("Contribution to All groups CPI Index Number ;  All groups CPI ;  Australia ;", "Index Points", "INDEX", "Month", "A130393723K"),
    ]
    from scripts.validate import GROUPS

    for n, group in enumerate(GROUPS):
        columns.append((f"Contribution to All groups CPI Index Number ;  {group} ;  Australia ;", "Index Points", "INDEX", "Month", f"A1300000{n:02d}X"))
    rows: list[tuple[date, list[float | None]]] = []
    for m in range(months):
        year, month = divmod(2024 * 12 + 11 + m, 12)
        headline = round(97 + 0.3 * m, 2)
        parts = [round(headline / 11, 2)] * 10
        parts.append(round(headline - sum(parts) + shift, 2))
        rows.append((date(year, month + 1, 1), [headline, 100 + m, 0.3, headline, *parts]))
    return workbook(columns, rows)


def table17(values: dict[date, float]) -> bytes:
    columns = [("Index Numbers ;  All groups CPI ;  Australia ;", "Index Numbers", "INDEX", "Quarter", "A2325846C")]
    return workbook(columns, [(when, [value]) for when, value in sorted(values.items())])
