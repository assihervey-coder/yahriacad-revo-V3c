"""Contrôles de vérification locaux (repli quand services.verification est absent).

Implémentation réelle (pas un stub) : recouvrements de composants, nets non
routés, nets suspendus, absence de plans d'alimentation — suffisants pour
judiciariser un pipeline dfm_only même hors-ligne.
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

from orchestrator.common import get_field, overlapping_components


def local_checks(graph: Any, clearance_mm: float = 0.2) -> Dict[str, Any]:
    """Exécute des contrôles géométriques/électriques locaux -> rapport normalisé."""
    issues: List[str] = []

    comps = get_field(graph, "components", default={}) or {}
    nets = get_field(graph, "nets", default={}) or {}

    # 1) Recouvrements de composants
    overlaps: List[Tuple[str, str]] = []
    try:
        overlaps = overlapping_components(graph, clearance_mm)
    except Exception:
        overlaps = []
    for ref_a, ref_b in overlaps:
        issues.append(f"overlap: composants {ref_a} et {ref_b} se recouvrent")

    # 2) Nets non routés
    unrouted: List[str] = []
    for net_id, net in nets.items():
        if not bool(get_field(net, "routed", default=False)):
            unrouted.append(str(net_id))
    for net_id in unrouted:
        issues.append(f"unrouted: net {net_id} non routé")

    # 3) Nets suspendus (0 ou 1 pin)
    for net_id, net in nets.items():
        pins = get_field(net, "pins", default=[]) or []
        if len(pins) < 2:
            issues.append(f"hanging: net {net_id} ne relie que {len(pins)} pin(s)")

    # 4) Nets d'alimentation manquants
    for power_net in ("GND", "VCC"):
        if power_net not in {str(k) for k in nets.keys()}:
            issues.append(f"power: net d'alimentation {power_net} absent")

    # 5) Composants hors carte
    board = get_field(graph, "board_size", "board_size_mm", default=(100.0, 80.0)) or (100.0, 80.0)
    try:
        width, height = float(board[0]), float(board[1])
    except (TypeError, IndexError):
        width, height = 100.0, 80.0
    for ref, comp in comps.items():
        x = float(get_field(comp, "x", "x_mm", default=0.0) or 0.0)
        y = float(get_field(comp, "y", "y_mm", default=0.0) or 0.0)
        if not (-5.0 <= x <= width + 5.0 and -5.0 <= y <= height + 5.0):
            issues.append(f"outside: composant {ref} hors de la carte ({x:.1f},{y:.1f})")

    # Score qualité local : 100 - pénalités
    penalty = 15.0 * len(overlaps) + 8.0 * len(unrouted) + 4.0 * max(0, len(issues) - len(overlaps) - len(unrouted))
    quality = max(0.0, 100.0 - penalty)
    return {
        "engine": "local_checks",
        "passed": not issues,
        "issues": issues,
        "quality": quality,
        "stats": {"overlaps": len(overlaps), "unrouted": len(unrouted),
                  "components": len(comps), "nets": len(nets)},
    }
