#!/usr/bin/env python3
"""Synchronisation du catalogue composants depuis l'API Digi-Key (OAuth2).

Structure réelle :
  1. lecture de la clé d'API (env DIGIKEY_CLIENT_ID / DIGIKEY_CLIENT_SECRET) ;
  2. boucle sur une liste de requêtes de composants courants (MCU, capteurs,
     régulateurs, connecteurs, passifs) ;
  3. écriture de chaque résultat en JSON dans
     data/component_library/digikey_sync/<slug>.json (schéma stable exploitable
     par services.parser.component_lib_matcher).

Mode mock-friendly : sans clé d'API, le script génère un catalogue
déterministe (mêmes fichiers, champ "mock": true) pour développer/tester
la chaîne sans compte Digi-Key.

Usage :
    python scripts/data/sync_digikey.py                  # mock si pas de clé
    DIGIKEY_CLIENT_ID=... DIGIKEY_CLIENT_SECRET=... python scripts/data/sync_digikey.py
    python scripts/data/sync_digikey.py --query "esp32" --limit 5
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "backend"))

OUT_DIR = REPO_ROOT / "data" / "component_library" / "digikey_sync"

# Requêtes par défaut : familles courantes d'un design PCB type IoT
DEFAULT_QUERIES: list[dict] = [
    {"slug": "mcu-esp32", "keywords": "ESP32-WROOM-32E", "category": "mcu",
     "fields": {"package": "QFN-48", "flash_kb": 4096}},
    {"slug": "mcu-stm32f103", "keywords": "STM32F103C8T6", "category": "mcu",
     "fields": {"package": "LQFP-48", "flash_kb": 64}},
    {"slug": "sensor-bme680", "keywords": "BME680", "category": "sensor",
     "fields": {"interface": "I2C"}},
    {"slug": "regulator-ams1117", "keywords": "AMS1117-3.3", "category": "regulator",
     "fields": {"vout_v": 3.3, "dropout": "ldo"}},
    {"slug": "usb-c-connector", "keywords": "USB-C receptacle 16 pin", "category": "connector",
     "fields": {"pins": 16}},
    {"slug": "lipo-charger-tp4056", "keywords": "TP4056", "category": "power",
     "fields": {"icharge_a": 1.0}},
]

DIGIKEY_TOKEN_URL = "https://api.digikey.com/v1/oauth2/token"
DIGIKEY_SEARCH_URL = "https://api.digikey.com/products/v4/search/keyword"


def _slug(text: str) -> str:
    """Normalise une chaîne en identifiant de fichier sûr."""
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "result"


def _mock_result(query: dict, limit: int) -> dict:
    """Catalogue déterministe (mock) : structure identique à l'API réelle."""
    kw = query["keywords"]
    parts = []
    for i in range(min(3, max(1, limit // 3))):
        parts.append({
            "mpn": f"{kw.split()[0].upper()}-{1000 + i * 7}",
            "manufacturer": "GenericCorp" if i % 2 else "MegaSemi",
            "description": f"{kw} (mock entry #{i + 1})",
            "package": query.get("fields", {}).get("package", "0603"),
            "stock": 2500 + i * 311,
            "unit_price_usd": round(0.12 + i * 0.37, 3),
        })
    return {"query": kw, "category": query.get("category", "passive"), "mock": True,
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "parts": parts}


def _get_access_token(client_id: str, client_secret: str) -> str:
    """Récupère un token OAuth2 client_credentials (Digi-Key POST /token)."""
    data = urllib.parse.urlencode({
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
    }).encode()
    req = urllib.request.Request(DIGIKEY_TOKEN_URL, data=data, method="POST")
    with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 (API officielle)
        payload = json.load(resp)
    if "access_token" not in payload:
        raise RuntimeError(f"token Digi-Key invalide: {payload.get('error', payload)}")
    return str(payload["access_token"])


def _search_real(token: str, keywords: str, limit: int) -> dict:
    """Recherche réelle POST /search/keyword (Products v4)."""
    body = json.dumps({"Keywords": keywords, "Limit": limit}).encode()
    req = urllib.request.Request(
        DIGIKEY_SEARCH_URL, data=body, method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "X-DIGIKEY-Client-Id": os.environ["DIGIKEY_CLIENT_ID"],
            "Content-Type": "application/json",
        })
    with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
        payload = json.load(resp)
    parts = [
        {
            "mpn": p.get("ProductNumber", ""),
            "manufacturer": (p.get("Manufacturer") or {}).get("Name", ""),
            "description": (p.get("Description") or {}).get("ProductDescription", ""),
            "package": (p.get("Parameters") or [{}])[0].get("ValueText", "") if p.get("Parameters") else "",
            "stock": int(p.get("QuantityAvailable") or 0),
            "unit_price_usd": float((p.get("UnitPricing") or [{}])[0].get("UnitPrice", 0.0)),
        }
        for p in payload.get("Products", [])[:limit]
    ]
    return {"query": keywords, "category": "", "mock": False,
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "parts": parts}


def main() -> int:
    """Point d'entrée CLI : boucle les requêtes, écrit un JSON par requête."""
    parser = argparse.ArgumentParser(description="Sync catalogue Digi-Key → JSON")
    parser.add_argument("--query", default="", help="requête unique (hors liste par défaut)")
    parser.add_argument("--limit", type=int, default=9, help="résultats par requête")
    parser.add_argument("--out", default=str(OUT_DIR), help="dossier de sortie")
    args = parser.parse_args()

    client_id = os.environ.get("DIGIKEY_CLIENT_ID", "")
    client_secret = os.environ.get("DIGIKEY_CLIENT_SECRET", "")
    token = ""
    if client_id and client_secret:
        print("[digikey] clés détectées — mode RÉEL (OAuth2 client_credentials)")
        token = _get_access_token(client_id, client_secret)
    else:
        print("[digikey] pas de DIGIKEY_CLIENT_ID/SECRET — mode MOCK déterministe")

    queries = list(DEFAULT_QUERIES)
    if args.query:
        queries = [{"slug": _slug(args.query), "keywords": args.query, "category": "custom"}]

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    written = 0
    for q in queries:
        if token:
            try:
                result = _search_real(token, q["keywords"], args.limit)
            except Exception as exc:  # repli mock : le sync ne casse jamais la CI
                print(f"  ! {q['slug']}: appel réel échoué ({exc}) → mock")
                result = _mock_result(q, args.limit)
        else:
            result = _mock_result(q, args.limit)

        path = out_dir / f"{q['slug']}.json"
        path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        written += 1
        print(f"  ✓ {path.relative_to(REPO_ROOT)} ({len(result['parts'])} parts)")

    print(f"[digikey] {written} fichiers écrits dans {out_dir.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
