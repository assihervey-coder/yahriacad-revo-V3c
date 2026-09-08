"""Compatibilité composants — avertissements (tension, logique, interfaces)."""
from __future__ import annotations

from typing import List, Optional

from shared.utilities import get_logger
from services.ai_engine.knowledge_graph.kg import KnowledgeGraph

log = get_logger("ai_engine.kg.compatibility")

COMP = "comp:"


def _node_props(kg: KnowledgeGraph, mpn: str) -> Optional[dict]:
    node = kg.nodes.get(COMP + mpn) or kg.nodes.get(mpn)
    return node.props if node else None


def check_compatibility(kg: KnowledgeGraph, mpn_a: str, mpn_b: str) -> List[str]:
    """Vérifie la compatibilité de deux composants → liste d'avertissements.

    Détecte : mismatch de tension d'alimentation, logique 3V3 vs 5V,
    incompatibilité d'interface (I2C vs SPI sans bridge).
    """
    warnings: List[str] = []
    pa, pb = _node_props(kg, mpn_a), _node_props(kg, mpn_b)
    if pa is None or pb is None:
        missing = mpn_a if pa is None else mpn_b
        warnings.append(f"composant inconnu dans le KG: {missing}")
        return warnings

    va, vb = pa.get("voltage"), pb.get("voltage")
    if va is not None and vb is not None:
        try:
            fa, fb = float(va), float(vb)
            if abs(fa - fb) > 0.5:
                warnings.append(
                    f"domaine de tension différent : {mpn_a}={fa}V, "
                    f"{mpn_b}={fb}V — prévoir un level shifter ou une alimentation dédiée")
                if {fa, fb} <= {3.3, 5.0}:
                    warnings.append(
                        f"logique mixte 3V3/5V entre {mpn_a} et {mpn_b} : "
                        "vérifier la tolérance 5V des pins (datasheet)")
        except (TypeError, ValueError):
            pass

    ia = {str(i).lower() for i in pa.get("interfaces", [])}
    ib = {str(i).lower() for i in pb.get("interfaces", [])}
    if ia and ib and not (ia & ib):
        warnings.append(
            f"interfaces incompatibles : {mpn_a} {sorted(ia)} vs {mpn_b} "
            f"{sorted(ib)} — un bridge/level-shifter est nécessaire")

    # substitut déclaré = signal d'info utile
    if kg.has_edge(COMP + mpn_a, COMP + mpn_b, "substitute"):
        warnings.append(
            f"{mpn_b} est un substitut déclaré de {mpn_a} — vérifier le pinout")

    return warnings


def build_compatibility_edges(kg: KnowledgeGraph) -> int:
    """Annote le KG : arêtes 'compatible' / 'incompatible' entre composants.

    Retourne le nombre d'arêtes ajoutées.
    """
    comps = [n.id for n in kg.nodes.values() if n.kind == "component"]
    added = 0
    for i, a in enumerate(comps):
        for b in comps[i + 1:]:
            mpn_a = kg.nodes[a].props.get("mpn", a)
            mpn_b = kg.nodes[b].props.get("mpn", b)
            warns = check_compatibility(kg, mpn_a, mpn_b)
            hard = any("incompatibles" in w or "inconnu" in w for w in warns)
            if hard:
                kg.add_edge(a, b, "incompatible", {"warnings": warns})
            else:
                kg.add_edge(a, b, "compatible", {"warnings": warns})
            added += 1
    log.info("compatibilité : %d paires annotées", added)
    return added
