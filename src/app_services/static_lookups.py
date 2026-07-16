# -*- coding: utf-8 -*-
"""static_lookups.py — Historische lookup-data die met de repo mee-komt.

Deze bestanden in data/ worden gegenereerd door scripts/build_static_caches.py
uit de lokale PIM-caches en committed naar de repo. Zo heeft Streamlit Cloud
direct toegang tot alle ISBN's die we eerder al opzochten (~13k druks,
~30k images, ~4k Nielsen records) zonder dat er een externe database nodig is.

De lookups zijn read-only. Live opgevraagde data wordt tijdens de sessie
gecacht in workspace/ (zie caches.py) maar verdwijnt bij de volgende deploy;
draai periodiek build_static_caches.py om nieuwe lookups permanent te maken.

Gebruik:
    from src.app_services import static_lookups
    druk = static_lookups.get_druks()           # dict {isbn: druk-string}
    urls = static_lookups.get_image_urls()      # dict {isbn: url}
    nl   = static_lookups.get_nielsen()         # dict {isbn: {kolom: waarde}}
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[2] / "data"


def _load(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


@lru_cache(maxsize=1)
def get_druks() -> dict[str, str]:
    """Historische druk-lookups per ISBN. Bij ontbrekend bestand: lege dict."""
    return _load(DATA_DIR / "druk_lookup.json")


@lru_cache(maxsize=1)
def get_image_urls() -> dict[str, str]:
    """Historische geverifieerde cover-URL's per ISBN."""
    return _load(DATA_DIR / "image_urls.json")


@lru_cache(maxsize=1)
def get_nielsen() -> dict[str, dict[str, str]]:
    """Historische Nielsen-records per ISBN (alle 140 template-kolommen)."""
    return _load(DATA_DIR / "nielsen_lookup.json")


def stats() -> dict[str, int]:
    """Aantal ISBN's per lookup-bestand — handig voor de UI."""
    return {
        "druk": len(get_druks()),
        "image_urls": len(get_image_urls()),
        "nielsen": len(get_nielsen()),
    }
