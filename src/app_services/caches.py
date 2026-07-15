# -*- coding: utf-8 -*-
"""
caches.py — JSON-caches met atomaire merge-on-write.

Multi-user veilig genoeg voor deze toepassing:
  - save_json_cache herlaadt eerst het bestand van schijf, merged de nieuwe
    entries erin en schrijft via tempfile + os.replace (atomair op POSIX en
    Windows/NTFS). Twee gelijktijdige schrijvers verliezen dus hooguit
    elkaars *gelijktijdige* nieuwe entries (worden later opnieuw opgehaald),
    maar het bestand raakt nooit corrupt en bestaande entries blijven staan.

Cache-map: env PIM_CACHE_DIR (Azure: /home/data/pim-cache, persistent),
anders <projectroot>/workspace. Koude start (geen bestand) is prima.
"""
from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CACHE_DIR = Path(os.getenv("PIM_CACHE_DIR", str(PROJECT_ROOT / "workspace")))

NIELSEN_CACHE = "nielsen_raw_cache.json"
KB_DRUK_CACHE = "druk_raw_cache.json"
MB_DRUK_CACHE = "druk_mb_cache.json"


def _cache_path(name: str) -> Path:
    return CACHE_DIR / name


def load_json_cache(name: str) -> dict:
    path = _cache_path(name)
    if not path.exists():
        return {}
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (ValueError, OSError):
        # Corrupt/onleesbaar bestand mag de app nooit blokkeren
        return {}


def _acquire_lock(lock_path: Path, timeout: float = 5.0) -> int | None:
    """Cross-process lock via exclusief aangemaakt lockbestand.

    Return file descriptor bij succes, None bij timeout (dan gaan we
    best-effort zonder lock verder — nooit blokkeren of crashen).
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            return os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            time.sleep(0.02)
        except OSError:
            return None
    return None


def _release_lock(fd: int | None, lock_path: Path) -> None:
    if fd is None:
        return
    try:
        os.close(fd)
        os.unlink(lock_path)
    except OSError:
        pass


def save_json_cache(name: str, updates: dict) -> None:
    """Merge `updates` in de bestaande cache en schrijf atomair terug.

    Multi-user veilig: een lockbestand serialiseert schrijvers (Windows
    en Linux/Azure); de write zelf is atomair via tempfile + os.replace.
    Best-effort: bij aanhoudende contention wordt de write overgeslagen —
    een gemiste cache-write is onschuldig (data wordt later opnieuw
    opgehaald), een crash in de gebruikersflow niet.
    """
    if not updates:
        return
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = _cache_path(name)
    lock_path = _cache_path(name + ".lock")

    lock_fd = _acquire_lock(lock_path)
    try:
        for attempt in range(8):
            merged = load_json_cache(name)
            merged.update(updates)

            fd, tmp_name = tempfile.mkstemp(dir=str(CACHE_DIR), suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    json.dump(merged, handle, ensure_ascii=False)
                os.replace(tmp_name, path)
                return
            except PermissionError:
                try:
                    os.unlink(tmp_name)
                except OSError:
                    pass
                time.sleep(0.05 * (attempt + 1))
            except BaseException:
                try:
                    os.unlink(tmp_name)
                except OSError:
                    pass
                raise
        # Na alle pogingen nog bezet: write overslaan (best-effort cache)
    finally:
        _release_lock(lock_fd, lock_path)
