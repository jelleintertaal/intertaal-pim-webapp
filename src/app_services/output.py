# -*- coding: utf-8 -*-
"""
output.py — Bouwt het output-Excel in het vaste template-format.

Regels (uit de opdracht):
  - Template-kolommen exact (naam + volgorde); templates zijn leidend.
  - Daarná twee extra kolommen: Status en Bron.
  - Alle inputrijen blijven aanwezig, in de originele volgorde.
  - Duplicaten in de input krijgen elk dezelfde opgehaalde data.
  - Alles als string (geen .0-floats).
"""
from __future__ import annotations

import io

import pandas as pd

from src.app_services.templates import STATUS_COL, BRON_COL
from src.app_services.validation import RowResult

EXCEL_CELL_MAX = 32000


def build_output_df(
    rows: list[RowResult],
    data_by_isbn: dict[str, dict[str, str]],
    template_cols: list[str],
    isbn_col_name: str,
    bron_by_isbn: dict[str, str] | None = None,
) -> pd.DataFrame:
    bron_by_isbn = bron_by_isbn or {}
    records: list[dict[str, str]] = []
    for row in rows:
        record = {col: "" for col in template_cols}
        record[isbn_col_name] = row.raw or (row.isbn or "")
        if row.isbn:
            data = data_by_isbn.get(row.isbn, {})
            for col, value in data.items():
                if col in record and value not in (None, ""):
                    text = str(value)
                    if len(text) > EXCEL_CELL_MAX:
                        text = text[:EXCEL_CELL_MAX]
                    record[col] = text
            # ISBN-kolom altijd het geschoonde ISBN tonen
            record[isbn_col_name] = row.isbn
        record[STATUS_COL] = row.status
        if row.opmerking and row.status and row.opmerking not in row.status:
            record[STATUS_COL] = f"{row.status} — {row.opmerking}"
        record[BRON_COL] = bron_by_isbn.get(row.isbn or "", "")
        records.append(record)

    df = pd.DataFrame(records, columns=template_cols + [STATUS_COL, BRON_COL])
    return df.astype(str).replace("nan", "")


def df_to_xlsx_bytes(df: pd.DataFrame) -> bytes:
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df.to_excel(writer, index=False)
    buffer.seek(0)
    return buffer.getvalue()
