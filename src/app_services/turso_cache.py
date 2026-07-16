# -*- coding: utf-8 -*-
"""turso_cache.py — Gedeelde live cache in Turso (SQLite-in-de-cloud).

Alle Streamlit Cloud-sessies delen deze cache — nieuwe lookups die één
gebruiker doet zijn direct beschikbaar voor de volgende gebruiker op elk
apparaat. Bij een Streamlit Cloud redeploy blijft de cache staan (Turso
is een externe service, geen ephemeral filesystem).

Read-pad: eerst Turso (schaal-onafhankelijk), val bij storing terug op de
statische JSON's in data/. Write-pad: schrijven naar Turso en (best-effort)
tegelijk naar de lokale session-JSON.

Secrets:
  TURSO_DATABASE_URL   libsql://... (van Turso dashboard)
  TURSO_AUTH_TOKEN     eyJhbGc...  (van Turso dashboard)

Wanneer beide ontbreken (bijv. lokaal ontwikkelen zonder Turso) valt alles
transparent terug op de repo-JSON's — de app blijft werken.
"""
from __future__ import annotations

import json
import os
import threading
from functools import lru_cache
from typing import Any, Sequence

import requests

REQUEST_TIMEOUT = 15
# Streamlit Cloud draait in de VS/EU; Turso EU-region geeft ~15-50ms latency.
# Bij een verzameling van N ISBN's doen we 1 grote SELECT ... WHERE isbn IN (?..?)
# in plaats van N round-trips.
MAX_IN_CLAUSE = 500


class TursoConfig:
    def __init__(self) -> None:
        url = (os.getenv("TURSO_DATABASE_URL") or "").strip()
        token = (os.getenv("TURSO_AUTH_TOKEN") or "").strip()
        if not url or not token:
            # Streamlit-secrets fallback
            try:
                import streamlit as st
                url = url or str(st.secrets.get("TURSO_DATABASE_URL", "")).strip()
                token = token or str(st.secrets.get("TURSO_AUTH_TOKEN", "")).strip()
            except Exception:
                pass
        self.url = url.replace("libsql://", "https://") if url else ""
        self.token = token
        self.enabled = bool(self.url and self.token)


@lru_cache(maxsize=1)
def _config() -> TursoConfig:
    return TursoConfig()


def is_enabled() -> bool:
    return _config().enabled


_session = threading.local()


def _get_session() -> requests.Session:
    if not hasattr(_session, "s"):
        _session.s = requests.Session()
        _session.s.headers.update({"Authorization": f"Bearer {_config().token}"})
    return _session.s


class TursoUnavailable(Exception):
    """Turso reageerde niet of gaf een fout — beller moet fallback gebruiken."""


