"""Profils d'usines PCB — contraintes DFM et facteurs de prix par fabricant."""
from __future__ import annotations

from dataclasses import asdict, dataclass

from shared.utilities import get_logger

log = get_logger(__name__)


@dataclass(frozen=True)
class FactoryProfile:
    """Capacités et tarifs d'une usine de fabrication PCB."""

    name: str
    min_trace_mm: float
    min_clearance_mm: float
    min_hole_mm: float
    min_annular_ring_mm: float
    max_layers: int
    min_trace_oz: float = 1.0
    lead_time_days: int = 5
    unit_price_factor: float = 1.0
    assembly: bool = True


# Valeurs réalistes (specs publiques 2024, prototypes 2-4 couches)
DEFAULTS: dict[str, FactoryProfile] = {
    "jlcpcb": FactoryProfile(
        name="jlcpcb",
        min_trace_mm=0.127,      # 5 mil
        min_clearance_mm=0.127,  # 5 mil
        min_hole_mm=0.2,         # 0.2 mm mécanique standard
        min_annular_ring_mm=0.15,
        max_layers=20,
        min_trace_oz=1.0,
        lead_time_days=4,
        unit_price_factor=1.0,
        assembly=True,
    ),
    "pcbway": FactoryProfile(
        name="pcbway",
        min_trace_mm=0.1,        # 4 mil
        min_clearance_mm=0.1,
        min_hole_mm=0.2,
        min_annular_ring_mm=0.15,
        max_layers=14,
        min_trace_oz=1.0,
        lead_time_days=3,
        unit_price_factor=1.15,
        assembly=True,
    ),
}


def get_profile(name: str) -> FactoryProfile:
    """Profil par nom (insensible à la casse) ; ValueError si inconnu."""
    key = (name or "").strip().lower()
    if key in DEFAULTS:
        return DEFAULTS[key]
    raise ValueError(
        f"usine inconnue: {name!r} — disponibles: {', '.join(sorted(DEFAULTS))}")


def list_profiles() -> list[str]:
    """Noms des profils disponibles."""
    return sorted(DEFAULTS)


def profile_dict(profile: FactoryProfile) -> dict[str, object]:
    """Sérialisation du profil (dict plat)."""
    return asdict(profile)
