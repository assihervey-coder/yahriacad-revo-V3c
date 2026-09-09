"""Règles manufacturières par usine (PCBWay, JLCPCB) — cerveau physique / réalité industrielle."""
from __future__ import annotations

import os
from functools import lru_cache
from typing import Any

from shared.utilities import get_logger

log = get_logger(__name__)

# Profils embarqués (fallback) — remplacés par configs/factories/*.yaml si présents.
_EMBEDDED: dict[str, dict[str, Any]] = {
    "jlcpcb": {
        "name": "JLCPCB",
        "min_trace_mm": 0.127,
        "min_clearance_mm": 0.127,
        "min_hole_mm": 0.2,
        "min_annular_ring_mm": 0.13,
        "max_layers": 20,
        "max_aspect_ratio": 10.0,
        "lead_time_days": 4,
        "assembly": True,
        "unit_price_factor": 1.0,
    },
    "pcbway": {
        "name": "PCBWay",
        "min_trace_mm": 0.1,
        "min_clearance_mm": 0.1,
        "min_hole_mm": 0.2,
        "min_annular_ring_mm": 0.15,
        "max_layers": 14,
        "max_aspect_ratio": 12.0,
        "lead_time_days": 5,
        "assembly": True,
        "unit_price_factor": 1.25,
    },
}


def _try_load_yaml_profiles() -> dict[str, dict[str, Any]]:
    """Charge configs/factories/*.yaml si pyyaml disponible, sinon fallback embarqué."""
    profiles: dict[str, dict[str, Any]] = {}
    cfg_dir = os.path.join(os.getcwd(), "configs", "factories")
    try:
        import yaml  # optional

        if os.path.isdir(cfg_dir):
            for fname in os.listdir(cfg_dir):
                if fname.endswith((".yaml", ".yml")):
                    with open(os.path.join(cfg_dir, fname), encoding="utf-8") as f:
                        data = yaml.safe_load(f) or {}
                    key = fname.rsplit(".", 1)[0].lower()
                    if isinstance(data, dict):
                        profiles[key] = data
    except Exception as exc:  # pragma: no cover
        log.debug("yaml factory profiles indisponibles (%s) — fallback embarqué", exc)
    for key, val in _EMBEDDED.items():
        profiles.setdefault(key, val)
    return profiles


@lru_cache(maxsize=1)
def _profiles() -> dict[str, dict[str, Any]]:
    return _try_load_yaml_profiles()


class ManufacturingRules:
    """Accès aux règles par usine + helpers de comparaison design ↔ usine."""

    @staticmethod
    def get(factory: str = "jlcpcb") -> dict[str, Any]:
        key = factory.lower().strip()
        profiles = _profiles()
        if key not in profiles:
            log.warning("usine inconnue '%s' — profil jlcpcb utilisé", factory)
            key = "jlcpcb"
        return dict(profiles[key])

    @staticmethod
    def list_profiles() -> dict[str, dict[str, Any]]:
        return {k: dict(v) for k, v in _profiles().items()}

    @staticmethod
    def compatible(graph_layers: int, factory: str = "jlcpcb") -> list[str]:
        """Retourne les incompatibilités design ↔ usine (textes, vide si OK)."""
        prof = ManufacturingRules.get(factory)
        issues: list[str] = []
        if graph_layers > int(prof.get("max_layers", 4)):
            issues.append(
                f"{graph_layers} couches > maximum {prof.get('max_layers')} chez {prof.get('name')}")
        return issues
