# -*- coding: utf-8 -*-
"""
validation.py — Upload-validatie en rij-administratie.

Anders dan isbn_utils.extract_isbns_from_df behoudt deze parser de
ORIGINELE volgorde en duplicaten: elke inputrij wordt een RowResult,
ook rijen met een ongeldig ISBN (die krijgen status 'Ongeldig ISBN'
en blokkeren niets).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from isbn_utils import find_isbn_column, _clean_isbn, _is_isbn13

# Status-vocabulaire (vast, wordt 1-op-1 in de output getoond)
STATUS_OK = "OK"
STATUS_OK_CACHE = "OK (cache)"
STATUS_INVALID = "Ongeldig ISBN"
STATUS_NOT_FOUND = "Niet gevonden"
STATUS_QUOTA = "Niet verwerkt (dagquotum bereikt)"
STATUS_SOURCE_DOWN = "Bron onbereikbaar"


class UploadError(ValueError):
    """Gebruikersgerichte fout bij het inlezen van een upload."""


@dataclass
class RowResult:
    index: int                 # positie in het inputbestand (0-based)
    raw: str                   # de originele celwaarde
    isbn: str | None           # geschoond ISBN-13, of None indien ongeldig
    status: str = ""
    opmerking: str = ""


def parse_upload(uploaded_file) -> tuple[list[RowResult], str]:
    """Lees een geüpload Excel-bestand volledig in-memory.

    Returns (rows, gedetecteerde_kolomnaam). Raises UploadError met een
    duidelijke, gebruikersvriendelijke melding.
    """
    try:
        df = pd.read_excel(uploaded_file, dtype=str)
    except Exception as exc:
        raise UploadError(
            "Het bestand kan niet worden gelezen. Upload een geldig "
            "Excel-bestand (.xlsx)."
        ) from exc

    if df.empty:
        raise UploadError("Het bestand bevat geen rijen.")

    col = find_isbn_column(df)
    if col is None:
        raise UploadError(
            "Geen ISBN-kolom gevonden. Zorg dat het bestand een kolom bevat "
            "met ISBN-13 nummers (beginnend met 978 of 979)."
        )

    rows: list[RowResult] = []
    for i, value in enumerate(df[col]):
        raw = "" if pd.isna(value) else str(value).strip()
        cleaned = _clean_isbn(raw) if raw else ""
        if raw and _is_isbn13(cleaned):
            rows.append(RowResult(index=i, raw=raw, isbn=cleaned))
        else:
            rows.append(RowResult(
                index=i, raw=raw, isbn=None,
                status=STATUS_INVALID,
                opmerking="Geen geldig ISBN-13" if raw else "Lege cel",
            ))
    return rows, col


def unique_valid_isbns(rows: list[RowResult]) -> list[str]:
    """Unieke geldige ISBNs in volgorde van eerste voorkomen."""
    seen: dict[str, None] = {}
    for row in rows:
        if row.isbn and row.isbn not in seen:
            seen[row.isbn] = None
    return list(seen.keys())
