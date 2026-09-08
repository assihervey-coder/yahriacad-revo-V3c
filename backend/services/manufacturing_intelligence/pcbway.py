"""Client PCBWay — capacités, devis, upload de gerbers.

Avec PCBWAY_API_KEY : appels httpx réels (import lazy). Sans clé : estimation
locale déterministe (mock) — aucune clé API en dur dans le code.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, Optional

from shared.utilities import get_logger, new_id, short_id
from shared.utilities.config import get_settings

from services.manufacturing_intelligence.factory_profiles import (
    FactoryProfile,
    get_profile,
)

log = get_logger(__name__)

_API_BASE = "https://www.pcbway.com/api/v2"


@dataclass
class Quote:
    """Devis de fabrication (USD)."""

    base_usd: float
    shipping_usd: float
    total_usd: float
    lead_time: int
    source: str = "estimate"  # estimate | api


def _estimate(params: Dict[str, Any], factor: float, shipping: float) -> Quote:
    """Estimation locale : base 5$ + surface + surcharge couches + quantité."""
    w = float(params.get("width_mm", 50.0))
    h = float(params.get("height_mm", 40.0))
    layers = int(params.get("layers", 2))
    qty = max(1, int(params.get("quantity", 5)))
    area = w * h  # mm²
    per_board = 5.0 + area * 0.0015 * factor + max(0, layers - 2) * 2.0 * factor
    if float(params.get("min_trace_mm", 0.2)) < 0.15:
        per_board *= 1.1  # techn avancée
    base = per_board * qty
    lead = int(params.get("lead_time_days", 4))
    return Quote(base_usd=round(base, 2), shipping_usd=round(shipping, 2),
                 total_usd=round(base + shipping, 2), lead_time=lead)


class PCBWayClient:
    """Client REST PCBWay (API réelle si clé, estimation locale sinon)."""

    def __init__(self, api_key: Optional[str] = None) -> None:
        self.api_key = api_key or get_settings().pcbway_api_key or None
        self.factory = "pcbway"

    def get_capabilities(self) -> FactoryProfile:
        """Profil DFM PCBWay."""
        return get_profile("pcbway")

    def quote(self, params: Dict[str, Any]) -> Quote:
        """Devis : API réelle si clé configurée, estimation locale sinon."""
        if not self.api_key:
            log.info("PCBWAY_API_KEY absente — devis estimé localement")
            return _estimate(params, self.get_capabilities().unit_price_factor, 18.0)
        try:
            import httpx  # lazy

            resp = httpx.post(
                f"{_API_BASE}/order/quote",
                json=params,
                headers={"X-API-KEY": self.api_key},
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
                lead_time=int(data.get("lead_time_days", 5)),
                source="api",
            )
        except Exception as exc:
            log.warning("API PCBWay injoignable (%s) — fallback estimation", exc)
            return _estimate(params, self.get_capabilities().unit_price_factor, 18.0)

    def upload_gerbers(self, path: str) -> str:
        """Upload l'archive de gerbers → order_id (mock sans clé API)."""
        if not self.api_key:
            order_id = f"PCBWAY-MOCK-{short_id('')}"
            log.info("upload gerbers simulé (pas de clé) → %s", order_id)
            return order_id
        try:
            import httpx  # lazy

            with open(path, "rb") as fh:
                resp = httpx.post(
                    f"{_API_BASE}/order/gerbers",
                    headers={"X-API-KEY": self.api_key},
                    files={"file": (path.split("/")[-1], fh, "application/zip")},
                    timeout=60.0,
                )
                resp.raise_for_status()
                return str(resp.json().get("order_id", new_id("pcbway")))
        except Exception as exc:
            log.warning("upload PCBWay échoué (%s) — order mock", exc)
            return f"PCBWAY-MOCK-{short_id('')}"
