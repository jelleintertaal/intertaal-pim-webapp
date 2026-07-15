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
    app_id = (os.getenv("CB_ALGOLIA_APP_ID") or "").strip()
    api_key = (os.getenv("CB_ALGOLIA_API_KEY") or "").strip()
    index_name = (os.getenv("CB_ALGOLIA_INDEX") or "").strip()
    if app_id and api_key and index_name:
        return AlgoliaConfig(app_id, api_key, index_name)

    if ALGOLIA_CONFIG_FILE.exists():
        try:
            data = json.loads(ALGOLIA_CONFIG_FILE.read_text(encoding="utf-8"))
            return AlgoliaConfig(data["app_id"], data["api_key"], data["index_name"])
        except (KeyError, ValueError) as exc:
            raise MissingSecretsError(
                "CB-configuratiebestand is onleesbaar of onvolledig. "
                "Zie docs/runbook-cb-key.md om de CB-sleutel te vernieuwen."
            ) from exc

    raise MissingSecretsError(
        "CB-sleutel niet gevonden. Zet CB_ALGOLIA_APP_ID, CB_ALGOLIA_API_KEY "
        "en CB_ALGOLIA_INDEX als omgevingsvariabelen (Azure App Settings), "
        "of draai lokaal scripts/cb_api_export.py --force-login. "
        "Zie docs/runbook-cb-key.md."
    )
