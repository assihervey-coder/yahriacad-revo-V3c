"""Client JLCPCB — capacités, devis, upload gerbers, dispo composants (SMT).

Sans JLCPCB_API_KEY : devis estimé localement et bibliothèque de composants
vérifiée depuis data/component_library (fallback mock déterministe).
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from shared.utilities import get_logger, new_id, short_id
from shared.utilities.config import get_settings

from services.manufacturing_intelligence.factory_profiles import (
    FactoryProfile,
    get_profile,
)
from services.manufacturing_intelligence.pcbway import Quote, _estimate

log = get_logger(__name__)

_API_BASE = "https://cart.jlcpcb.com/api/v2"
_LIBRARY_DIR = Path("data/component_library")


class JLCPCBClient:
    """Client REST JLCPCB (API réelle si clé, estimation/mock sinon)."""

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or get_settings().jlcpcb_api_key or None
        self.factory = "jlcpcb"

    def get_capabilities(self) -> FactoryProfile:
        """Profil DFM JLCPCB (SMT économique, jusqu'à 20 couches)."""
        return get_profile("jlcpcb")

    # -- devis / gerbers ------------------------------------------------------
    def quote(self, params: dict[str, Any]) -> Quote:
        """Devis : API réelle si clé configurée, estimation locale sinon."""
        if not self.api_key:
            log.info("JLCPCB_API_KEY absente — devis estimé localement")
            return _estimate(params, self.get_capabilities().unit_price_factor, 15.0)
        try:
            import httpx  # lazy

            resp = httpx.post(
                f"{_API_BASE}/orders/quote",
                json=params,
                headers={"X-JLC-KEY": self.api_key},
                timeout=15.0,
            )
            resp.raise_for_status()
            data = resp.json()
            return Quote(
                base_usd=float(data.get("base_usd", 0.0)),
                shipping_usd=float(data.get("shipping_usd", 0.0)),
                total_usd=float(data.get("total_usd",
                                         data.get("base_usd", 0.0)
                                         + data.get("shipping_usd", 0.0))),
                lead_time=int(data.get("lead_time_days", 4)),
                source="api",
            )
        except Exception as exc:
            log.warning("API JLCPCB injoignable (%s) — fallback estimation", exc)
            return _estimate(params, self.get_capabilities().unit_price_factor, 15.0)

    def upload_gerbers(self, path: str) -> str:
        """Upload l'archive de gerbers → order_id (mock sans clé API)."""
        if not self.api_key:
            order_id = f"JLC-MOCK-{short_id('')}"
            log.info("upload gerbers simulé (pas de clé) → %s", order_id)
            return order_id
        try:
            import httpx  # lazy

            with open(path, "rb") as fh:
                resp = httpx.post(
                    f"{_API_BASE}/orders/gerbers",
                    headers={"X-JLC-KEY": self.api_key},
                    files={"file": (path.split("/")[-1], fh, "application/zip")},
                    timeout=60.0,
                )
                resp.raise_for_status()
                return str(resp.json().get("order_id", new_id("jlc")))
        except Exception as exc:
            log.warning("upload JLCPCB échoué (%s) — order mock", exc)
            return f"JLC-MOCK-{short_id('')}"

    # -- bibliothèque composants ----------------------------------------------
    def check_part_availability(self, mpn_list: list[str]) -> dict[str, dict[str, Any]]:
        """Disponibilité SMT par MPN — bibliothèque locale puis mock déterministe."""
        library = self._load_library()
        out: dict[str, dict[str, Any]] = {}
        for mpn in mpn_list:
            if not mpn:
                continue
            if mpn in library:
                out[mpn] = dict(library[mpn])
                continue
            # mock déterministe : hash du MPN → stock/prix stables entre runs
            digest = hashlib.md5(mpn.encode("utf-8")).digest()
            stock = int.from_bytes(digest[:2], "big") % 50_000
            basic = digest[2] % 4 == 0  # ~25% "basic part" (sans frais setup)
            out[mpn] = {
                "available": stock > 500,
                "stock": stock,
                "price_usd": round(0.01 + int.from_bytes(digest[3:4], "big") / 8.0, 4),
                "basic": basic,
                "source": "mock",
            }
        log.info("dispo JLCPCB vérifiée pour %d MPN", len(out))
        return out

    def _load_library(self) -> dict[str, dict[str, Any]]:
        """Charge data/component_library/*.json (cache local optionnel)."""
        library: dict[str, dict[str, Any]] = {}
        if _LIBRARY_DIR.is_dir():
            for file in _LIBRARY_DIR.glob("*.json"):
                try:
                    data = json.loads(file.read_text(encoding="utf-8"))
                    entries = data if isinstance(data, list) else data.get("parts", [])
                    for part in entries:
                        if isinstance(part, dict) and part.get("mpn"):
                            library[str(part["mpn"])] = {**part, "source": "library"}
                except Exception as exc:
                    log.warning("bibliothèque illisible (%s): %s", file, exc)
        return library
