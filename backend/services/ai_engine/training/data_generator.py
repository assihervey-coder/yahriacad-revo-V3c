"""Générateur d'épisodes de placement — graphes aléatoires réalistes.

Nécessite services.design_core (DesignGraph) à l'appel — import lazy.
Les positions « optimales » sont approximées par itérations de centroïde :
chaque composant converge vers le centroïde de ses voisins connectés.
"""
from __future__ import annotations

import random

import numpy as np
from shared.utilities import get_logger

log = get_logger("ai_engine.training.data_generator")

# pool de composants réalistes (ref préfixe, w, h, power, price)
_PARTS = [
    ("U", 12.0, 12.0, 0.9, 8.50),   # MCU/module
    ("U", 5.0, 4.0, 0.4, 1.20),     # capteur
    ("U", 4.0, 3.0, 0.2, 0.60),     # LDO / interface
    ("C", 1.0, 0.5, 0.0, 0.02),     # condensateur
    ("R", 1.0, 0.5, 0.0, 0.01),     # résistance
    ("J", 8.0, 5.0, 0.0, 0.35),     # connecteur
    ("D", 1.6, 0.8, 0.05, 0.05),    # LED
    ("L", 3.2, 2.5, 0.0, 0.10),     # inductance
]


def _random_graph(n_components: int, rng: random.Random):
    """Construit un DesignGraph aléatoire réaliste (composants + nets)."""
    from services.ai_engine._dc_bridge import design_graph_cls

    DesignGraph = design_graph_cls()
    graph = DesignGraph()
    board_w, board_h = 60.0, 40.0

    refs: list[str] = []
    counters: dict[str, int] = {}
    for _ in range(n_components):
        prefix, w, h, power, price = rng.choice(_PARTS)
        counters[prefix] = counters.get(prefix, 0) + 1
        ref = f"{prefix}{counters[prefix]}"
        refs.append(ref)
        graph.add_component(
            ref, value=prefix, footprint=f"FP_{prefix}",
            x=rng.uniform(5.0, board_w - 5.0),
            y=rng.uniform(5.0, board_h - 5.0),
            rotation=rng.choice([0, 90, 180, 270]),
            bbox=(w, h), power_w=power, price_usd=price, placed=True,
        )

    # nets : chaînes + bus d'alimentation partagés
    for i, ref in enumerate(refs[:-1]):
        other = refs[(i + 1) % len(refs)]
        net_id = f"n_sig_{i}"
        graph.add_net(net_id=net_id, name=f"sig_{i}", class_name="default")
        graph.connect(ref, "1", net_id)
        graph.connect(other, "1", net_id)
    # rails partagés
    graph.add_net(net_id="n_3v3", name="3V3", class_name="power")
    for ref in refs[: max(1, len(refs) // 2)]:
        graph.connect(ref, "2", "n_3v3")
    graph.add_net(net_id="n_gnd", name="GND", class_name="power")
    for ref in refs:
        graph.connect(ref, "3", "n_gnd")
    return graph


def _centroid_optimize(graph, sweeps: int = 25,
                       lr: float = 0.6) -> dict[str, tuple[float, float]]:  # noqa: ANN001
    """Positions optimales approximées : chaque comp → centroïde de ses voisins."""
    adjacency: dict[str, list[str]] = {ref: [] for ref in graph.components}
    for net in graph.nets.values():
        refs = sorted({str(pin[0]) for pin in (getattr(net, "pins", []) or [])
                       if isinstance(pin, (list, tuple)) and len(pin) >= 2})
        for r in refs:
            adjacency.setdefault(r, []).extend(
                o for o in refs if o != r)

    pos = {ref: (c.x, c.y) for ref, c in graph.components.items()}
    for _ in range(sweeps):
        new_pos = dict(pos)
        for ref, neighbors in adjacency.items():
            nbrs = [n for n in neighbors if n in pos]
            if not nbrs:
                continue
            cx = sum(pos[n][0] for n in nbrs) / len(nbrs)
            cy = sum(pos[n][1] for n in nbrs) / len(nbrs)
            px, py = pos[ref]
            new_pos[ref] = (px + lr * (cx - px), py + lr * (cy - py))
        pos = new_pos
    return pos


def generate_placement_episode(n_components: int = 10, seed: int | None = None
                               ) -> tuple[object, dict[str, tuple[float, float]]]:
    """Un épisode : (DesignGraph aléatoire, positions optimales approximées).

    Le graphe retourné a des positions INITIALES aléatoires ; les positions
    optimales (centroïde itéré) sont fournies à part pour l'entraînement.
    """
    rng = random.Random(seed)
    graph = _random_graph(max(3, n_components), rng)
    optimal = _centroid_optimize(graph)
    log.debug("épisode généré: %d composants, %d nets",
              len(graph.components), len(graph.nets))
    return graph, optimal


def generate_batch(n: int, n_components: int = 10, seed: int | None = None
                   ) -> list[tuple[object, dict[str, tuple[float, float]]]]:
    """Lot de n épisodes (seeds décalés pour la variété reproductible)."""
    base = seed if seed is not None else int(np.random.randint(0, 2**31 - 1))
    return [generate_placement_episode(n_components, seed=base + i)
            for i in range(n)]
