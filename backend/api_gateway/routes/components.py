"""Route composants — recherche dans la librairie (ComponentLibMatcher)."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from shared.utilities import get_logger

from orchestrator.common import call_probe, get_field, try_import

log = get_logger("api.components")

router = APIRouter(prefix="/api/v1/components", tags=["components"])

# Mini-catalogue de repli (dev / services.parser absent)
_FALLBACK_CATALOG: list[dict[str, Any]] = [
    {"mpn": "ESP32-WROOM-32E", "value": "ESP32", "footprint": "ESP32-WROOM-32E",
     "description": "MCU WiFi+BT dual-core 240 MHz", "manufacturer": "Espressif", "price_usd": 3.1,
     "pads": 38},
    {"mpn": "BME680", "value": "BME680", "footprint": "BME680",
     "description": "Capteur température/humidité/pression/gaz I²C", "manufacturer": "Bosch",
     "price_usd": 4.2, "pads": 8},
    {"mpn": "AMS1117-3.3", "value": "LDO 3.3V", "footprint": "SOT-223",
     "description": "Régulateur linéaire 1A 3.3V", "manufacturer": "AMS", "price_usd": 0.15,
     "pads": 4},
    {"mpn": "RC0402FR-0710KL", "value": "10k", "footprint": "0402",
     "description": "Résistance 10 kΩ 1%", "manufacturer": "Yageo", "price_usd": 0.002, "pads": 2},
    {"mpn": "CL05B104KO5NNNC", "value": "100n", "footprint": "0402",
     "description": "Condensateur céramique 100 nF 16V X7R", "manufacturer": "Samsung",
     "price_usd": 0.003, "pads": 2},
    {"mpn": "USB4085-GF-A", "value": "USB-C", "footprint": "USB-C-16P",
     "description": "Connecteur USB Type-C receptacle", "manufacturer": "GCT", "price_usd": 0.8,
     "pads": 16},
]


def _normalize(entry: Any) -> dict[str, Any]:
    if isinstance(entry, dict):
        return {
            "mpn": str(entry.get("mpn") or entry.get("part_number") or ""),
            "value": str(entry.get("value") or ""),
            "footprint": str(entry.get("footprint") or entry.get("package") or ""),
            "description": str(entry.get("description") or ""),
            "manufacturer": str(entry.get("manufacturer") or entry.get("mfr") or ""),
            "price_usd": float(entry.get("price_usd") or entry.get("price") or 0.0),
        }
    return {
        "mpn": str(get_field(entry, "mpn", "part_number", default="") or ""),
        "value": str(get_field(entry, "value", default="") or ""),
        "footprint": str(get_field(entry, "footprint", "package", default="") or ""),
        "description": str(get_field(entry, "description", default="") or ""),
        "manufacturer": str(get_field(entry, "manufacturer", default="") or ""),
        "price_usd": float(get_field(entry, "price_usd", "price", default=0.0) or 0.0),
    }


def _matcher() -> Any:
    cls = try_import("services.parser", ["ComponentLibMatcher"]).get("ComponentLibMatcher")
    if cls is None:
        return None
    try:
        return cls()
    except TypeError:
        return cls()


def _search(query: str) -> list[dict[str, Any]]:
    matcher = _matcher()
    if matcher is None:
        lowered = query.lower()
        return [entry for entry in _FALLBACK_CATALOG
                if lowered in json_text(entry)]
    raw = (call_probe(matcher, "search", (query,))
           or call_probe(matcher, "match", (query,))
           or call_probe(matcher, "find", (query,)))
    if raw is None:
        return []
    if isinstance(raw, dict):
        raw = [raw]
    results = [_normalize(item) for item in raw]
    return [r for r in results if r.get("mpn")]


def json_text(entry: dict[str, Any]) -> str:
    import json

    return json.dumps(entry, default=str).lower()


@router.get("/search")
async def search_components(request: Request, q: str = Query(..., min_length=1),
                            limit: int = 20) -> dict[str, Any]:
    """Recherche de composants par mots-clés / MPN / description."""
    results = _search(q)[: max(1, min(limit, 100))]
    return {"query": q, "count": len(results), "results": results}


@router.get("/{mpn}")
async def get_component(mpn: str, request: Request) -> dict[str, Any]:
    """Fiche d'un composant par MPN exact (ou meilleur match)."""
    results = _search(mpn)
    for entry in results:
        if entry.get("mpn", "").upper() == mpn.upper():
            return entry
    if results:
        return results[0]
    raise HTTPException(status_code=404, detail=f"composant introuvable: {mpn}")
