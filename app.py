# -*- coding: utf-8 -*-
"""
Intertaal PIM — ISBN opzoektool (Nielsen + CB), in Intertaal-huisstijl.

Views (st.session_state.view): home -> nielsen | cb.
Zelfde flow als voorheen per tool: Excel uploaden -> ISBNs valideren ->
bron bevragen -> Excel downloaden in het vaste template-format.

Huisstijl overgenomen van intertaalid.nl (Shopify-thema CSS-variabelen):
  oranje #d2701c (koppen/accenten), groen #6eaa41 (primaire acties),
  blauw #0073b7 (secundair), paars #51396d, achtergrond #f3f5f6, font Inter.
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
    looks_like_isbn13, rows_from_isbns,
    STATUS_OK, STATUS_OK_CACHE, STATUS_NOT_FOUND,
)

LOGO_URL = "https://intertaalid.nl/cdn/shop/files/Naam_logo_255x@2x.png?v=1747650479"
FAVICON_URL = "https://intertaalid.nl/cdn/shop/files/FAVICON_INTERAAL_ID_96x96.png?v=1748509516"

st.set_page_config(
    page_title="Intertaal PIM",
    page_icon=FAVICON_URL,
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ---------------------------------------------------------------------------
# Huisstijl-CSS (Intertaalid.nl-palet + interactieve kaarten)
# ---------------------------------------------------------------------------

_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

:root {
    --it-oranje: #d2701c;
    --it-groen: #6eaa41;
    --it-groen-donker: #5c8f36;
    --it-blauw: #0073b7;
    --it-blauw-donker: #00436b;
    --it-paars: #51396d;
    --it-grijs: #f3f5f6;
    --it-border: #e1e3e4;
}

html, body, [class*="css"], .stMarkdown, button, input {
    font-family: 'Inter', sans-serif !important;
}

/* Streamlit-chrome verbergen + compact bovenaan */
#MainMenu, footer, header[data-testid="stHeader"] { display: none !important; }
.block-container {
    padding-top: 1.2rem !important;
    padding-bottom: 1rem !important;
    max-width: 1240px;
}

/* ------- Brand header ------- */
.pim-header {
    display: flex; align-items: center; gap: 1.2rem;
    padding: .4rem 0 1rem 0;
    border-bottom: 3px solid var(--it-oranje);
    margin-bottom: 1.4rem;
}
.pim-header img { height: 46px; }
/* Kleur bewust GEERFD van Streamlits thema, niet hardgecodeerd.
   Deze titel staat als enige tekst direct op de app-achtergrond (de kaarten
   hebben hun eigen witte vlak). Met een vaste #1a1a1a was hij in donkere modus
   onleesbaar: contrast 1.09:1 op de donkere achtergrond #0e1117.
   Streamlit zet de tekstkleur van body per thema (#31333f licht, #fafafa
   donker), dus 'inherit' geeft in beide thema's maximaal contrast.
   Let op: .streamlit/config.toml (base = "light") staat NIET in de
   deploy-whitelist, dus op Azure volgt het thema de browserinstelling. */
.pim-header .pim-title {
    font-size: 1.5rem; font-weight: 700; color: inherit; letter-spacing: -.02em;
}
.pim-header .pim-title span { color: var(--it-oranje); }
.pim-header .pim-sub {
    margin-left: auto; color: var(--it-oranje); font-size: .95rem; font-weight: 700;
}

/* ------- Grote keuzekaarten (home) ------- */
div[class*="st-key-card_"] {
    background: #ffffff;
    border: 1px solid var(--it-border);
    border-radius: 22px;
    padding: 2.4rem 2.2rem 1.6rem 2.2rem;
    position: relative;
    overflow: hidden;
    transition: transform .28s cubic-bezier(.2,.8,.3,1), box-shadow .28s;
    min-height: 430px;
}
/* Drie kaarten naast elkaar: iets compacter zodat ze in 1 viewport passen. */
@media (min-width: 900px) {
    div[class*="st-key-card_"] { padding: 2rem 1.7rem 1.5rem 1.7rem; min-height: 415px; }
}

/* ------- Kaarten even hoog, knoppen op één lijn -------
   De kaartteksten en badges wikkelen over verschillend veel regels, waardoor
   de kaarten anders hoog werden (435 / 460 / 500 px) en de knoppen op drie
   verschillende hoogtes stonden. De kolom rekt al mee; alleen Streamlits
   tussenwrapper deed dat niet. Die stretchen we, de kaart vult hem, en de
   knop wordt met margin-top:auto naar de onderkant geduwd.
   De min-height hierboven blijft als terugval als Streamlit ooit andere
   data-testid's gebruikt. */
[data-testid="stColumn"] > [data-testid="stVerticalBlock"] > [data-testid="stLayoutWrapper"] {
    flex: 1 1 auto;
    height: 100%;
}
div[class*="st-key-card_"] {
    display: flex;
    flex-direction: column;
    height: 100%;
}
/* Streamlit zet om elk element een stElementContainer; dat zijn de echte
   flex-kinderen van de kaart. De margin-top moet daar staan, niet op de knop
   zelf, anders gebeurt er niets. */
div[class*="st-key-card_"] > [data-testid="stElementContainer"]:last-child {
    margin-top: auto;
    width: 100%;
}
div[class*="st-key-card_"]::before {
    content: ""; position: absolute; top: 0; left: 0; right: 0; height: 7px;
    transform: scaleX(0); transform-origin: left;
    transition: transform .35s cubic-bezier(.2,.8,.3,1);
}
.st-key-card_nielsen::before { background: linear-gradient(90deg, var(--it-blauw), #37a3e0); }
.st-key-card_cb::before      { background: linear-gradient(90deg, var(--it-oranje), #f0a04b); }
.st-key-card_zoeken::before  { background: linear-gradient(90deg, var(--it-paars), #8768ad); }
div[class*="st-key-card_"]:hover {
    transform: translateY(-8px);
    box-shadow: 0 22px 48px rgba(0,0,0,.13);
}
div[class*="st-key-card_"]:hover::before { transform: scaleX(1); }

.pim-card-icon {
    width: 84px; height: 84px; border-radius: 20px;
    display: flex; align-items: center; justify-content: center;
    font-size: 2.6rem; margin-bottom: 1.1rem;
    transition: transform .3s;
}
div[class*="st-key-card_"]:hover .pim-card-icon { transform: scale(1.12) rotate(-4deg); }
.pim-icon-blauw  { background: rgba(0,115,183,.10); }
.pim-icon-oranje { background: rgba(210,112,28,.10); }
.pim-icon-paars  { background: rgba(81,57,109,.10); }

.pim-card-titel { font-size: 1.7rem; font-weight: 800; color: #1a1a1a; margin-bottom: .4rem; letter-spacing: -.02em; }
.pim-card-tekst { color: #5a6165; font-size: 1.02rem; line-height: 1.55; margin-bottom: 1rem; }
.pim-badges { display: flex; gap: .5rem; flex-wrap: wrap; margin-bottom: .4rem; }
.pim-badge {
    padding: .34rem .8rem; border-radius: 999px;
    font-size: .82rem; font-weight: 600;
}
.pim-badge-blauw  { background: rgba(0,115,183,.10); color: var(--it-blauw); }
.pim-badge-oranje { background: rgba(210,112,28,.10); color: var(--it-oranje); }
.pim-badge-groen  { background: rgba(110,170,65,.12); color: #4e7a2e; }
.pim-badge-paars  { background: rgba(81,57,109,.10); color: var(--it-paars); }

/* Kaart-knoppen: groot en in kaartkleur */
.st-key-card_nielsen .stButton button,
.st-key-card_cb .stButton button,
.st-key-card_zoeken .stButton button {
    width: 100%; padding: .95rem 1.4rem;
    font-size: 1.08rem; font-weight: 700;
    border-radius: 14px; border: none; color: #fff;
    transition: filter .2s, transform .15s;
}
.st-key-card_nielsen .stButton button { background: var(--it-blauw); }
.st-key-card_cb .stButton button      { background: var(--it-oranje); }
.st-key-card_zoeken .stButton button  { background: var(--it-paars); }
.st-key-card_nielsen .stButton button:hover,
.st-key-card_cb .stButton button:hover,
.st-key-card_zoeken .stButton button:hover { filter: brightness(1.12); transform: scale(1.02); color: #fff; }

/* ------- Tool-views ------- */
.pim-terug .stButton button {
    background: transparent; border: 1.5px solid var(--it-border);
    border-radius: 10px; color: #444; font-weight: 600;
    transition: border-color .2s, color .2s;
}
.pim-terug .stButton button:hover { border-color: var(--it-oranje); color: var(--it-oranje); }

/* Upload-dropzone groot en on-brand */
[data-testid="stFileUploaderDropzone"] {
    min-height: 150px;
    border: 2.5px dashed var(--it-border) !important;
    border-radius: 18px !important;
    background: #fbfcfc !important;
    transition: border-color .25s, background .25s, transform .2s;
}
[data-testid="stFileUploaderDropzone"]:hover {
    border-color: var(--it-groen) !important;
    background: rgba(110,170,65,.05) !important;
    transform: scale(1.01);
}

/* Metric-tegels */
.pim-metrics { display: flex; gap: .9rem; margin: .3rem 0 .9rem 0; }
.pim-metric {
    flex: 1; background: #fff; border: 1px solid var(--it-border);
    border-radius: 16px; padding: 1rem .6rem; text-align: center;
    transition: transform .2s, box-shadow .2s;
}
.pim-metric:hover { transform: translateY(-3px); box-shadow: 0 8px 22px rgba(0,0,0,.08); }
.pim-metric .m-waarde { font-size: 1.9rem; font-weight: 800; line-height: 1.1; }
.pim-metric .m-label  { font-size: .82rem; color: #6a7175; font-weight: 600; margin-top: .2rem; }
.m-blauw  { color: var(--it-blauw); }
.m-groen  { color: var(--it-groen); }
.m-oranje { color: var(--it-oranje); }
.m-paars  { color: var(--it-paars); }

/* Start/download-knoppen groot en groen */
.pim-actie .stButton button, .stDownloadButton button {
    width: 100%; padding: 1rem 1.5rem;
    background: var(--it-groen); color: #fff;
    font-size: 1.12rem; font-weight: 700;
    border: none; border-radius: 14px;
    transition: background .2s, transform .15s, box-shadow .2s;
}
.pim-actie .stButton button:hover, .stDownloadButton button:hover {
    background: var(--it-groen-donker); color: #fff;
    transform: translateY(-2px); box-shadow: 0 10px 26px rgba(110,170,65,.35);
}
.pim-actie .stButton button:disabled { background: #c6cdd0; }

/* Voortgangsbalk in brand-groen */
.stProgress > div > div > div > div { background: var(--it-groen) !important; }

/* ------- Vrij zoeken (tab 3) ------- */
.pim-zoekblok [data-testid="stTextInput"] input {
    font-size: 1.1rem; padding: .9rem 1.1rem;
    border-radius: 14px; border: 2px solid var(--it-border);
    transition: border-color .2s, box-shadow .2s;
}
.pim-zoekblok [data-testid="stTextInput"] input:focus {
    border-color: var(--it-paars);
    box-shadow: 0 0 0 4px rgba(81,57,109,.10);
}
.pim-zoekblok [data-testid="stFormSubmitButton"] button {
    width: 100%; padding: .92rem 1.5rem;
    background: var(--it-paars); color: #fff;
    font-size: 1.08rem; font-weight: 700;
    border: none; border-radius: 14px;
    transition: filter .2s, transform .15s, box-shadow .2s;
}
.pim-zoekblok [data-testid="stFormSubmitButton"] button:hover {
    filter: brightness(1.15); color: #fff;
    transform: translateY(-2px); box-shadow: 0 10px 26px rgba(81,57,109,.30);
}
.pim-zoek-hint { color: #6a7175; font-size: .9rem; margin: .1rem 0 .2rem 0; }

/* Exact-publicatieknop (nog op slot): bewust aanwezig maar gedimd */
div[class*="st-key-"][class*="_exactblok"] .stButton button {
    width: 100%; padding: 1rem 1.5rem;
    font-size: 1.12rem; font-weight: 700;
    border-radius: 14px;
    border: 2px dashed #c6cdd0;
    background: var(--it-grijs); color: #8a9297;
    cursor: not-allowed;
    transition: border-color .25s, color .25s;
}
div[class*="st-key-"][class*="_exactblok"] .stButton button:hover {
    border-color: var(--it-paars); color: var(--it-paars);
}
.pim-exact-hint {
    text-align: center; color: #8a9297;
    font-size: .8rem; font-weight: 600; margin-top: .35rem;
    letter-spacing: .02em; text-transform: uppercase;
}

/* Login */
.pim-login {
    max-width: 430px; margin: 8vh auto 0 auto; text-align: center;
    background: #fff; border: 1px solid var(--it-border); border-radius: 22px;
    padding: 2.6rem 2.4rem; box-shadow: 0 18px 44px rgba(0,0,0,.08);
}
.pim-login img { height: 52px; margin-bottom: 1.2rem; }
</style>
"""


