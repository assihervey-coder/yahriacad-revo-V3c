"""Estimation des coûts — board, assemblage, composants, total + suggestions."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple

from shared.utilities import get_logger

from services.manufacturing_intelligence.factory_profiles import FactoryProfile

log = get_logger(__name__)

_BASE_BOARD_USD = 5.0          # prix plancher prototype
_AREA_FACTOR_USD_PER_MM2 = 0.0015
_LAYER_SURCHARGE_USD = 2.0     # par couche au-delà de 2
_ASSEMBLY_SETUP_USD = 25.0
_ASSEMBLY_PER_SMD_USD = 0.5
_COMPONENT_MARGIN = 1.3        # marge achat composants


@dataclass
class CostBreakdown:
    """Décomposition du coût unitaire (quantité 1)."""

    board_usd: float
    assembly_usd: float
    components_usd: float
    total_usd: float
    details: Dict[str, Any] = field(default_factory=dict)


def _is_smd(comp: Any) -> bool:
    fp = str(getattr(comp, "footprint", "") or "").lower()
    return not any(tag in fp for tag in ("tht", "tth", "dip", "to-", "radial", "axial"))


class CostEstimator:
    """Estime le coût de revient d'un DesignGraph pour un profil d'usine."""

    def __init__(self, profile: FactoryProfile) -> None:
        self.profile = profile

    def estimate(self, graph: Any) -> CostBreakdown:
        """Board (base 5$ + area*factor + surcharge couches, qty 1) + assembly + BOM."""
        w, h = graph.board_size if isinstance(graph.board_size, (tuple, list)) else (50.0, 40.0)
        area_mm2 = float(w) * float(h)
        n_layers = len(list(getattr(graph, "layers", []) or [])) or 2
        factor = float(self.profile.unit_price_factor)

        board_usd = (_BASE_BOARD_USD
                     + area_mm2 * _AREA_FACTOR_USD_PER_MM2 * factor
                     + max(0, n_layers - 2) * _LAYER_SURCHARGE_USD * factor)

        comps = list(graph.components.values())
        smd_count = sum(1 for c in comps if _is_smd(c))
        assembly_usd = 0.0
        if self.profile.assembly and comps:
            assembly_usd = _ASSEMBLY_SETUP_USD + smd_count * _ASSEMBLY_PER_SMD_USD

        components_usd = sum(float(getattr(c, "price_usd", 0.0) or 0.0)
                             for c in comps) * _COMPONENT_MARGIN

        breakdown = CostBreakdown(
            board_usd=round(board_usd, 2),
            assembly_usd=round(assembly_usd, 2),
            components_usd=round(components_usd, 2),
            total_usd=round(board_usd + assembly_usd + components_usd, 2),
            details={
                "area_mm2": round(area_mm2, 2),
                "layers": n_layers,
                "components": len(comps),
                "smd_components": smd_count,
                "factory": self.profile.name,
                "quantity": 1,
            },
        )
        log.info("coût %s: %.2f$ (board %.2f, assembly %.2f, comp %.2f)",
                 self.profile.name, breakdown.total_usd, breakdown.board_usd,
                 breakdown.assembly_usd, breakdown.components_usd)
        return breakdown

    # -- optimisation -----------------------------------------------------------
    def optimize_for_cost(self, graph: Any) -> List[str]:
        """Suggestions concrètes de réduction de coût, chiffrées."""
        suggestions: List[str] = []
        w, h = graph.board_size if isinstance(graph.board_size, (tuple, list)) else (50.0, 40.0)
        area_mm2 = float(w) * float(h)
        n_layers = len(list(getattr(graph, "layers", []) or [])) or 2
        factor = float(self.profile.unit_price_factor)

        if n_layers > 2:
            saving = max(0, n_layers - 2) * _LAYER_SURCHARGE_USD * factor
            suggestions.append(
                f"Réduire de {n_layers} à 2 couches : ~{saving:.2f}$ économisés par carte")

        used_mm2 = sum(
            float(getattr(c, "bbox", (0, 0))[0]) * float(getattr(c, "bbox", (0, 0))[1])
            for c in graph.components.values())
        if area_mm2 > 0 and used_mm2 / area_mm2 < 0.3 and used_mm2 > 0:
            target = used_mm2 / 0.5  # densité cible 50%
            saving = (area_mm2 - target) * _AREA_FACTOR_USD_PER_MM2 * factor
            suggestions.append(
                f"Rétrecir la carte ({area_mm2:.0f} → {target:.0f} mm², "
                f"occupation {100 * used_mm2 / area_mm2:.0f}%) : ~{saving:.2f}$")

        passive_values: Dict[Tuple[str, str], int] = {}
        for ref, comp in graph.components.items():
            if ref[:1].upper() in {"R", "C", "L"}:
                passive_values[(str(getattr(comp, "value", "")),
                                str(getattr(comp, "footprint", "")))] = \
                    passive_values.get((str(getattr(comp, "value", "")),
                                        str(getattr(comp, "footprint", ""))), 0) + 1
        if len(passive_values) > 6:
            suggestions.append(
                f"Regrouper les {len(passive_values)} valeurs passives distinctes "
                f"vers 5-6 valeurs standard (remises volume + bobines SMT partagées)")

        comps = list(graph.components.values())
        if self.profile.assembly and comps and all(not _is_smd(c) for c in comps):
            suggestions.append("Design 100% traversant : désactiver l'assemblage SMT "
                               f"(-{_ASSEMBLY_SETUP_USD:.0f}$ de setup)")

        expensive = sorted(
            (float(getattr(c, "price_usd", 0.0) or 0.0), str(getattr(c, "ref", "")))
            for c in comps)[-3:]
        top = [f"{ref} ({price:.2f}$)" for price, ref in reversed(expensive) if price > 0]
        if top:
            suggestions.append("Alternatives moins chères à sourcer pour: " + ", ".join(top))

        if not suggestions:
            suggestions.append("Coût déjà optimisé pour ce profil d'usine")
        return suggestions
