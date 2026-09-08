#!/usr/bin/env python3
"""Synchronisation du catalogue composants depuis l'API Mouser (Search API).

Structure réelle (miroir de sync_digikey.py) :
  1. lecture de la clé (env MOUSER_API_KEY, Search API key) ;
  2. boucle sur les requêtes de composants courants ;
  3. écriture en JSON dans data/component_library/mouser_sync/<slug>.json.

Mode mock-friendly : sans clé, catalogue déterministe dans les mêmes fichiers.

Usage :
    python scripts/data/sync_mouser.py
    MOUSER_API_KEY=... python scripts/data/sync_mouser.py --query "bme680"
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "backend"))

OUT_DIR = REPO_ROOT / "data" / "component_library" / "mouser_sync"

# Partage la même grille de requêtes que Digi-Key (nomenclatures comparables)
sys.path.insert(0, str(Path(__file__).resolve().parent))
from sync_digikey import DEFAULT_QUERIES, _mock_result, _slug  # noqa: E402

MOUSER_SEARCH_URL = "https://api.mouser.com/api/v1/search/keyword"


def _search_real(api_key: str, keywords: str, limit: int) -> dict:
    """Recherche réelle Mouser POST /search/keyword (clé dans le body)."""
    body = json.dumps({
        "SearchByKeywordRequest": {
            "keyword": keywords,
            "records": min(limit, 50),
            "startingRecord": 0,
        }
    }).encode()
    req = urllib.request.Request(
        f"{MOUSER_SEARCH_URL}?apiKey={api_key}", data=body, method="POST",
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
        payload = json.load(resp)
    parts = []
    for p in payload.get("SearchResults", {}).get("Parts", [])[:limit]:
        try:
            price = float((p.get("PriceBreaks") or [{}])[0].get("Price", "0")
                          .replace("$", "").replace(",", "") or 0.0)
        except (TypeError, ValueError):
            price = 0.0
        parts.append({
            "mpn": p.get("ManufacturerPartNumber", ""),
            "manufacturer": p.get("Manufacturer", ""),
            "description": p.get("Description", ""),
            "package": p.get("Package", "") or "",
            "stock": int(p.get("Availability", "0").replace(",", "").split()[0]
                         if p.get("Availability") and p["Availability"].split() else 0),
            "unit_price_usd": price,
        })
    return {"query": keywords, "category": "", "mock": False,
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "parts": parts}


def main() -> int:
    """Point d'entrée CLI : boucle les requêtes, écrit un JSON par requête."""
    parser = argparse.ArgumentParser(description="Sync catalogue Mouser → JSON")
    parser.add_argument("--query", default="", help="requête unique (hors liste par défaut)")
    parser.add_argument("--limit", type=int, default=9, help="résultats par requête")
    parser.add_argument("--out", default=str(OUT_DIR), help="dossier de sortie")
    args = parser.parse_args()

    api_key = os.environ.get("MOUSER_API_KEY", "")
    if api_key:
        print("[mouser] MOUSER_API_KEY détectée — mode RÉEL (Search API v1)")
    else:
        print("[mouser] pas de MOUSER_API_KEY — mode MOCK déterministe")

    queries = list(DEFAULT_QUERIES)
    if args.query:
        queries = [{"slug": _slug(args.query), "keywords": args.query, "category": "custom"}]

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    written = 0
    for q in queries:
        if api_key:
            try:
                result = _search_real(api_key, q["keywords"], args.limit)
            except Exception as exc:
                print(f"  ! {q['slug']}: appel réel échoué ({exc}) → mock")
                result = _mock_result(q, args.limit)
        else:
            result = _mock_result(q, args.limit)

        path = out_dir / f"{q['slug']}.json"
        path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        written += 1
        print(f"  ✓ {path.relative_to(REPO_ROOT)} ({len(result['parts'])} parts)")

    print(f"[mouser] {written} fichiers écrits dans {out_dir.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
