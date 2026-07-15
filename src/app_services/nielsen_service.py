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

from src.app_services import caches
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
    cache = caches.load_json_cache(caches.NIELSEN_CACHE)
    return sum(1 for isbn in isbns if isbn in cache)


def enrich(isbns: list[str], target_columns: list[str],
           progress_cb: Callable[[int, int], None] | None = None,
           max_live: int | None = None) -> NielsenResult:
    """Verrijk unieke ISBNs: cache eerst, dan live tot het quotum.

    max_live is een testhaakje om quota-gedrag te simuleren.
    """
    result = NielsenResult()
    cache = caches.load_json_cache(caches.NIELSEN_CACHE)
    new_entries: dict[str, str] = {}
    session = requests.Session()
    client_id = password = api_url = None

    total = len(isbns)
    for i, isbn in enumerate(isbns):
        if progress_cb:
            progress_cb(i + 1, total)

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
            result.status[isbn] = STATUS_NOT_FOUND
            result.opmerking[isbn] = "ISBN niet bekend bij Nielsen"

    caches.save_json_cache(caches.NIELSEN_CACHE, new_entries)
    return result
