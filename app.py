# -*- coding: utf-8 -*-
"""
Intertaal PIM — ISBN opzoektool (Nielsen + CB).

Bewust simpel gehouden: twee tabs, beide met dezelfde flow:
  Excel uploaden -> ISBNs valideren -> bron bevragen -> Excel downloaden
  in het vaste template-format (+ Status/Bron-kolommen achteraan).

Geen scrapers, geen database, geen subprocess-aanroepen: de oude
beheersfunctionaliteit is verwijderd (archief: _archive/app-legacy/).
Uploads blijven in-memory per gebruikerssessie; er wordt niets van de
upload op schijf bewaard. Secrets komen uit env vars / .env en worden
nooit in de interface of de output getoond.
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import streamlit as st

from src.app_services import templates
from src.app_services import nielsen_service, cb_service
from src.app_services.output import build_output_df, df_to_xlsx_bytes
from src.app_services.secrets import MissingSecretsError, get_algolia_config, get_nielsen_credentials
from src.app_services.validation import (
    UploadError, parse_upload, unique_valid_isbns,
    STATUS_OK, STATUS_OK_CACHE, STATUS_NOT_FOUND,
)

st.set_page_config(page_title="Intertaal PIM — ISBN opzoeken", page_icon="📚", layout="centered")


def _require_password() -> None:
    """Simpele wachtwoord-poort. Wachtwoord komt uit env var of Streamlit
    secrets (APP_PASSWORD). Als er geen wachtwoord is ingesteld, staat de
    app open (handig voor lokaal ontwikkelen)."""
    import os as _os
    expected = _os.getenv("APP_PASSWORD", "").strip()
    try:
        if not expected and "APP_PASSWORD" in st.secrets:
            expected = str(st.secrets["APP_PASSWORD"]).strip()
    except Exception:
        pass
    if not expected:
        return  # geen wachtwoord ingesteld -> vrije toegang

    if st.session_state.get("_auth_ok"):
        return

    st.title("📚 Intertaal PIM — ISBN opzoeken")
    st.markdown("Deze tool is alleen voor Intertaal-medewerkers. Voer het gedeelde wachtwoord in.")
    pw = st.text_input("Wachtwoord", type="password", key="_auth_pw")
    if st.button("Inloggen", type="primary"):
        if pw == expected:
            st.session_state["_auth_ok"] = True
            st.rerun()
        else:
            st.error("Onjuist wachtwoord.")
    st.stop()


_require_password()

st.title("📚 Intertaal PIM — ISBN opzoeken")
st.caption(
    "Upload een Excel met ISBN's, kies de bron en download het verrijkte "
    "bestand in het vaste format."
)

tab_nielsen, tab_cb = st.tabs(["Nielsen opzoeken", "CB opzoeken"])


def _toon_upload_info(rows, kolom, extra: str = "") -> None:
    geldig = [r for r in rows if r.isbn]
    uniek = unique_valid_isbns(rows)
    tekst = (f"**{len(rows)}** rijen gelezen — **{len(geldig)}** geldige ISBN's "
             f"(**{len(uniek)}** uniek), kolom: `{kolom}`")
    if len(geldig) < len(rows):
        tekst += f" — {len(rows) - len(geldig)} rij(en) zonder geldig ISBN (blokkeren niets)"
    st.info(tekst + (f"\n\n{extra}" if extra else ""))


def _download_knop(df, prefix: str, key: str) -> None:
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    st.download_button(
        label="⬇️ Download verrijkt Excel-bestand",
        data=df_to_xlsx_bytes(df),
        file_name=f"{prefix}_{stamp}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key=key,
    )
    st.dataframe(df.head(25), use_container_width=True)


# ---------------------------------------------------------------------------
# Tab 1 — Nielsen opzoeken
# ---------------------------------------------------------------------------
with tab_nielsen:
    st.subheader("Nielsen opzoeken")
    st.markdown(
        "Zoekt ISBN's op in Nielsen BookData en levert het vaste "
        "141-koloms format. **Let op:** Nielsen staat ±1000 nieuwe "
        "opzoekingen per dag toe; eerder opgezochte ISBN's komen uit de "
        "cache en tellen niet mee."
    )

    nl_file = st.file_uploader("Excel met ISBN's", type=["xlsx", "xls"], key="nl_upload")

    if nl_file is not None:
        try:
            nl_rows, nl_kolom = parse_upload(nl_file)
        except UploadError as exc:
            st.error(str(exc))
        else:
            nl_uniek = unique_valid_isbns(nl_rows)
            cache_hits = nielsen_service.count_cache_hits(nl_uniek)
            live_nodig = len(nl_uniek) - cache_hits
            extra = f"Nielsen: **{cache_hits}** al in cache, **{live_nodig}** live op te halen."
            if live_nodig > 1000:
                extra += (" ⚠️ Dat is meer dan het dagquotum (1000): een deel krijgt de "
                          "status *dagquotum bereikt* en kan morgen opnieuw.")
            _toon_upload_info(nl_rows, nl_kolom, extra)

            if st.button("Start Nielsen-opzoeking", type="primary", key="nl_start",
                         disabled=not nl_uniek):
                try:
                    get_nielsen_credentials()  # vroege, duidelijke fout
                except MissingSecretsError as exc:
                    st.error(str(exc))
                else:
                    voortgang = st.progress(0.0, text="Nielsen-opzoeking gestart...")

                    def _nl_progress(done: int, total: int) -> None:
                        voortgang.progress(done / total,
                                           text=f"Nielsen: {done}/{total} ISBN's verwerkt")

                    resultaat = nielsen_service.enrich(
                        nl_uniek, templates.NIELSEN_DATA_COLUMNS, progress_cb=_nl_progress)
                    voortgang.progress(1.0, text="Klaar")

                    for row in nl_rows:
                        if row.isbn:
                            row.status = resultaat.status.get(row.isbn, STATUS_NOT_FOUND)
                            row.opmerking = resultaat.opmerking.get(row.isbn, "")

                    bron = {isbn: "Nielsen" for isbn in resultaat.data}
                    df = build_output_df(nl_rows, resultaat.data,
                                         templates.NIELSEN_COLUMNS,
                                         templates.NIELSEN_ISBN_COL, bron)
                    st.session_state["nl_output"] = df

                    ok = sum(1 for r in nl_rows if r.status in (STATUS_OK, STATUS_OK_CACHE))
                    melding = (f"Klaar: {ok} van {len(nl_rows)} rijen met Nielsen-data "
                               f"({resultaat.cache_hits} uit cache, {resultaat.live_fetches} live).")
                    if resultaat.quota_hit:
                        st.warning(melding + " Het dagquotum is bereikt — de resterende "
                                             "ISBN's staan gemarkeerd en kunnen morgen opnieuw.")
                    else:
                        st.success(melding)

    if "nl_output" in st.session_state:
        _download_knop(st.session_state["nl_output"], "nielsen_verrijkt", "nl_download")


# ---------------------------------------------------------------------------
# Tab 2 — CB opzoeken
# ---------------------------------------------------------------------------
with tab_cb:
    st.subheader("CB opzoeken")
    st.markdown(
        "Zoekt ISBN's op in CB Online (Centraal Boekhuis) en levert het "
        "vaste 50-koloms format met alle CB-metadata én een grotere cover-URL "
        "(ImageUrl_nieuw, uit hetzelfde Boekhuis-ecosysteem)."
    )

    cb_file = st.file_uploader("Excel met ISBN's", type=["xlsx", "xls"], key="cb_upload")

    if cb_file is not None:
        try:
            cb_rows, cb_kolom = parse_upload(cb_file)
        except UploadError as exc:
            st.error(str(exc))
        else:
            cb_uniek = unique_valid_isbns(cb_rows)
            _toon_upload_info(cb_rows, cb_kolom)

            if st.button("Start CB-opzoeking", type="primary", key="cb_start",
                         disabled=not cb_uniek):
                try:
                    cfg = get_algolia_config()
                except MissingSecretsError as exc:
                    st.error(str(exc))
                else:
                    voortgang = st.progress(0.0, text="CB-opzoeking gestart...")
                    try:
                        records = cb_service.fetch_cb_records(
                            cb_uniek, cfg,
                            progress_cb=lambda b, t: voortgang.progress(
                                min(b / t, 1.0), text=f"CB: batch {b}/{t}"))
                    except (cb_service.CBAuthError, cb_service.CBServiceError) as exc:
                        st.error(str(exc))
                        records = None

                    if records is not None:
                        gevonden = [i for i in cb_uniek if i in records]
                        voortgang.progress(1.0, text="Klaar")

                        data_by_isbn = {
                            isbn: cb_service.build_cb_row(isbn, records[isbn])
                            for isbn in gevonden
                        }
                        bron = {}
                        for row in cb_rows:
                            if not row.isbn:
                                continue
                            if row.isbn in records:
                                row.status = STATUS_OK
                                bron[row.isbn] = "CB"
                            else:
                                row.status = STATUS_NOT_FOUND
                                row.opmerking = "ISBN niet bekend bij CB"

                        df = build_output_df(cb_rows, data_by_isbn,
                                             templates.CB_COLUMNS, templates.CB_ISBN_COL,
                                             bron)
                        st.session_state["cb_output"] = df
                        st.success(f"Klaar: {len(gevonden)} van {len(cb_uniek)} unieke "
                                   f"ISBN's gevonden bij CB.")

    if "cb_output" in st.session_state:
        _download_knop(st.session_state["cb_output"], "cb_verrijkt", "cb_download")
