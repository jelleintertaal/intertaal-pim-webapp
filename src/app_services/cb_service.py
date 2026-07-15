# -*- coding: utf-8 -*-
"""
cb_service.py — CB Online lookups via de Algolia-index + mapping naar het
vaste 16-koloms "CB data gewenst"-format.

De veld-mapping is 1-op-1 overgenomen uit scripts/cb_gewenst_26k.py
(build_gewenst), de bewezen implementatie van het afgesproken format.

afbeeldingsurl: het mind-books patroon (grote cover, zelfde
Libris/Boekhuis-ecosysteem) — bewust ZONDER live verificatie (keuze Jelle):
instant, maar bij een ISBN dat mind-books niet kent geeft de URL een 404.
"""
from __future__ import annotations

import time
from typing import Callable

import requests

from src.app_services.secrets import AlgoliaConfig

BATCH_SIZE = 500
REQUEST_TIMEOUT = 60

BESCHIKBAARHEID = {
    "1": "Leverbaar",
    "2": "Nog niet verschenen",
    "3": "Niet leverbaar, wordt herdrukt",
    "4": "Niet leverbaar bij CB",
    "5": "Niet leverbaar",
    "6": "Wordt opnieuw uitgegeven",
}


class CBAuthError(RuntimeError):
    """Algolia weigert de sleutel (401/403) — CB-sessie/sleutel verlopen."""


class CBServiceError(RuntimeError):
    """Overige CB-fouten (netwerk, 5xx)."""


def fetch_cb_records(isbns: list[str], cfg: AlgoliaConfig,
                     progress_cb: Callable[[int, int], None] | None = None) -> dict[str, dict]:
    """Haal CB-records op in batches van 500. Return {isbn: raw_record}."""
    url = f"https://{cfg.app_id}-dsn.algolia.net/1/indexes/*/objects"
    headers = {
        "x-algolia-application-id": cfg.app_id,
        "x-algolia-api-key": cfg.api_key,
        "content-type": "application/json",
    }
    results: dict[str, dict] = {}
    total_batches = (len(isbns) + BATCH_SIZE - 1) // BATCH_SIZE

    for batch_num, start in enumerate(range(0, len(isbns), BATCH_SIZE), start=1):
        batch = isbns[start:start + BATCH_SIZE]
        payload = {"requests": [{"indexName": cfg.index_name, "objectID": isbn}
                                for isbn in batch]}
        try:
            resp = requests.post(url, headers=headers, json=payload,
                                 timeout=REQUEST_TIMEOUT)
        except requests.RequestException as exc:
            raise CBServiceError("CB (Algolia) is tijdelijk niet bereikbaar.") from exc

        if resp.status_code in (401, 403):
            raise CBAuthError(
                "De CB-sleutel is verlopen of ongeldig. "
                "Zie docs/runbook-cb-key.md om de sleutel te vernieuwen."
            )
        if resp.status_code != 200:
            raise CBServiceError(f"CB (Algolia) gaf een fout (HTTP {resp.status_code}).")

        for item in resp.json().get("results", []):
            if item and not item.get("_not_found"):
                oid = str(item.get("objectID") or item.get("Isbn") or "").strip()
                if oid:
                    results[oid] = item

        if progress_cb:
            progress_cb(batch_num, total_batches)
        if batch_num < total_batches:
            time.sleep(0.25)
    return results


def _g(record: dict, key: str) -> str:
    value = record.get(key)
    if value is None:
        return ""
    if isinstance(value, list):
        return " | ".join(str(v) for v in value if v is not None)
    return str(value).strip()


def image_url_for(isbn: str) -> str:
    return f"https://images.mind-books.nl/libris/book/cover/{isbn}"


def build_cb_row(isbn: str, record: dict, druk: str = "") -> dict[str, str]:
    """Map één CB-record naar het 16-koloms template (kolomnamen exact)."""
    hoofdtitel = _g(record, "Hoofdtitel")
    ondertitel = _g(record, "Ondertitel")

    vd_raw = _g(record, "Verschijningsdatum")
    verschijningsdatum = (f"{vd_raw[:4]}-{vd_raw[4:6]}-{vd_raw[6:8]}"
                          if len(vd_raw) >= 8 else vd_raw)

    prijs = _g(record, "Prijs")

    nur = _g(record, "Nur")
    thema_hoofd = _g(record, "ThemaHoofdSubject")
    thema_sub = _g(record, "ThemaSubjects")
    nur_parts = [p for p in (nur, thema_hoofd) if p]
    if thema_sub and thema_sub != thema_hoofd:
        nur_parts.append(thema_sub)

    bestelbaar = _g(record, "bestelbaar_nl")
    code = _g(record, "BeschikbaarheidsCode")
    leverbaarheid = bestelbaar or BESCHIKBAARHEID.get(code, f"Code {code}" if code else "")

    return {
        "ISBN": isbn,
        "TITLE": hoofdtitel,
        "Binding": _g(record, "Verschijningsvorm"),
        "Title": f"{hoofdtitel} - {ondertitel}" if (hoofdtitel and ondertitel) else (hoofdtitel or ondertitel),
        "verschijningsdatum": verschijningsdatum,
        "LISTPRICE": prijs,
        "in/ex btw": "incl. btw" if prijs else "",
        "Valuta": "EUR" if prijs else "",
        "Publisher": _g(record, "Uitgever") or _g(record, "Imprint"),
        "Druk": druk,
        "Omschrijving": ondertitel,
        "afbeeldingsurl": image_url_for(isbn),
        "serienaam": _g(record, "ReeksNm"),
        "seriedeel ": _g(record, "ReeksNr"),
        "NUR CODES studydomein / tags": " | ".join(nur_parts),
        "leverbaarheid": leverbaarheid,
    }
