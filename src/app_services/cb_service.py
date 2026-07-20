# -*- coding: utf-8 -*-
"""
cb_service.py — CB Online lookups via de Algolia-index + mapping naar het
vaste 50-koloms "CB nieuwe uitvraag"-format.

Alle rauwe CB Algolia velden gaan 1-op-1 door naar de output (met listwaarden
pipe-gescheiden). Wij voegen alleen 'ImageUrl_nieuw' toe: het mind-books
patroon (grote cover, zelfde Libris/Boekhuis-ecosysteem als CB), bewust
ZONDER live verificatie zodat het instant is.
"""
from __future__ import annotations

import time
from typing import Callable

import requests

from src.app_services.secrets import AlgoliaConfig

BATCH_SIZE = 500
REQUEST_TIMEOUT = 60


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
    """Map één CB-record naar het 50-koloms format (rauwe API-veldnamen).

    Alle Algolia velden gaan 1-op-1 door; listwaarden worden pipe-gescheiden
    (bijv. 'Auteur: Jan | Piet'). ImageUrl_nieuw is de mind-books URL die de
    lelijke CB-thumbnail vervangt door de grote cover uit hetzelfde
    Libris/Boekhuis-ecosysteem.

    Parameter 'druk' wordt hier NIET gebruikt (CB Algolia bevat geen druk-veld,
    en het huidige 50-koloms format heeft geen aparte 'Druk'-kolom). We laten
    'm in de signature voor achterwaartse compatibiliteit met app.py.
    """
    _ = druk  # bewust ongebruikt in dit format
    return {
        "Isbn": isbn,
        # Identificatie
        "objectID": _g(record, "objectID"),
        "LastUpdateDTD": _g(record, "LastUpdateDTD"),
        # Titel
        "Hoofdtitel": _g(record, "Hoofdtitel"),
        "Ondertitel": _g(record, "Ondertitel"),
        "Deeltitel": _g(record, "Deeltitel"),
        "Sectietitel": _g(record, "Sectietitel"),
        "OrigineleTitel": _g(record, "OrigineleTitel"),
        # Betrokkenen
        "Auteur": _g(record, "Auteur"),
        "EersteBetrokkene": _g(record, "EersteBetrokkene"),
        "Redacteur": _g(record, "Redacteur"),
        "Vertaler": _g(record, "Vertaler"),
        "Bewerker": _g(record, "Bewerker"),
        "Illustrator": _g(record, "Illustrator"),
        "Fotograaf": _g(record, "Fotograaf"),
        "Corporatie": _g(record, "Corporatie"),
        # Uitgeverij / verschijning
        "Uitgever": _g(record, "Uitgever"),
        "Imprint": _g(record, "Imprint"),
        "Verschijningsvorm": _g(record, "Verschijningsvorm"),
        "Taal": _g(record, "Taal"),
        "Boeksoort": _g(record, "Boeksoort"),
        "Verschijningsdatum": _g(record, "Verschijningsdatum"),
        "Verschijningsjaar": _g(record, "Verschijningsjaar"),
        "VerwachteVerschijningsdatum": _g(record, "VerwachteVerschijningsdatum"),
        "SpecialeUitgaveInd": _g(record, "SpecialeUitgaveInd"),
        "ReeksNm": _g(record, "ReeksNm"),
        "ReeksNr": _g(record, "ReeksNr"),
        "Prijs": _g(record, "Prijs"),
        # NUR / categorisatie
        "Nur": _g(record, "Nur"),
        "NurNivo1": _g(record, "NurNivo1"),
        "NurNivo2": _g(record, "NurNivo2"),
        "NurNivo3": _g(record, "NurNivo3"),
        # Thema
        "ThemaHoofdSubject": _g(record, "ThemaHoofdSubject"),
        "ThemaSubjects": _g(record, "ThemaSubjects"),
        "ThemaExtraSubjects": _g(record, "ThemaExtraSubjects"),
        "ThemaQualifiersPedagogischDoel": _g(record, "ThemaQualifiersPedagogischDoel"),
        "ThemaQualifiersTaal": _g(record, "ThemaQualifiersTaal"),
        "ThemaQualifiersDoelgroep": _g(record, "ThemaQualifiersDoelgroep"),
        "ThemaQualifiersPlaats": _g(record, "ThemaQualifiersPlaats"),
        "ThemaQualifiersTijdperk": _g(record, "ThemaQualifiersTijdperk"),
        "ThemaQualifiersStijl": _g(record, "ThemaQualifiersStijl"),
        # Beschikbaarheid / verkoop
        "BeschikbaarheidsCode": _g(record, "BeschikbaarheidsCode"),
        "bestelbaar_nl": _g(record, "bestelbaar_nl"),
        "bestelbaar_be": _g(record, "bestelbaar_be"),
        "is_bestelbaar": _g(record, "is_bestelbaar"),
        "assortiment_type_nl": _g(record, "assortiment_type_nl"),
        "assortiment_type_be": _g(record, "assortiment_type_be"),
        "VerkooplandUitsluiting": _g(record, "VerkooplandUitsluiting"),
        # Afbeelding
        "ImageUrl": _g(record, "ImageUrl"),
        "ImageUrl_nieuw": image_url_for(isbn),
    }
