# -*- coding: utf-8 -*-
"""
nielsen_service.py — Nielsen BDOL lookups met cache en quota-afhandeling.

Kern verplaatst uit scripts/enrich_nielsen.py zodat de webapp en de
CLI-scripts dezelfde logica delen.

Quota: Nielsen staat ~1000 calls per dag toe. Bij het quota-signaal
(HTTP 403/429, quota-tekst in de body, of resultCode 50) stopt de
verwerking netjes; resterende ISBNs krijgen een quota-status en het
proces crasht nooit.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Callable

import requests

from src.app_services import caches, static_lookups, turso_cache
from src.app_services.secrets import get_nielsen_credentials, get_nielsen_api_url
from src.app_services.validation import (
    STATUS_OK, STATUS_OK_CACHE, STATUS_NOT_FOUND, STATUS_QUOTA, STATUS_SOURCE_DOWN,
)

RATE_LIMIT_SECONDS = 0.35
REQUEST_TIMEOUT = 15


class NielsenQuotaExceeded(Exception):
    pass


@dataclass
class NielsenResult:
    data: dict[str, dict[str, str]] = field(default_factory=dict)   # isbn -> {kolom: waarde}
    status: dict[str, str] = field(default_factory=dict)            # isbn -> statustekst
    opmerking: dict[str, str] = field(default_factory=dict)         # isbn -> toelichting
    quota_hit: bool = False
    live_fetches: int = 0
    cache_hits: int = 0


def fetch_nielsen(isbn: str, session: requests.Session,
                  client_id: str, password: str, api_url: str) -> str:
    """Eén ISBN ophalen. Returnt raw XML. Raist NielsenQuotaExceeded bij quota."""
    params = {
        "clientId": client_id,
        "password": password,
        "from": 0, "to": 1,
        "indexType": 0, "format": 7, "resultView": 2,
        "field0": 1, "value0": isbn, "logic0": 0,
    }
    resp = session.get(api_url, params=params, timeout=REQUEST_TIMEOUT)
    if resp.status_code in (403, 429):
        raise NielsenQuotaExceeded(f"HTTP {resp.status_code}")
    resp.raise_for_status()
    lowered = resp.text.lower()
    if any(t in lowered for t in ("quota exceeded", "daily limit", "credits exhausted")):
        raise NielsenQuotaExceeded("quota-melding in response")
    if "<resultCode>50</resultCode>" in resp.text:
        raise NielsenQuotaExceeded("resultCode=50 (dagquotum)")
    return resp.text


def parse_nielsen(xml: str, target_columns: list[str]) -> dict[str, str]:
    """Extraheert de gevraagde kolommen uit een Nielsen XML-record."""
    if not xml or "<record>" not in xml:
        return {}
    match = re.search(r"<record>(.*?)</record>", xml, re.DOTALL)
    if not match:
        return {}
    record = match.group(1)
    out: dict[str, str] = {}
    for col in target_columns:
        m = re.search(rf"<{re.escape(col)}>([^<]*)</{re.escape(col)}>", record)
        if m and m.group(1).strip():
            out[col] = m.group(1).strip()
    return out


def count_cache_hits(isbns: list[str]) -> int:
    """Aantal ISBN's dat gratis (zonder Nielsen-call) beantwoord kan worden:
    Turso + statische repo-lookup + ephemeral session-cache."""
    turso_hits: set[str] = set()
    if turso_cache.is_enabled():
        turso_hits = set(turso_cache.fetch_nielsen(isbns).keys())
    static_nl = static_lookups.get_nielsen()
    session_cache = caches.load_json_cache(caches.NIELSEN_CACHE)
    return sum(1 for isbn in isbns
               if isbn in turso_hits or isbn in static_nl or isbn in session_cache)


def enrich(isbns: list[str], target_columns: list[str],
           progress_cb: Callable[[int, int], None] | None = None,
           max_live: int | None = None) -> NielsenResult:
    """Verrijk unieke ISBNs: cache eerst, dan live tot het quotum.

    max_live is een testhaakje om quota-gedrag te simuleren.
    """
    result = NielsenResult()
    cache = caches.load_json_cache(caches.NIELSEN_CACHE)
    static_nl = static_lookups.get_nielsen()  # {isbn: {kolom: waarde}}
    # Turso in één batch ophalen (gedeelde live cache — nieuwe records van iedereen)
    turso_records: dict[str, dict[str, str]] = {}
    if turso_cache.is_enabled():
        turso_records = turso_cache.fetch_nielsen(isbns)
    new_entries: dict[str, str] = {}
    new_nielsen_records: dict[str, dict[str, str]] = {}
    session = requests.Session()
    client_id = password = api_url = None

    total = len(isbns)
    for i, isbn in enumerate(isbns):
        if progress_cb:
            progress_cb(i + 1, total)

        # 1a. Turso: gedeelde live cache — nieuwe records van andere gebruikers
        if isbn in turso_records:
            parsed = {k: v for k, v in turso_records[isbn].items() if k in target_columns}
            if parsed:
                result.data[isbn] = parsed
                result.status[isbn] = STATUS_OK_CACHE
                result.cache_hits += 1
            else:
                result.status[isbn] = STATUS_NOT_FOUND
                result.opmerking[isbn] = "ISBN niet bekend bij Nielsen"
            continue

        # 1b. Statische repo-lookup (fallback bij Turso-storing)
        if isbn in static_nl:
            parsed = {k: v for k, v in static_nl[isbn].items() if k in target_columns}
            if parsed:
                result.data[isbn] = parsed
                result.status[isbn] = STATUS_OK_CACHE
                result.cache_hits += 1
            else:
                result.status[isbn] = STATUS_NOT_FOUND
                result.opmerking[isbn] = "ISBN niet bekend bij Nielsen"
            continue

        if isbn in cache:
            xml = cache[isbn]
            from_cache = True
        elif result.quota_hit or (max_live is not None and result.live_fetches >= max_live):
            result.status[isbn] = STATUS_QUOTA
            result.opmerking[isbn] = "Probeer het morgen opnieuw; al opgehaalde data blijft bewaard"
            result.quota_hit = True
            continue
        else:
            if client_id is None:
                client_id, password = get_nielsen_credentials()
                api_url = get_nielsen_api_url()
            try:
                xml = fetch_nielsen(isbn, session, client_id, password, api_url)
            except NielsenQuotaExceeded:
                result.quota_hit = True
                result.status[isbn] = STATUS_QUOTA
                result.opmerking[isbn] = "Probeer het morgen opnieuw; al opgehaalde data blijft bewaard"
                continue
            except requests.RequestException as exc:
                result.status[isbn] = STATUS_SOURCE_DOWN
                result.opmerking[isbn] = "Nielsen tijdelijk niet bereikbaar"
                continue
            new_entries[isbn] = xml
            cache[isbn] = xml
            result.live_fetches += 1
            from_cache = False
            time.sleep(RATE_LIMIT_SECONDS)
            if len(new_entries) % 50 == 0:
                caches.save_json_cache(caches.NIELSEN_CACHE, new_entries)

        parsed = parse_nielsen(xml, target_columns)
        if parsed:
            result.data[isbn] = parsed
            result.status[isbn] = STATUS_OK_CACHE if from_cache else STATUS_OK
            if from_cache:
                result.cache_hits += 1
            else:
                # Verzamel om naar Turso te pushen (parseer ALLE 140 kolommen,
                # niet alleen de gevraagde — dan is elke toekomstige lookup
                # compleet)
                from src.app_services import templates
                full_parsed = parse_nielsen(xml, templates.NIELSEN_DATA_COLUMNS)
                if full_parsed:
                    new_nielsen_records[isbn] = full_parsed
        else:
            result.status[isbn] = STATUS_NOT_FOUND
            result.opmerking[isbn] = "ISBN niet bekend bij Nielsen"

    caches.save_json_cache(caches.NIELSEN_CACHE, new_entries)
    # Push nieuwe Nielsen records naar Turso — gedeelde live cache
    if new_nielsen_records and turso_cache.is_enabled():
        turso_cache.upsert_nielsen(new_nielsen_records)
    return result


# ---------------------------------------------------------------------------
# Vrij zoeken bij Nielsen (tab 3)
# ---------------------------------------------------------------------------

# Veldcodes van de BDOL-zoek-API. Deze staan NIET in de leveranciers-
# documentatie en zijn op 08-09-2026 empirisch vastgesteld tegen de live API:
#   1 = ISBN        2 = titel        3 = auteur/betrokkene
# Veldcode 4 gaf inconsistente treffers en wordt bewust niet gebruikt.
FIELD_ISBN = 1
FIELD_TITEL = 2
FIELD_AUTEUR = 3

# Elke zoekopdracht kost quotum, dus standaard klein houden.
SEARCH_MAX_RESULTS = 100


@dataclass
class NielsenSearchResult:
    data: dict[str, dict[str, str]] = field(default_factory=dict)   # isbn -> {kolom: waarde}
    volgorde: list[str] = field(default_factory=list)               # isbns op relevantievolgorde
    hits: int = 0                                                   # totaal bij Nielsen
    quota_hit: bool = False
    bron_down: bool = False


def parse_nielsen_records(xml: str, target_columns: list[str]) -> list[tuple[str, dict[str, str]]]:
    """Parse ALLE records uit een zoekrespons (parse_nielsen doet alleen de eerste).

    Returnt [(isbn, {kolom: waarde}), ...] op de volgorde die Nielsen teruggeeft.
    """
    uit: list[tuple[str, dict[str, str]]] = []
    for rec in re.findall(r"<record>(.*?)</record>", xml or "", re.DOTALL):
        m = re.search(r"<ISBN13>([^<]*)</ISBN13>", rec)
        isbn = (m.group(1).strip() if m else "")
        if not isbn:
            continue
        waarden: dict[str, str] = {}
        for col in target_columns:
            mm = re.search(rf"<{re.escape(col)}>([^<]*)</{re.escape(col)}>", rec)
            if mm and mm.group(1).strip():
                waarden[col] = mm.group(1).strip()
        if waarden:
            uit.append((isbn, waarden))
    return uit


def _hits_uit_xml(xml: str) -> int:
    m = re.search(r"<hits>(\d+)</hits>", xml or "")
    return int(m.group(1)) if m else 0


def zoek(term: str, target_columns: list[str], max_results: int = 25,
         progress_cb: Callable[[int, int], None] | None = None) -> NielsenSearchResult:
    """Vrije zoekopdracht bij Nielsen op titel en auteur, of exact op ISBN.

    Een geldig ISBN-13 gaat via veldcode 1. Elke andere term wordt zowel op
    titel (2) als op auteur (3) gezocht; de resultaten worden samengevoegd met
    de titeltreffers eerst en dubbele ISBN's eruit.

    LET OP: elke call telt mee met het dagquotum van 1000. Daarom één call per
    veld, geen paginering.
    """
    from src.app_services import templates
    from src.app_services.validation import looks_like_isbn13

    result = NielsenSearchResult()
    term = (term or "").strip()
    if not term:
        return result

    max_results = max(1, min(int(max_results), SEARCH_MAX_RESULTS))
    isbn = looks_like_isbn13(term)
    velden = [FIELD_ISBN] if isbn else [FIELD_TITEL, FIELD_AUTEUR]
    zoekwaarde = isbn or term

    client_id, password = get_nielsen_credentials()
    api_url = get_nielsen_api_url()
    session = requests.Session()

    nieuwe_xml: dict[str, str] = {}
    nieuwe_records: dict[str, dict[str, str]] = {}

    for nr, veld in enumerate(velden, start=1):
        if progress_cb:
            progress_cb(nr, len(velden))
        params = {
            "clientId": client_id, "password": password,
            "from": 0, "to": max_results,
            "indexType": 0, "format": 7, "resultView": 2,
            "field0": veld, "value0": zoekwaarde, "logic0": 0,
        }
        try:
            resp = session.get(api_url, params=params, timeout=REQUEST_TIMEOUT)
        except requests.RequestException:
            result.bron_down = True
            continue

        if resp.status_code in (403, 429):
            result.quota_hit = True
            break
        if resp.status_code >= 400:
            result.bron_down = True
            continue

        tekst = resp.text
        lowered = tekst.lower()
        if any(t in lowered for t in ("quota exceeded", "daily limit", "credits exhausted")) \
                or "<resultCode>50</resultCode>" in tekst:
            result.quota_hit = True
            break

        result.hits = max(result.hits, _hits_uit_xml(tekst))

        for gevonden_isbn, waarden in parse_nielsen_records(tekst, target_columns):
            if gevonden_isbn not in result.data:
                result.data[gevonden_isbn] = waarden
                result.volgorde.append(gevonden_isbn)

        # Records uit een zoekopdracht zijn veldidentiek aan een directe
        # ISBN-lookup (geverifieerd), dus ze mogen de cache in. Dat scheelt
        # later quotum bij het verrijken van diezelfde ISBN's.
        for rec in re.findall(r"<record>(.*?)</record>", tekst, re.DOTALL):
            m = re.search(r"<ISBN13>([^<]*)</ISBN13>", rec)
            if not m:
                continue
            rec_isbn = m.group(1).strip()
            if rec_isbn:
                nieuwe_xml[rec_isbn] = f"<record>{rec}</record>"
                volledig = parse_nielsen(f"<record>{rec}</record>", templates.NIELSEN_DATA_COLUMNS)
                if volledig:
                    nieuwe_records[rec_isbn] = volledig

        if len(velden) > 1 and nr < len(velden):
            time.sleep(RATE_LIMIT_SECONDS)

    if nieuwe_xml:
        caches.save_json_cache(caches.NIELSEN_CACHE, nieuwe_xml)
    if nieuwe_records and turso_cache.is_enabled():
        turso_cache.upsert_nielsen(nieuwe_records)

    result.volgorde = result.volgorde[:max_results]
    result.data = {i: result.data[i] for i in result.volgorde}
    return result


# ---------------------------------------------------------------------------
# Leverbaarheid
# ---------------------------------------------------------------------------

# Nielsen levert leverbaarheid per afzetmarkt als code plus Engelse tekst:
#   EURNBDPAC / EURNBDPAT  (Europa)
#   UKNBDPAC  / UKNBDPAT   (Verenigd Koninkrijk)
#   USNBDPAC  / USNBDPAT   (Verenigde Staten)
# Die velden zitten al in het 141-koloms template; wat hier bijkomt is een
# leesbare, genormaliseerde kolom.
#
# De codes volgen ONIX-codelijst 65. Vastgesteld op 08-09-2026 tegen 4163
# gecachte records plus een live controlecall:
#   - de koppeling code -> tekst was in alle gevallen consistent
#   - dekking: EUR 50,7%, UK 89,5%, US 77,6%
#   - 92,0% heeft minstens een van de drie, 8,0% heeft helemaal geen waarde
#
# EUR is voor Intertaal de relevante markt, maar bij de helft van de titels
# leeg. Daarom vallen we terug op UK en daarna US, en zetten we er ALTIJD bij
# uit welke markt de waarde komt. Waar EUR en UK allebei gevuld zijn, geven ze
# in 88,3% dezelfde strekking; het verschil zit vooral in EUR-code 97 (geen
# recente update), niet in echte tegenspraak. Bij 2,0% spreken ze elkaar wel
# echt tegen, en juist daarom staat de markt er zichtbaar bij.

LEVERBAARHEID_REGIOS = (
    ("EUR", "EURNBDPAC", "EURNBDPAT"),
    ("UK", "UKNBDPAC", "UKNBDPAT"),
    ("US", "USNBDPAC", "USNBDPAT"),
)

# Nederlandse labels bij ONIX-codelijst 65. De codes met (*) kwamen in de
# steekproef daadwerkelijk voor; de overige komen uit de standaard en staan
# erbij zodat er nooit een kale code in beeld komt.
LEVERBAARHEID_LABELS = {
    "01": "Geannuleerd",                                                # *
    "10": "Nog niet verschenen",                                        # *
    "11": "Wacht op voorraad",
    "12": "Nog niet leverbaar, wordt print-on-demand",
    "20": "Leverbaar",                                                  # *
    "21": "Op voorraad",                                                # *
    "22": "Op bestelling",                                              # *
    "23": "Print-on-demand",                                            # *
    "30": "Tijdelijk niet leverbaar",                                   # *
    "31": "Niet op voorraad",                                           # *
    "32": "Wordt herdrukt",                                             # *
    "33": "Wacht op heruitgave",
    "34": "Tijdelijk uit de verkoop",                                   # *
    "40": "Niet leverbaar, reden onbekend",                             # *
    "41": "Niet leverbaar, vervangen door nieuw product",               # *
    "42": "Niet leverbaar, ander formaat wel",
    "43": "Niet meer geleverd door de leverancier",                     # *
    "44": "Rechtstreeks bij de uitgever bestellen",
    "45": "Niet los verkrijgbaar",                                      # *
    "46": "Uit de verkoop genomen",                                     # *
    "47": "Restpartij",
    "48": "Niet leverbaar, vervangen door print-on-demand",
    "49": "Teruggeroepen",
    "50": "Niet als set verkocht",
    "51": "Niet leverbaar, uitgever meldt uitverkocht",                 # *
    "52": "Niet leverbaar, uitgever verkoopt niet meer in deze markt",  # *
    "97": "Geen recente update ontvangen",                              # *
    "98": "Geen updates meer",
    "99": "Neem contact op met de leverancier",                         # *
}

# Codes die betekenen dat de titel te krijgen is. Print-on-demand (23) telt
# mee: dat is leverbaar, alleen met een langere levertijd.
LEVERBAAR_CODES = {"20", "21", "22", "23"}
# Codes die betekenen dat de titel niet te krijgen is. 97, 98 en 99 staan
# bewust in geen van beide sets: die zeggen iets over de dataleverancier, niet
# over de beschikbaarheid van het boek.
NIET_LEVERBAAR_CODES = {"01", "10", "11", "12", "30", "31", "32", "33", "34",
                        "40", "41", "42", "43", "44", "45", "46", "47", "48",
                        "49", "50", "51", "52"}


# 97 en 98 zeggen niets over het boek maar over de datafeed van die markt
# ("geen recente update", "geen updates meer"). In de steekproef stond bij 191
# titels EUR op 97 terwijl UK gewoon 'In stock' meldde. Zo'n code laten winnen
# van een echt signaal uit een andere markt maakt de kolom onbruikbaar, dus
# zoeken we eerst door naar een markt die wel iets over het boek zegt.
GEEN_SIGNAAL_CODES = {"97", "98"}


def _label(code: str, velden: dict[str, str], tekst_veld: str) -> str:
    """Nederlands label; valt terug op Nielsens eigen Engelse tekst."""
    tekst = LEVERBAARHEID_LABELS.get(code) or str(velden.get(tekst_veld) or "").strip()
    return tekst or f"Code {code}"


def leverbaarheid(velden: dict[str, str]) -> tuple[str, str, str]:
    """Leid de leverbaarheid af uit een Nielsen-record.

    Returnt (tekst, code, markt). Volgorde van voorkeur: EUR, dan UK, dan US.
    Markten waarvan de code alleen iets over de datafeed zegt (97, 98) worden
    in de eerste ronde overgeslagen; komt er nergens een echt signaal, dan
    tonen we die code alsnog in plaats van een leeg veld. Zonder enige waarde:
    ("", "", "").
    """
    # Ronde 1: een markt met een echt signaal over het boek.
    for markt, code_veld, tekst_veld in LEVERBAARHEID_REGIOS:
        code = str(velden.get(code_veld) or "").strip()
        if code and code not in GEEN_SIGNAAL_CODES:
            return (_label(code, velden, tekst_veld), code, markt)
    # Ronde 2: geen enkel echt signaal; toon wat er wel staat.
    for markt, code_veld, tekst_veld in LEVERBAARHEID_REGIOS:
        code = str(velden.get(code_veld) or "").strip()
        if code:
            return (_label(code, velden, tekst_veld), code, markt)
    return ("", "", "")


def is_leverbaar(code: str) -> str:
    """'ja', 'nee' of 'onbekend' bij een ONIX-beschikbaarheidscode."""
    code = str(code or "").strip()
    if code in LEVERBAAR_CODES:
        return "ja"
    if code in NIET_LEVERBAAR_CODES:
        return "nee"
    return "onbekend"
