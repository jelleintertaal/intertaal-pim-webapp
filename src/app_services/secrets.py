# -*- coding: utf-8 -*-
"""
secrets.py — Centrale, veilige toegang tot credentials.

Volgorde per credential:
  1. Omgevingsvariabelen (Azure App Settings / lokaal gezet)
  2. .env in de projectroot (python-dotenv)
  3. Alleen voor CB: workspace/algolia_config.json (lokale fallback,
     geschreven door scripts/cb_api_export.py na browserlogin)

Foutmeldingen bevatten NOOIT secret-waarden.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(dotenv_path=PROJECT_ROOT / ".env")

ALGOLIA_CONFIG_FILE = Path(
    os.getenv("ALGOLIA_CONFIG_PATH", str(PROJECT_ROOT / "workspace" / "algolia_config.json"))
)


class MissingSecretsError(RuntimeError):
    """Credential ontbreekt; melding is veilig om aan gebruikers te tonen."""


@dataclass(frozen=True)
class AlgoliaConfig:
    app_id: str
    api_key: str
    index_name: str


def get_nielsen_credentials() -> tuple[str, str]:
    client_id = (os.getenv("NIELSEN_CLIENT_ID") or "").strip()
    password = (os.getenv("NIELSEN_PASSWORD") or "").strip()
    if not client_id or not password:
        raise MissingSecretsError(
            "Nielsen-inloggegevens ontbreken. Zet NIELSEN_CLIENT_ID en "
            "NIELSEN_PASSWORD als omgevingsvariabelen (Azure App Settings) "
            "of in het .env-bestand."
        )
    return client_id, password


def get_nielsen_api_url() -> str:
    return os.getenv(
        "NIELSEN_API_URL",
        "http://ws.nielsenbookdataonline.com/BDOLRest/RESTwebServices/BDOLrequest",
    )


def get_algolia_config() -> AlgoliaConfig:
    # 1. Env vars / Streamlit Cloud secrets (hoogste prioriteit)
    app_id = (os.getenv("CB_ALGOLIA_APP_ID") or "").strip()
    api_key = (os.getenv("CB_ALGOLIA_API_KEY") or "").strip()
    index_name = (os.getenv("CB_ALGOLIA_INDEX") or "").strip()
    if app_id and api_key and index_name:
        return AlgoliaConfig(app_id, api_key, index_name)

    # 2. Lokaal algolia_config.json (dev-machine met cb_api_export.py)
    if ALGOLIA_CONFIG_FILE.exists():
        try:
            data = json.loads(ALGOLIA_CONFIG_FILE.read_text(encoding="utf-8"))
            return AlgoliaConfig(data["app_id"], data["api_key"], data["index_name"])
        except (KeyError, ValueError):
            pass  # val door naar fallback-module

    # 3. Fallback: hardcoded in cb_key_fallback.py — dit bestand wordt
    #    automatisch bijgewerkt door de desktop-app 'CB Bestellingen'
    #    (tab 'CB koppelen') via de GitHub Contents API. Streamlit Cloud
    #    detecteert de push en redeployt binnen ~30 sec.
    try:
        from src.app_services import cb_key_fallback as _fb
        if _fb.CB_ALGOLIA_APP_ID and _fb.CB_ALGOLIA_API_KEY and _fb.CB_ALGOLIA_INDEX:
            return AlgoliaConfig(
                _fb.CB_ALGOLIA_APP_ID,
                _fb.CB_ALGOLIA_API_KEY,
                _fb.CB_ALGOLIA_INDEX,
            )
    except ImportError:
        pass

    raise MissingSecretsError(
        "CB-sleutel niet gevonden. Vraag een collega om in de desktop-app "
        "'CB Bestellingen' op tabblad 'CB koppelen' de CB-sleutel te "
        "vernieuwen; binnen 1 minuut is de webapp weer werkend."
    )
