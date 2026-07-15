"""
fix_druk_outliers_v2.py — Tweede iteratie fixes bovenop _v3.xlsx.

Gebruikt de raw KB cache uit v1-fix, dus geen nieuwe API-calls voor KB.
Aanvullingen:
  - Regex accepteert "Ne herziene/geactualiseerde/verbeterde druk"
  - Engelse "first/second/... edition" mapping
  - Compound ordinalen 100+ (via sortkey fallback als display niet parseert)
  - Wist suspect KB-annotation-based waarden als nieuwe parsing niks vindt
  - Managementboek retry voor gewiste ISBNs
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

import pandas as pd
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INPUT_XLSX = Path(r"C:\Users\jelle\Downloads\CB data gewenst 1726_FILLED_v3.xlsx")
OUTPUT_XLSX = Path(r"C:\Users\jelle\Downloads\CB data gewenst 1726_FILLED_v4.xlsx")
KB_CACHE_PATH = PROJECT_ROOT / "workspace" / "druk_raw_cache.json"
MB_CACHE_PATH = PROJECT_ROOT / "workspace" / "druk_mb_cache.json"

USER_AGENT = "Intertaal-PIM/1.0 (contact: jelle@acda-rpa.nl)"

# ---------------------------------------------------------------------------
# Ordinalen
# ---------------------------------------------------------------------------

DUTCH_ORDINALS = {}
_base_ord = {
    1: "eerste", 2: "tweede", 3: "derde", 4: "vierde", 5: "vijfde",
    6: "zesde", 7: "zevende", 8: "achtste", 9: "negende", 10: "tiende",
    11: "elfde", 12: "twaalfde", 13: "dertiende", 14: "veertiende", 15: "vijftiende",
    16: "zestiende", 17: "zeventiende", 18: "achttiende", 19: "negentiende",
    20: "twintigste",
    30: "dertigste", 40: "veertigste", 50: "vijftigste", 60: "zestigste",
    70: "zeventigste", 80: "tachtigste", 90: "negentigste", 100: "honderdste",
}
for _n, _w in _base_ord.items():
    DUTCH_ORDINALS[_w] = _n
_units = {1: "een", 2: "twee", 3: "drie", 4: "vier", 5: "vijf",
          6: "zes", 7: "zeven", 8: "acht", 9: "negen"}
_tens_words = {20: "twintig", 30: "dertig", 40: "veertig", 50: "vijftig",
               60: "zestig", 70: "zeventig", 80: "tachtig", 90: "negentig"}
for _tv, _tw in _tens_words.items():
    for _uv, _uw in _units.items():
        DUTCH_ORDINALS[f"{_uw}en{_tw}ste"] = _tv + _uv

# Honderd-tal compound ordinalen (voor 100-199)
_honderd_base = "honderdenTste"
for _uv, _uw in _units.items():
    DUTCH_ORDINALS[f"honderden{_uw}de"] = 100 + _uv  # honderdeneerste, honderdentweede
# Uitzondering: eerste heeft geen -de vorm
DUTCH_ORDINALS["honderdeneerste"] = 101
DUTCH_ORDINALS["honderdentweede"] = 102
DUTCH_ORDINALS["honderdenderde"] = 103
DUTCH_ORDINALS["honderdenvierde"] = 104
DUTCH_ORDINALS["honderdenvijfde"] = 105
DUTCH_ORDINALS["honderdenzesde"] = 106
DUTCH_ORDINALS["honderdenzevende"] = 107
DUTCH_ORDINALS["honderdenachtste"] = 108
DUTCH_ORDINALS["honderdennegende"] = 109
DUTCH_ORDINALS["honderdentiende"] = 110

# Engelse ordinalen
ENGLISH_ORDINALS = {
    "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5,
    "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10,
    "eleventh": 11, "twelfth": 12, "thirteenth": 13, "fourteenth": 14,
    "fifteenth": 15, "sixteenth": 16, "seventeenth": 17, "eighteenth": 18,
    "nineteenth": 19, "twentieth": 20,
}


# ---------------------------------------------------------------------------
# Verbeterde KB parser
# ---------------------------------------------------------------------------

_ADJ_BETWEEN = r"(?:herziene|geactualiseerde|verbeterde|volledig\s+herziene|nieuwe|nederlandse|vertaalde|revised|updated|corrected|new|first|second)\s+"


def parse_kb_mods_edition_v2(edition_val: str) -> str | None:
    """Parse mods:edition value → integer druk-string of None."""
    if not edition_val:
        return None
    sortkey = ""
    if "#" in edition_val:
        sortkey, display = edition_val.split("#", 1)
    else:
        display = edition_val
    d = display.lower().strip()
    sortkey = sortkey.strip().lstrip("0") or "0"

    # 1) "Ne (herziene/etc.) druk" of "Ne (herziene) editie"
    m = re.search(
        rf"\b(\d+)\s*(?:e|de|ste|nd|rd|th)?\s+(?:{_ADJ_BETWEEN})?(?:druk|dr\.?|editie|edition|ed\.?)\b",
        d)
    if m and int(m.group(1)) < 500:
        return m.group(1)

    # 2) Nederlandse ordinaal + optioneel adjectief + druk/editie
    for word, num in sorted(DUTCH_ORDINALS.items(), key=lambda x: -len(x[0])):
        if re.search(rf"\b{word}\s+(?:{_ADJ_BETWEEN})?(?:druk|editie|dr\.|ed\.)", d):
            return str(num)

    # 3) Engelse ordinaal (first edition etc.)
    for word, num in sorted(ENGLISH_ORDINALS.items(), key=lambda x: -len(x[0])):
        if re.search(rf"\b{word}\s+(?:{_ADJ_BETWEEN})?(?:edition|ed\.|impression)", d):
            return str(num)

    # 4) Los ordinaal woord in display
    for word, num in sorted(DUTCH_ORDINALS.items(), key=lambda x: -len(x[0])):
        if re.search(rf"\b{word}\b", d):
            return str(num)

    # 5) Sortkey fallback voor 100-199 range (compound ordinalen die we niet catchen)
    if sortkey.isdigit() and 100 <= int(sortkey) < 200:
        # bijv "102#Honderdentweede druk" → 100-199 → laatste 2 cijfers als tussen 0-99
        # Maar sortkey 102 heeft druk 1, oplage 02. Nee wacht — voor 102 is "Honderdentweede druk" = 102e druk.
        # Voor 501 is display "Vijfde druk, eerste oplage" = 5e druk.
        # De regel is: als display GEEN parse-able druk heeft maar sortkey WEL 3-digits patroon <druk><oplage>,
        # dan is sortkey ambigu.
        # Voor 100-199: aannemen dat display de compound ordinal is (honderdN) en sortkey is de daadwerkelijke druk
        return sortkey
    if sortkey.isdigit() and 200 <= int(sortkey) < 500:
        # Idem — 247, 387, 494 zijn te specifiek voor druk+oplage patroon. Wsl legit hoge drukken?
        # Nee, verdacht. Return None om KB te laten falen; annotation of managementboek pakt het op.
        return None
    if sortkey.isdigit() and int(sortkey) < 100 and int(sortkey) > 0:
        return sortkey

    return None


def parse_kb_response_v2(xml_text: str) -> tuple[str | None, str]:
    if not xml_text:
        return None, ""

    m = re.search(r"<mods:edition>([^<]+)</mods:edition>", xml_text)
    if m:
        druk = parse_kb_mods_edition_v2(m.group(1))
        if druk:
            return druk, "kb.nl:mods"

    # Strict annotation fallback
    for annot in re.findall(r"<dcx:annotation[^>]*>([^<]+)</dcx:annotation>", xml_text):
        low = annot.lower()
        # Skip "1e druk deze uitgave"
        if "druk" in low and ("deze uitgave" in low or "deze uitg." in low
                              or "oorspr" in low or "1e druk deze" in low):
            continue
        # Skip ISBNs, ISSNs, signaturen
        if "isbn" in low or "issn" in low or "signatuur" in low or "signatuur" in low:
            continue

        mm = re.search(
            rf"\b(\d+)e\s+(?:{_ADJ_BETWEEN})?druk\b", low)
        if mm and int(mm.group(1)) < 500:
            return mm.group(1), "kb.nl:annotation"

        for word, num in sorted(DUTCH_ORDINALS.items(), key=lambda x: -len(x[0])):
            if re.search(rf"\b{word}\s+(?:{_ADJ_BETWEEN})?druk\b", low):
                return str(num), "kb.nl:annotation"

    return None, ""


# ---------------------------------------------------------------------------
# Managementboek strict
# ---------------------------------------------------------------------------

def fetch_mb_druk_strict(isbn: str, session: requests.Session) -> str | None:
    url = f"https://www.managementboek.nl/boek/{isbn}"
    try:
        resp = session.get(url, timeout=15, headers={"User-Agent": USER_AGENT}, allow_redirects=True)
        if resp.status_code != 200:
            return None
        html = resp.text

        # Zoek in specs area
        # Pak <b>Druk:</b>, <td>Druk:</td>, <li>Druk: N</li>
        for pat in [
            r"<b>Druk:?</b>\s*(\d+)",
            r"<td[^>]*>Druk:?</td>\s*<td[^>]*>\s*(\d+)e?",
            r"Druk\s*:\s*(\d+)e?\s+druk",
            r"<i>\s*(\d+)e\s+druk\s*</i>",
        ]:
            m = re.search(pat, html, re.IGNORECASE)
            if m and int(m.group(1)) < 500:
                return m.group(1)
        return None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("=== Fix Druk outliers v2 ===")
    df = pd.read_excel(INPUT_XLSX)
    df["_clean_isbn"] = df["ISBN"].astype(str).str.strip().apply(
        lambda x: re.sub(r"[A-Za-z]+$", "", x)
    )
    df["Druk"] = df["Druk"].astype(object)
    df["_druk_source"] = df["_druk_source"].astype(object)

    def cur_druk(idx):
        v = df.at[idx, "Druk"]
        if pd.isna(v): return ""
        return str(v).strip().replace(".0", "")

    def is_suspect(v: str) -> bool:
        if not v or not v.isdigit(): return False
        return int(v) > 15

    def has_druk(x):
        if pd.isna(x): return False
        s = str(x).strip()
        return bool(s and s not in ("nan", "None", ""))

    # Load KB raw cache (uit vorige run)
    with open(KB_CACHE_PATH, encoding="utf-8") as f:
        kb_cache = json.load(f)
    print(f"KB raw cache: {len(kb_cache)} entries")

    # Load MB cache
    mb_cache = {}
    if MB_CACHE_PATH.exists():
        with open(MB_CACHE_PATH, encoding="utf-8") as f:
            mb_cache = json.load(f)

    session = requests.Session()

    # ------------------ Stap 1: Herparse ALLE rows met v2 parser ------------------
    print("\n[Stap 1] Herparse alle KB responses met v2 parser...")

    candidates_mask = df["Publisher"].apply(has_druk)
    candidates = list(df.index[candidates_mask])

    fixed = 0
    cleared = 0
    changed = []

    for idx in candidates:
        isbn = df.at[idx, "_clean_isbn"]
        xml = kb_cache.get(isbn, "")
        old_druk = cur_druk(idx)
        old_src = str(df.at[idx, "_druk_source"] or "")

        # Only try KB fix if old source is KB
        if "kb.nl" not in old_src and old_src not in ("", None):
            continue

        new_druk, new_src = parse_kb_response_v2(xml)

        if new_druk:
            if new_druk != old_druk:
                df.at[idx, "Druk"] = new_druk
                df.at[idx, "_druk_source"] = new_src
                fixed += 1
                changed.append((isbn, old_druk, new_druk, "kb-v2-fix"))
        elif is_suspect(old_druk):
            # Oude waarde was suspect, nieuwe parsing vindt niks → wis
            df.at[idx, "Druk"] = None
            df.at[idx, "_druk_source"] = ""
            cleared += 1
            changed.append((isbn, old_druk, "(cleared)", "kb-cleared"))

    print(f"  KB fixed: {fixed}")
    print(f"  KB cleared (was suspect, geen alternatief): {cleared}")

    # ------------------ Stap 2: Managementboek retry voor gewiste ISBNs ------------------
    cleared_isbns = [df.at[idx, "_clean_isbn"] for idx in candidates
                     if not has_druk(df.at[idx, "Druk"])
                     and df.at[idx, "_druk_source"] in ("", None)]

    print(f"\n[Stap 2] Managementboek retry voor {len(cleared_isbns)} gewiste ISBNs...")

    mb_fixed = 0
    for i, isbn in enumerate(cleared_isbns):
        if isbn in mb_cache:
            druk = mb_cache[isbn]
        else:
            druk = fetch_mb_druk_strict(isbn, session)
            mb_cache[isbn] = druk if druk else ""
            time.sleep(1.0)
            if (i + 1) % 25 == 0:
                with open(MB_CACHE_PATH, "w", encoding="utf-8") as f:
                    json.dump(mb_cache, f, ensure_ascii=False)

        if druk and not is_suspect(druk):
            # Find idx for this isbn
            for idx in candidates:
                if df.at[idx, "_clean_isbn"] == isbn:
                    df.at[idx, "Druk"] = druk
                    df.at[idx, "_druk_source"] = "managementboek.nl:retry"
                    mb_fixed += 1
                    changed.append((isbn, "(empty)", druk, "mb-retry"))
                    break

        if (i + 1) % 50 == 0:
            print(f"  Progress: {i+1}/{len(cleared_isbns)} (mb_fixed={mb_fixed})", flush=True)

    with open(MB_CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(mb_cache, f, ensure_ascii=False)
    print(f"  MB fixed: {mb_fixed}")

    # ------------------ Stap 3: Managementboek retry voor ANDERE mb outliers ------------------
    mb_outliers = [idx for idx in candidates
                   if is_suspect(cur_druk(idx))
                   and "managementboek" in str(df.at[idx, "_druk_source"] or "")]
    print(f"\n[Stap 3] Managementboek strict retry voor {len(mb_outliers)} mb outliers...")
    mb_fixed2 = 0
    for i, idx in enumerate(mb_outliers):
        isbn = df.at[idx, "_clean_isbn"]
        if isbn in mb_cache:
            druk = mb_cache[isbn]
        else:
            druk = fetch_mb_druk_strict(isbn, session)
            mb_cache[isbn] = druk if druk else ""
            time.sleep(1.0)

        old_druk = cur_druk(idx)
        if druk and not is_suspect(druk):
            df.at[idx, "Druk"] = druk
            df.at[idx, "_druk_source"] = "managementboek.nl:retry"
            mb_fixed2 += 1
            changed.append((isbn, old_druk, druk, "mb-outlier-fix"))
        elif not druk:
            # Wis, geen betrouwbare bron
            df.at[idx, "Druk"] = None
            df.at[idx, "_druk_source"] = ""
            changed.append((isbn, old_druk, "(cleared)", "mb-cleared"))

    with open(MB_CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(mb_cache, f, ensure_ascii=False)
    print(f"  MB outliers fixed: {mb_fixed2}")

    # ------------------ Report ------------------
    total_filled = df["Druk"].apply(has_druk).sum()
    still_suspect = df[df["Druk"].apply(lambda x: has_druk(x) and str(x).replace(".0","").strip().isdigit()
                                           and int(str(x).replace(".0","").strip()) > 15)]

    print(f"\n=== EINDRAPPORT v4 ===")
    print(f"Totaal rijen: {len(df)}")
    print(f"Druk gevuld:  {total_filled} ({total_filled/len(df)*100:.1f}%)")
    print(f"Nog verdacht (>15): {len(still_suspect)}")
    print(f"Totaal wijzigingen deze run: {len(changed)}")

    print("\n=== Steekproef 30 wijzigingen ===")
    for isbn, old, new, reason in changed[:30]:
        print(f"  {isbn}: {old} -> {new} ({reason})")

    df_out = df.drop(columns=["_clean_isbn"])
    df_out.to_excel(OUTPUT_XLSX, index=False, engine="openpyxl")
    print(f"\nOpgeslagen: {OUTPUT_XLSX}")


if __name__ == "__main__":
    main()