def _pipeline(requests_body: list[dict]) -> list[dict]:
    cfg = _config()
    if not cfg.enabled:
        raise TursoUnavailable("Turso niet geconfigureerd")
    try:
        resp = _get_session().post(
            f"{cfg.url}/v2/pipeline",
            json={"requests": requests_body + [{"type": "close"}]},
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json().get("results", [])
    except (requests.RequestException, ValueError) as exc:
        raise TursoUnavailable(str(exc)) from exc


def _stmt(sql: str, args: Sequence[str] = ()) -> dict:
    return {
        "type": "execute",
        "stmt": {
            "sql": sql,
            "args": [{"type": "text", "value": str(a)} for a in args],
        },
    }


def _rows(result: dict) -> list[list[Any]]:
    resp = result.get("response", {})
    if resp.get("type") != "execute":
        return []
    return resp.get("result", {}).get("rows", [])


def _val(cell: dict) -> str:
    """Cel uit een Turso-response → string."""
    v = cell.get("value", "")
    return "" if v is None else str(v)


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------

def fetch_druks(isbns: list[str]) -> dict[str, str]:
    """Batched lookup van druk-strings. Return {} bij storing."""
    if not isbns or not is_enabled():
        return {}
    out: dict[str, str] = {}
    for chunk_start in range(0, len(isbns), MAX_IN_CLAUSE):
        chunk = isbns[chunk_start:chunk_start + MAX_IN_CLAUSE]
        placeholders = ",".join(["?"] * len(chunk))
        try:
            results = _pipeline([_stmt(
                f"SELECT isbn, druk FROM druk_lookup WHERE isbn IN ({placeholders})",
                chunk,
            )])
        except TursoUnavailable:
            return out  # deelresultaat is beter dan niks
        for row in _rows(results[0]):
            out[_val(row[0])] = _val(row[1])
    return out


def fetch_image_urls(isbns: list[str]) -> dict[str, str]:
    if not isbns or not is_enabled():
        return {}
    out: dict[str, str] = {}
    for chunk_start in range(0, len(isbns), MAX_IN_CLAUSE):
        chunk = isbns[chunk_start:chunk_start + MAX_IN_CLAUSE]
        placeholders = ",".join(["?"] * len(chunk))
        try:
            results = _pipeline([_stmt(
                f"SELECT isbn, url FROM image_urls WHERE isbn IN ({placeholders})",
                chunk,
            )])
        except TursoUnavailable:
            return out
        for row in _rows(results[0]):
            out[_val(row[0])] = _val(row[1])
    return out


def fetch_nielsen(isbns: list[str]) -> dict[str, dict[str, str]]:
    if not isbns or not is_enabled():
        return {}
    out: dict[str, dict[str, str]] = {}
    for chunk_start in range(0, len(isbns), MAX_IN_CLAUSE):
        chunk = isbns[chunk_start:chunk_start + MAX_IN_CLAUSE]
        placeholders = ",".join(["?"] * len(chunk))
        try:
            results = _pipeline([_stmt(
                f"SELECT isbn, data FROM nielsen_lookup WHERE isbn IN ({placeholders})",
                chunk,
            )])
        except TursoUnavailable:
            return out
        for row in _rows(results[0]):
            try:
                out[_val(row[0])] = json.loads(_val(row[1]))
            except ValueError:
                continue
    return out


# ---------------------------------------------------------------------------
# Write (best-effort — nooit crash bij storing)
# ---------------------------------------------------------------------------

def upsert_druks(entries: dict[str, str], source: str = "live") -> int:
    """Schrijf druks weg. Return aantal succesvol; 0 bij storing."""
    if not entries or not is_enabled():
        return 0
    ok = 0
    for chunk_start in range(0, len(entries), 100):
        chunk = list(entries.items())[chunk_start:chunk_start + 100]
        stmts = [_stmt(
            "INSERT OR REPLACE INTO druk_lookup (isbn, druk, source) VALUES (?, ?, ?)",
            (isbn, druk, source),
        ) for isbn, druk in chunk]
        try:
            _pipeline(stmts)
            ok += len(chunk)
        except TursoUnavailable:
            break
    return ok


def upsert_image_urls(entries: dict[str, str]) -> int:
    if not entries or not is_enabled():
        return 0
    ok = 0
    for chunk_start in range(0, len(entries), 100):
        chunk = list(entries.items())[chunk_start:chunk_start + 100]
        stmts = [_stmt(
            "INSERT OR REPLACE INTO image_urls (isbn, url) VALUES (?, ?)",
            (isbn, url),
        ) for isbn, url in chunk]
        try:
            _pipeline(stmts)
            ok += len(chunk)
        except TursoUnavailable:
            break
    return ok


def upsert_nielsen(entries: dict[str, dict[str, str]]) -> int:
    if not entries or not is_enabled():
        return 0
    ok = 0
    for chunk_start in range(0, len(entries), 50):
        chunk = list(entries.items())[chunk_start:chunk_start + 50]
        stmts = [_stmt(
            "INSERT OR REPLACE INTO nielsen_lookup (isbn, data) VALUES (?, ?)",
            (isbn, json.dumps(rec, ensure_ascii=False, separators=(",", ":"))),
        ) for isbn, rec in chunk]
        try:
            _pipeline(stmts)
            ok += len(chunk)
        except TursoUnavailable:
            break
    return ok


def stats() -> dict[str, int]:
    """Handige diagnose voor de UI."""
    if not is_enabled():
        return {"druk": 0, "image_urls": 0, "nielsen": 0, "enabled": 0}
    try:
        results = _pipeline([
            _stmt("SELECT COUNT(*) FROM druk_lookup"),
            _stmt("SELECT COUNT(*) FROM image_urls"),
            _stmt("SELECT COUNT(*) FROM nielsen_lookup"),
        ])
        counts = [int(_val(_rows(r)[0][0])) for r in results if _rows(r)]
        return {"druk": counts[0], "image_urls": counts[1], "nielsen": counts[2], "enabled": 1}
    except (TursoUnavailable, IndexError):
        return {"druk": 0, "image_urls": 0, "nielsen": 0, "enabled": 0}
