"""Règles de design génériques (indépendantes de l'usine)."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class DesignRules:
    """Règles géométriques minimales utilisées par le DRC.

    Les valeurs par défaut correspondent à un process standard 4 couches FR4.
    """

    min_trace_mm: float = 0.2          # largeur de trace minimale
    min_clearance_mm: float = 0.2      # isolement cuivre/cuivre minimal
    min_via_drill_mm: float = 0.3      # diamètre de forage via minimal
    min_via_pad_mm: float = 0.6        # diamètre de pad via minimal
    min_annular_ring_mm: float = 0.15  # anneau autour du forage
    max_aspect_ratio: float = 8.0      # épaisseur carte / forage
    min_edge_margin_mm: float = 0.5    # cuivre trop proche du bord
    board_thickness_mm: float = 1.6

    @classmethod
    def from_factory_profile(cls, profile: dict) -> "DesignRules":
        """Construit les règles depuis un profil usine (manufacturing_rules)."""
        return cls(
            min_trace_mm=float(profile.get("min_trace_mm", 0.2)),
            min_clearance_mm=float(profile.get("min_clearance_mm", 0.2)),
            min_via_drill_mm=float(profile.get("min_hole_mm", 0.3)),
            min_via_pad_mm=float(profile.get("min_hole_mm", 0.3)) * 2.0,
            min_annular_ring_mm=float(profile.get("min_annular_ring_mm", 0.15)),
            max_aspect_ratio=float(profile.get("max_aspect_ratio", 8.0)),
        )

    def to_dict(self) -> dict:
        return self.__dict__.copy()
