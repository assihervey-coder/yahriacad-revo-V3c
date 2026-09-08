"""Conftest global des tests PCB_AI_DESIGNER_V3.

PYTHONPATH : les tests importent les paquets `shared` (racine) et
`services`/`api_gateway`/`orchestrator` (backend/). Deux mécanismes couvrent
cela :
  - pyproject.toml  → [tool.pytest.ini_options] pythonpath = [".", "backend"] ;
  - ce conftest     → insertion défensive de sys.path (exécution hors pytest,
    éditeurs, runners exotiques).

Lancement : `cd pcb_ai_designer_v3 && PYTHONPATH=.:backend python3 -m pytest tests/unit -q`
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
for _path in (str(REPO_ROOT), str(REPO_ROOT / "backend")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from services.design_core import DesignGraph  # noqa: E402


@pytest.fixture()
def design_graph() -> DesignGraph:
    """Petit DesignGraph partagé : 2 composants placés + 1 net connecté.

    Sert de socle minimal aux tests unitaires (graphe, contraintes,
    versioning, modèle mental) — jamais muté par les fixtures elles-mêmes,
    les tests qui modifient le graphe utilisent `.copy()`.
    """
    graph = DesignGraph(project_id="test-graph", name="test", board_size=(50.0, 40.0))
    graph.add_component("R1", value="10k", footprint="0603", x=10.0, y=10.0, placed=True)
    graph.add_component("C1", value="100n", footprint="0603", x=30.0, y=10.0, placed=True)
    graph.add_net(name="GND", class_name="power")
    graph.connect("R1", "1", "N1")
    graph.connect("C1", "1", "N1")
    return graph
