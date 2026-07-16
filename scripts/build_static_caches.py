# -*- coding: utf-8 -*-
"""build_static_caches.py — extraheert de historische lookup-data uit de
lokale caches (op de PIM-machine) en schrijft compacte JSON-bestanden in
data/ die met de repo mee-gedeployd worden naar Streamlit Cloud.

Draai dit script periodiek op de PIM-laptop (waar de complete caches
staan) om de statische lookup-data te verversen:

    python scripts/build_static_caches.py \
        --workspace "C:/Users/jelle/.openclaw/workspace/intertaal-pim/intertaal-pim/workspace"

Output in data/:
  druk_lookup.json      {isbn: druk-string}         (~1-2 MB, ~25k ISBN's)
  image_urls.json       {isbn: url}                 (~2-3 MB, ~31k ISBN's)
  nielsen_lookup.json   {isbn: {kolom: waarde,...}} (~15 MB, ~4k ISBN's,
                                                     alle 141 template-velden)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.fix_druk_outliers_v2 import parse_kb_response_v2
from src.app_services import templates


def build_druk(workspace: Path, out: Path) -> None:
    kb_path = workspace / "druk_raw_cache.json"
    mb_path = workspace / "druk_mb_cache.json"
    out_data: dict[str, str] = {}

    if kb_path.exists():
        print(f"KB.nl cache: {kb_path}")
        with open(kb_path, encoding="utf-8") as f:
            kb = json.load(f)
        parsed = 0
        for isbn, xml in kb.items():
            if not xml:
                continue
            druk, _bron = parse_kb_response_v2(xml)
            if druk:
                out_data[isbn] = druk
                parsed += 1
        print(f"  KB: {parsed}/{len(kb)} met druk-info")

    if mb_path.exists():
        print(f"Managementboek cache: {mb_path}")
        with open(mb_path, encoding="utf-8") as f:
            mb = json.load(f)
        added = 0
        for isbn, druk in mb.items():
            if isbn not in out_data and druk:
                out_data[isbn] = str(druk)
                added += 1
        print(f"  MB: {added} extra")

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(out_data, ensure_ascii=False, separators=(",", ":")),
                   encoding="utf-8")
    print(f"-> {out} ({len(out_data)} ISBN's, {out.stat().st_size / 1024:.0f} kB)\n")


def build_images(workspace: Path, out: Path) -> None:
    src = workspace / "image_url_cache.json"
    if not src.exists():
        print(f"(geen {src}, image-cache overgeslagen)")
        return
    print(f"Image cache: {src}")
    with open(src, encoding="utf-8") as f:
        data = json.load(f)
    # Filter: alleen niet-lege URL's
    filtered = {isbn: url for isbn, url in data.items() if url}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(filtered, ensure_ascii=False, separators=(",", ":")),
                   encoding="utf-8")
    print(f"-> {out} ({len(filtered)} ISBN's, {out.stat().st_size / 1024:.0f} kB)\n")


def build_nielsen(workspace: Path, out: Path) -> None:
    src = workspace / "nielsen_raw_cache.json"
    if not src.exists():
        print(f"(geen {src}, Nielsen-cache overgeslagen)")
        return
    print(f"Nielsen raw cache: {src}")
    with open(src, encoding="utf-8") as f:
        cache = json.load(f)

    columns = templates.NIELSEN_DATA_COLUMNS  # 140 kolommen (excl. ISBN-inputkolom)
    out_data: dict[str, dict[str, str]] = {}
    for isbn, xml in cache.items():
        if not xml or "<record>" not in xml:
            continue
        m = re.search(r"<record>(.*?)</record>", xml, re.DOTALL)
        if not m:
            continue
        record = m.group(1)
        row: dict[str, str] = {}
        for col in columns:
            mm = re.search(rf"<{col}>([^<]*)</{col}>", record)
            if mm and mm.group(1).strip():
                row[col] = mm.group(1).strip()
        if row:
            out_data[isbn] = row

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(out_data, ensure_ascii=False, separators=(",", ":")),
                   encoding="utf-8")
    print(f"-> {out} ({len(out_data)} ISBN's, {out.stat().st_size / 1024:.0f} kB)\n")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace", required=True,
                    help="Pad naar de workspace-map van de PIM-installatie "
                         "(met druk_raw_cache.json, nielsen_raw_cache.json etc.)")
    args = ap.parse_args()

    workspace = Path(args.workspace)
    if not workspace.is_dir():
        ap.error(f"Workspace-map bestaat niet: {workspace}")

    data_dir = PROJECT_ROOT / "data"
    print(f"Output: {data_dir}\n")
    build_druk(workspace, data_dir / "druk_lookup.json")
    build_images(workspace, data_dir / "image_urls.json")
    build_nielsen(workspace, data_dir / "nielsen_lookup.json")
    print("Klaar. Commit de data/-map om de webapp bij te werken.")


if __name__ == "__main__":
    main()