def _inject_css() -> None:
    st.markdown(_CSS, unsafe_allow_html=True)


def _brand_header(subtitel: str) -> None:
    st.markdown(
        f"""
        <div class="pim-header">
            <img src="{LOGO_URL}" alt="Intertaal" />
            <div class="pim-title">PIM <span>&middot;</span> {subtitel}</div>
            <div class="pim-sub">Product Informatie Management</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _metric_tegels(items: list[tuple[str, str, str]]) -> None:
    """items: (waarde, label, kleurklasse)"""
    tegels = "".join(
        f'<div class="pim-metric"><div class="m-waarde {kleur}">{waarde}</div>'
        f'<div class="m-label">{label}</div></div>'
        for waarde, label, kleur in items
    )
    st.markdown(f'<div class="pim-metrics">{tegels}</div>', unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Wachtwoord-poort (gebrand)
# ---------------------------------------------------------------------------

def _require_password() -> None:
    import os as _os
    expected = _os.getenv("APP_PASSWORD", "").strip()
    try:
        if not expected and "APP_PASSWORD" in st.secrets:
            expected = str(st.secrets["APP_PASSWORD"]).strip()
    except Exception:
        pass
    if not expected or st.session_state.get("_auth_ok"):
        return

    _inject_css()
    st.markdown(
        f"""<div class="pim-login"><img src="{LOGO_URL}" alt="Intertaal"/>
        <div style="font-size:1.25rem;font-weight:700;margin-bottom:.3rem;">PIM &mdash; ISBN opzoeken</div>
        <div style="color:#6a7175;font-size:.95rem;margin-bottom:.6rem;">
        Alleen voor Intertaal-medewerkers.</div></div>""",
        unsafe_allow_html=True,
    )
    _, mid, _ = st.columns([1, 1.2, 1])
    with mid:
        pw = st.text_input("Wachtwoord", type="password", key="_auth_pw",
                           label_visibility="collapsed", placeholder="Wachtwoord")
        with st.container(key="login_actie"):
            st.markdown('<div class="pim-actie">', unsafe_allow_html=True)
            if st.button("Inloggen", key="login_btn", use_container_width=True):
                if pw == expected:
                    st.session_state["_auth_ok"] = True
                    st.rerun()
                else:
                    st.error("Onjuist wachtwoord.")
            st.markdown('</div>', unsafe_allow_html=True)
    st.stop()


# ---------------------------------------------------------------------------
# Gedeelde bouwstenen
# ---------------------------------------------------------------------------

def _terug_knop() -> None:
    with st.container(key="terugblok"):
        st.markdown('<div class="pim-terug">', unsafe_allow_html=True)
        if st.button("← Terug naar overzicht", key=f"terug_{st.session_state.view}"):
            st.session_state.view = "home"
            st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)


def _resultaat_blok(df, prefix: str, key_prefix: str) -> None:
    """Resultaat: bewerken -> downloaden -> (straks) publiceren naar Exact.

    De data-editor bewaart bewerkingen per sessie (widget-state op key);
    de download en de toekomstige Exact-publicatie gebruiken de BEWERKTE
    versie, niet de ruwe opzoek-output.
    """
    with st.expander("✏️  Output bekijken & bewerken", expanded=False):
        st.caption(
            "Pas velden direct aan in de tabel. De download — en straks de "
            "publicatie naar Exact — gebruiken jouw bewerkte versie."
        )
        edited = st.data_editor(
            df, use_container_width=True, height=420,
            num_rows="fixed", key=f"{key_prefix}_editor",
        )

    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    col_dl, col_exact = st.columns(2, gap="medium")
    with col_dl:
        st.download_button(
            label="⬇️  Download verrijkt Excel-bestand",
            data=df_to_xlsx_bytes(edited),
            file_name=f"{prefix}_{stamp}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key=f"{key_prefix}_download",
            use_container_width=True,
        )
    with col_exact:
        with st.container(key=f"{key_prefix}_exactblok"):
            st.button(
                "🔒  Publiceer producten naar Exact",
                key=f"{key_prefix}_exact",
                disabled=True,
                use_container_width=True,
                help="De Exact Online-koppeling is in voorbereiding. Zodra die "
                     "live is, zet deze knop de bewerkte producten in de "
                     "publicatie-wachtrij.",
            )
            st.markdown(
                '<div class="pim-exact-hint">Exact-koppeling in voorbereiding</div>',
                unsafe_allow_html=True,
            )


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------

def view_home() -> None:
    _brand_header("ISBN opzoeken")
    col1, col2, col3 = st.columns(3, gap="large")

    with col1:
        with st.container(key="card_nielsen"):
            st.markdown(
                """
                <div class="pim-card-icon pim-icon-blauw">🌍</div>
                <div class="pim-card-titel">Nielsen opzoeken</div>
                <div class="pim-card-tekst">Internationale titels verrijken via
                Nielsen BookData. Volledige metadata in het vaste
                141&#8209;koloms format.</div>
                <div class="pim-badges">
                    <span class="pim-badge pim-badge-blauw">141 kolommen</span>
                    <span class="pim-badge pim-badge-paars">1000 per dag</span>
                    <span class="pim-badge pim-badge-groen">cache is gratis</span>
                </div>
                """,
                unsafe_allow_html=True,
            )
            if st.button("Start met Nielsen  →", key="go_nielsen", use_container_width=True):
                st.session_state.view = "nielsen"
                st.rerun()

    with col2:
        with st.container(key="card_cb"):
            st.markdown(
                """
                <div class="pim-card-icon pim-icon-oranje">📚</div>
                <div class="pim-card-titel">CB opzoeken</div>
                <div class="pim-card-tekst">Nederlandse en Vlaamse titels verrijken
                via CB (Centraal Boekhuis). Alle CB&#8209;metadata plus grote
                cover&#8209;URL in het 50&#8209;koloms format.</div>
                <div class="pim-badges">
                    <span class="pim-badge pim-badge-oranje">50 kolommen</span>
                    <span class="pim-badge pim-badge-blauw">supersnel</span>
                    <span class="pim-badge pim-badge-groen">incl. leverbaarheid</span>
                </div>
                """,
                unsafe_allow_html=True,
            )
            if st.button("Start met CB  →", key="go_cb", use_container_width=True):
                st.session_state.view = "cb"
                st.rerun()

    with col3:
        with st.container(key="card_zoeken"):
            st.markdown(
                """
                <div class="pim-card-icon pim-icon-paars">🔎</div>
                <div class="pim-card-titel">Vrij zoeken</div>
                <div class="pim-card-tekst">Zoek in de CB&#8209;catalogus op auteur,
                titel of ISBN &mdash; zonder bestand. Alle treffers meteen in beeld,
                met cover en leverbaarheid.</div>
                <div class="pim-badges">
                    <span class="pim-badge pim-badge-paars">geen upload nodig</span>
                    <span class="pim-badge pim-badge-blauw">auteur &middot; titel &middot; ISBN</span>
                    <span class="pim-badge pim-badge-groen">zelfde 50 kolommen</span>
                </div>
                """,
                unsafe_allow_html=True,
            )
            if st.button("Start met zoeken  →", key="go_zoeken", use_container_width=True):
                st.session_state.view = "zoeken"
                st.rerun()


def view_nielsen() -> None:
    _brand_header("Nielsen opzoeken")
    _terug_knop()

    col_upload, col_info = st.columns([1.15, 1], gap="large")
    with col_upload:
        nl_file = st.file_uploader("Excel met ISBN's", type=["xlsx", "xls"], key="nl_upload")
    rows = kolom = None
    if nl_file is not None:
        try:
            rows, kolom = parse_upload(nl_file)
        except UploadError as exc:
            with col_info:
                st.error(str(exc))

    if rows is not None:
        uniek = unique_valid_isbns(rows)
        geldig = [r for r in rows if r.isbn]
        cache_hits = nielsen_service.count_cache_hits(uniek)
        live_nodig = len(uniek) - cache_hits
        with col_info:
            _metric_tegels([
                (f"{len(rows)}", "rijen", "m-paars"),
                (f"{len(uniek)}", "unieke ISBN's", "m-blauw"),
                (f"{cache_hits}", "uit cache", "m-groen"),
                (f"{live_nodig}", "live nodig", "m-oranje"),
            ])
            if live_nodig > 1000:
                st.warning("Meer dan het dagquotum (1000): een deel krijgt de status "
                           "*dagquotum bereikt* en kan morgen opnieuw.")
            if len(geldig) < len(rows):
                st.caption(f"{len(rows) - len(geldig)} rij(en) zonder geldig ISBN — blokkeren niets. "
                           f"Kolom: `{kolom}`")
            with st.container(key="nl_actieblok"):
                st.markdown('<div class="pim-actie">', unsafe_allow_html=True)
                start = st.button("🚀  Start Nielsen-opzoeking", key="nl_start",
                                  disabled=not uniek, use_container_width=True)
                st.markdown('</div>', unsafe_allow_html=True)

        if start:
            try:
                get_nielsen_credentials()
            except MissingSecretsError as exc:
                st.error(str(exc))
            else:
                voortgang = st.progress(0.0, text="Nielsen-opzoeking gestart...")

                def _nl_progress(done: int, total: int) -> None:
                    voortgang.progress(done / total, text=f"Nielsen: {done}/{total} ISBN's verwerkt")

                resultaat = nielsen_service.enrich(
                    uniek, templates.NIELSEN_DATA_COLUMNS, progress_cb=_nl_progress)
                voortgang.progress(1.0, text="Klaar")

                for row in rows:
                    if row.isbn:
                        row.status = resultaat.status.get(row.isbn, STATUS_NOT_FOUND)
                        row.opmerking = resultaat.opmerking.get(row.isbn, "")

                bron = {isbn: "Nielsen" for isbn in resultaat.data}
                df = build_output_df(rows, resultaat.data, templates.NIELSEN_COLUMNS,
                                     templates.NIELSEN_ISBN_COL, bron)
                st.session_state["nl_output"] = df

                ok = sum(1 for r in rows if r.status in (STATUS_OK, STATUS_OK_CACHE))
                melding = (f"Klaar: {ok} van {len(rows)} rijen met Nielsen-data "
                           f"({resultaat.cache_hits} uit cache, {resultaat.live_fetches} live).")
                if resultaat.quota_hit:
                    st.warning(melding + " Dagquotum bereikt — de rest kan morgen opnieuw.")
                else:
                    st.success(melding)

    if "nl_output" in st.session_state:
        _resultaat_blok(st.session_state["nl_output"], "nielsen_verrijkt", "nl")


def view_cb() -> None:
    _brand_header("CB opzoeken")
    _terug_knop()

    col_upload, col_info = st.columns([1.15, 1], gap="large")
    with col_upload:
        cb_file = st.file_uploader("Excel met ISBN's", type=["xlsx", "xls"], key="cb_upload")
    rows = kolom = None
    if cb_file is not None:
        try:
            rows, kolom = parse_upload(cb_file)
        except UploadError as exc:
            with col_info:
                st.error(str(exc))

    if rows is not None:
        uniek = unique_valid_isbns(rows)
        geldig = [r for r in rows if r.isbn]
        with col_info:
            _metric_tegels([
                (f"{len(rows)}", "rijen", "m-paars"),
                (f"{len(geldig)}", "geldige ISBN's", "m-groen"),
                (f"{len(uniek)}", "unieke ISBN's", "m-oranje"),
            ])
            if len(geldig) < len(rows):
                st.caption(f"{len(rows) - len(geldig)} rij(en) zonder geldig ISBN — blokkeren niets. "
                           f"Kolom: `{kolom}`")
            with st.container(key="cb_actieblok"):
                st.markdown('<div class="pim-actie">', unsafe_allow_html=True)
                start = st.button("🚀  Start CB-opzoeking", key="cb_start",
                                  disabled=not uniek, use_container_width=True)
                st.markdown('</div>', unsafe_allow_html=True)

        if start:
            try:
                cfg = get_algolia_config()
            except MissingSecretsError as exc:
                st.error(str(exc))
            else:
                voortgang = st.progress(0.0, text="CB-opzoeking gestart...")
                try:
                    records = cb_service.fetch_cb_records(
                        uniek, cfg,
                        progress_cb=lambda b, t: voortgang.progress(
                            min(b / t, 1.0), text=f"CB: batch {b}/{t}"))
                except (cb_service.CBAuthError, cb_service.CBServiceError) as exc:
                    st.error(str(exc))
                    records = None

                if records is not None:
                    gevonden = [i for i in uniek if i in records]
                    voortgang.progress(1.0, text="Klaar")

                    data_by_isbn = {isbn: cb_service.build_cb_row(isbn, records[isbn])
                                    for isbn in gevonden}
                    bron = {}
                    for row in rows:
                        if not row.isbn:
                            continue
                        if row.isbn in records:
                            row.status = STATUS_OK
                            bron[row.isbn] = "CB"
                        else:
                            row.status = STATUS_NOT_FOUND
                            row.opmerking = "ISBN niet bekend bij CB"

                    df = build_output_df(rows, data_by_isbn, templates.CB_COLUMNS,
                                         templates.CB_ISBN_COL, bron)
                    st.session_state["cb_output"] = df
                    st.success(f"Klaar: {len(gevonden)} van {len(uniek)} unieke ISBN's gevonden bij CB.")

    if "cb_output" in st.session_state:
        _resultaat_blok(st.session_state["cb_output"], "cb_verrijkt", "cb")


def _zoek_uitvoeren(term: str, cfg, maximum: int) -> None:
    """Voer de zoekopdracht uit en zet het resultaat in de sessie.

    Een geldig ISBN-13 gaat via de exacte objectID-lookup (preciezer en
    sneller); al het andere via de Algolia full-text zoekopdracht.
    """
    isbn = looks_like_isbn13(term)
    voortgang = st.progress(0.0, text="Zoeken bij CB...")
    try:
        if isbn:
            gevonden = cb_service.fetch_cb_records([isbn], cfg)
            records = list(gevonden.values())
            totaal = len(records)
        else:
            records, totaal = cb_service.search_cb_records(
                term, cfg, max_results=maximum,
                progress_cb=lambda p, t: voortgang.progress(
                    min(p / t, 1.0), text=f"CB: pagina {p}/{t}"),
            )
    except (cb_service.CBAuthError, cb_service.CBServiceError) as exc:
        voortgang.empty()
        st.error(str(exc))
        return
    voortgang.empty()

    paren = []
    for record in records:
        oid = str(record.get("objectID") or record.get("Isbn") or "").strip()
        if oid:
            paren.append((oid, record))

    if not paren:
        for sleutel in ("zk_output", "zk_totaal", "zk_term_gebruikt"):
            st.session_state.pop(sleutel, None)
        st.warning(
            f"Geen resultaten voor “{term}”. Probeer een kortere of andere "
            "zoekterm — bijvoorbeeld alleen de achternaam van de auteur."
        )
        return

    isbns = [oid for oid, _ in paren]
    data_by_isbn = {oid: cb_service.build_cb_row(oid, record) for oid, record in paren}
    df = build_output_df(rows_from_isbns(isbns), data_by_isbn,
                         templates.CB_COLUMNS, templates.CB_ISBN_COL,
                         {oid: "CB" for oid in isbns})

    st.session_state["zk_output"] = df
    st.session_state["zk_totaal"] = totaal
    st.session_state["zk_term_gebruikt"] = term


def _zoek_resultaten_tonen() -> None:
    df = st.session_state["zk_output"]
    totaal = int(st.session_state.get("zk_totaal", len(df)))
    getoond = len(df)
    codes = df["BeschikbaarheidsCode"].astype(str).str.strip()
    leverbaar = int((codes == "1").sum())

    _metric_tegels([
        (f"{totaal}", "treffers bij CB", "m-paars"),
        (f"{getoond}", "opgehaald", "m-blauw"),
        (f"{leverbaar}", "direct leverbaar", "m-oranje"),
    ])
    if totaal > getoond:
        st.caption(
            f"CB heeft {totaal} treffers; de {getoond} meest relevante zijn opgehaald. "
            "Verhoog 'max. resultaten' of maak de zoekterm specifieker."
        )

    preview = df[["Isbn", "Hoofdtitel", "Auteur", "Uitgever",
                  "Verschijningsjaar", "Prijs"]].copy()
    preview.insert(0, "Cover", df["ImageUrl_nieuw"])
    preview["Leverbaarheid"] = codes.map(cb_service.leverbaarheid_label)

    st.dataframe(
        preview, use_container_width=True, hide_index=True, height=440,
        column_config={
            "Cover": st.column_config.ImageColumn("Cover", width="small"),
            "Isbn": st.column_config.TextColumn("ISBN", width="medium"),
            "Hoofdtitel": st.column_config.TextColumn("Titel", width="large"),
            "Verschijningsjaar": st.column_config.TextColumn("Jaar", width="small"),
        },
    )
    if codes.isin(["7", "8", "9", "10"]).any():
        st.caption("\\* Leverbaarheidscodes 7 t/m 10 zijn empirisch afgeleid en "
                   "nog niet bevestigd door CB-support.")

    _resultaat_blok(df, "cb_zoekresultaat", "zk")


def view_zoeken() -> None:
    _brand_header("Vrij zoeken")
    _terug_knop()

    with st.container(key="zoekblok"):
        st.markdown('<div class="pim-zoekblok">', unsafe_allow_html=True)
        with st.form("zk_form"):
            col_term, col_max = st.columns([3.4, 1], gap="medium")
            with col_term:
                term = st.text_input(
                    "Zoekterm", key="zk_term", label_visibility="collapsed",
                    placeholder="Auteur, titel of ISBN — bijv. Hueber, Menschen A1, 9783194919013",
                )
            with col_max:
                maximum = st.selectbox(
                    "Max. resultaten", [25, 50, 100, 250, 500, 1000], index=2,
                    key="zk_max", label_visibility="collapsed",
                    format_func=lambda n: f"max. {n}",
                )
            zoeken = st.form_submit_button("🔎  Zoeken", use_container_width=True)
        st.markdown(
            '<div class="pim-zoek-hint">Eén veld voor alles: een auteursnaam, '
            '(een deel van) een titel, of een ISBN-13. Enter zoekt ook.</div>',
            unsafe_allow_html=True,
        )
        st.markdown('</div>', unsafe_allow_html=True)

    if zoeken:
        if not (term or "").strip():
            st.warning("Vul eerst een zoekterm in.")
        else:
            try:
                cfg = get_algolia_config()
            except MissingSecretsError as exc:
                st.error(str(exc))
            else:
                _zoek_uitvoeren(term.strip(), cfg, int(maximum))

    if "zk_output" in st.session_state:
        _zoek_resultaten_tonen()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

_require_password()
_inject_css()

if "view" not in st.session_state:
    st.session_state.view = "home"

if st.session_state.view == "nielsen":
    view_nielsen()
elif st.session_state.view == "cb":
    view_cb()
elif st.session_state.view == "zoeken":
    view_zoeken()
else:
    view_home()
