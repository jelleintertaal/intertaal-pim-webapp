# -*- coding: utf-8 -*-
"""
druk_service.py — Druk (editie) per ISBN.

CB's Algolia-index bevat geen druk-veld. Bronnen, in volgorde:
  1. Bestaande caches: druk_raw_cache.json (KB.nl raw XML uit eerdere runs,
     ~25k+ ISBNs) en druk_mb_cache.json (Managementboek).
  2. Live KB.nl SRU voor cache-misses (standaard aan; ~0,4s per ISBN).

De KB-parser (parse_kb_response_v2, incl. sortkey#display-afhandeling en
Nederlandse ordinaalwoorden) wordt geïmporteerd uit de bewezen implementatie.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Callable

import requests

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.fix_druk_outliers_v2 import parse_kb_response_v2  # bewezen parser
from src.app_services import caches

KB_SRU_URL = "http://jsru.kb.nl/sru/sru"
USER_AGENT = "Intertaal-PIM/1.0 (contact: jelle@acda-rpa.nl)"
RATE_LIMIT_SECONDS = 0.35
REQUEST_TIMEOUT = 15


def druk_from_caches(isbns: list[str]) -> dict[str, str]:
    """Druk voor zover al bekend uit eerdere KB/Managementboek-runs."""
    out: dict[str, str] = {}
    kb_cache = caches.load_json_cache(caches.KB_DRUK_CACHE)
    for isbn in isbns:
        xml = kb_cache.get(isbn)
        if xml:
            druk, _bron = parse_kb_response_v2(xml)
            if druk:
                out[isbn] = druk
    mb_cache = caches.load_json_cache(caches.MB_DRUK_CACHE)
    for isbn in isbns:
        if isbn not in out and mb_cache.get(isbn):
            out[isbn] = str(mb_cache[isbn])
    return out


def druk_live_kb(isbns: list[str],
                 progress_cb: Callable[[int, int], None] | None = None) -> dict[str, str]:
    """Live KB.nl SRU-lookup voor ISBNs die nog niet in de cache zitten.

    Nieuwe raw responses worden aan de cache toegevoegd zodat volgende
    runs (webapp én lokale scripts) ze gratis hebben.
    """
    out: dict[str, str] = {}
    kb_cache = caches.load_json_cache(caches.KB_DRUK_CACHE)
    todo = [isbn for isbn in isbns if isbn not in kb_cache]
    new_entries: dict[str, str] = {}
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    for i, isbn in enumerate(todo):
        if progress_cb:
            progress_cb(i + 1, len(todo))
        params = {
            "operation": "searchRetrieve", "version": "1.2",
            "recordSchema": "dcx", "x-collection": "GGC",
            "query": f"dc.identifier={isbn}",
        }
        try:
            resp = session.get(KB_SRU_URL, params=params, timeout=REQUEST_TIMEOUT)
            xml = resp.text if resp.status_code == 200 else ""
        except requests.RequestException:
            xml = ""
        new_entries[isbn] = xml
        druk, _bron = parse_kb_response_v2(xml)
        if druk:
            out[isbn] = druk
        time.sleep(RATE_LIMIT_SECONDS)
        if len(new_entries) % 50 == 0:
            caches.save_json_cache(caches.KB_DRUK_CACHE, new_entries)

    caches.save_json_cache(caches.KB_DRUK_CACHE, new_entries)
    return out
