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


# ---------------------------------------------------------------------------
# Vrij zoeken (tab 3): full-text search op de CB Algolia-index
# ---------------------------------------------------------------------------

SEARCH_PAGE_SIZE = 100      # Algolia-maximum per pagina is 1000; 100 houdt de
                            # voortgangsbalk vloeiend zonder extra round-trips.
SEARCH_MAX_RESULTS = 1000   # Algolia's paginationLimitedTo-plafond.

# CB BeschikbaarheidsCode -> leesbare tekst.
# LET OP: 1 t/m 6 staan zo in de CB-documentatie. 7 t/m 10 zijn in augustus 2026
# empirisch afgeleid uit het assortiment en NIET bevestigd door CB-support;
# die krijgen een * mee zodat de gebruiker weet dat ze onder voorbehoud zijn.
BESCHIKBAARHEID_LABELS = {
    "1": "Leverbaar",
    "2": "Nog niet verschenen",
    "3": "Niet leverbaar, wordt herdrukt",
    "4": "Niet leverbaar bij CB",
    "5": "Niet leverbaar",
    "6": "Wordt opnieuw uitgegeven",
    "7": "Tijdelijk niet leverbaar *",
    "8": "Beperkt/speciaal *",
    "9": "Leverbaar via Van Ditmar-import *",
    "10": "Alleen ISBN-registratie *",
}


def leverbaarheid_label(code: str | int | None) -> str:
    """Leesbare leverbaarheid bij een BeschikbaarheidsCode.

    Gebruik ALTIJD dit veld en nooit is_bestelbaar/bestelbaar_nl/bestelbaar_be:
    die staan bij CB op alles op 'ja' en zijn dus waardeloos als filter.
    """
    key = str(code or "").strip()
    if not key:
        return ""
    return BESCHIKBAARHEID_LABELS.get(key, f"Code {key}")


def search_cb_records(query: str, cfg: AlgoliaConfig, max_results: int = 100,
                      progress_cb: Callable[[int, int], None] | None = None
                      ) -> tuple[list[dict], int]:
    """Vrije zoekopdracht op auteur, titel, uitgever, ISBN, reeks, ...

    Anders dan fetch_cb_records (dat exacte objectID-lookups doet) gebruikt dit
    de Algolia search-endpoint, met Algolia's eigen relevantie-ordening.

    Returns (records_op_relevantievolgorde, totaal_aantal_treffers). Het totaal
    kan groter zijn dan het aantal teruggegeven records: er worden er maximaal
    `max_results` opgehaald.
    """
    query = (query or "").strip()
    if not query:
        return [], 0

    max_results = max(1, min(int(max_results), SEARCH_MAX_RESULTS))
    url = f"https://{cfg.app_id}-dsn.algolia.net/1/indexes/{cfg.index_name}/query"
    headers = {
        "x-algolia-application-id": cfg.app_id,
        "x-algolia-api-key": cfg.api_key,
        "content-type": "application/json",
    }

    records: list[dict] = []
    gezien: set[str] = set()
    nb_hits = 0
    page = 0
    total_pages = 1

    while len(records) < max_results:
        rest = max_results - len(records)
        payload = {
            "query": query,
            "hitsPerPage": min(SEARCH_PAGE_SIZE, rest),
            "page": page,
        }
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

        data = resp.json()
        hits = data.get("hits") or []
        if page == 0:
            nb_hits = int(data.get("nbHits") or 0)
            # Hoeveel pagina's we echt gaan ophalen (voor de voortgangsbalk).
            beschikbaar = min(nb_hits, max_results)
            total_pages = max(1, (beschikbaar + SEARCH_PAGE_SIZE - 1) // SEARCH_PAGE_SIZE)

        for hit in hits:
            oid = str(hit.get("objectID") or hit.get("Isbn") or "").strip()
            if oid and oid not in gezien:
                gezien.add(oid)
                records.append(hit)

        if progress_cb:
            progress_cb(min(page + 1, total_pages), total_pages)

        page += 1
        if not hits or page >= int(data.get("nbPages") or 0):
            break
        if len(records) < max_results:
            time.sleep(0.25)

    return records[:max_results], nb_hits
