from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Union

import pandas as pd

import os

SHARED_INPUT_PATH = Path(os.getenv("SHARED_INPUT_PATH", "/tmp/uploaded_isbn_list.xlsx"))


def _clean_isbn(value: object) -> str:
    """Strip spaties, streepjes en cast naar string."""
    return re.sub(r"[-\s]", "", str(value).strip())


def _is_isbn13(value: object) -> bool:
    """True als de waarde een geldig ISBN-13 is (978 of 979 prefix, 13 cijfers)."""
    return bool(re.fullmatch(r"97[89]\d{10}", _clean_isbn(value)))


def find_isbn_column(df: pd.DataFrame) -> str | None:
    """
    Zoekt de kolom met de meeste geldige ISBN-13 waarden.
    Kijkt niet naar kolomnaam — puur op inhoud.
    Geeft None als er geen geschikte kolom is.
    """
    best_col = None
    best_count = 0

    for col in df.columns:
        count = sum(1 for v in df[col].dropna() if _is_isbn13(v))
        if count > best_count:
            best_count = count
            best_col = col

    return best_col if best_count > 0 else None


def extract_isbns_from_df(df: pd.DataFrame) -> tuple[list[str], str | None]:
    """
    Detecteert automatisch de ISBN-kolom en geeft deduplicated ISBN-13 lijst terug.
    Tweede returnwaarde is de gedetecteerde kolomnaam (voor feedback aan de gebruiker).
    """
    col = find_isbn_column(df)
    if col is None:
        return [], None

    seen: dict[str, None] = {}
    for v in df[col].dropna():
        clean = _clean_isbn(v)
        if re.fullmatch(r"97[89]\d{10}", clean):
            seen[clean] = None  # dict als ordered set

    return list(seen.keys()), col


def load_isbns_from_excel(
    path_or_file: Union[str, Path, object],
    limit: int | None = None,
) -> tuple[list[str], str | None]:
    """
    Laadt ISBNs uit een Excel-bestand of file-like object (bijv. Streamlit upload).
    Detecteert automatisch welke kolom ISBNs bevat.
    Geeft (isbns, gedetecteerde_kolomnaam) terug.
    """
    df = pd.read_excel(path_or_file, dtype=str)
    isbns, col = extract_isbns_from_df(df)
    if limit is not None:
        isbns = isbns[:limit]
    return isbns, col
