"""Persistance des designs (graphes sérialisés par révision).

Chemin : data/projects/{tenant}/{user}/{project}/design/rev_{n}.json
+ current.json (pointeur vers la révision courante).
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, List, Optional, Tuple

from orchestrator.common import data_root, deserialize_graph, graph_stats, serialize_graph
from shared.utilities import get_logger

log = get_logger("state.design")


class DesignStateManager:
    """Sauvegarde / rechargement des DesignGraph par révision."""

    def __init__(self, base_dir: Optional[str] = None) -> None:
        self.base = Path(base_dir) if base_dir else data_root()

    # -- chemins -------------------------------------------------------------
    def _design_dir(self, tenant: str, user: str, project: str) -> Path:
        return self.base / (tenant or "default") / (user or "default") / (project or "sans-projet") / "design"

    def _rev_path(self, tenant: str, user: str, project: str, rev: int) -> Path:
        return self._design_dir(tenant, user, project) / f"rev_{int(rev):06d}.json"

    def _current_path(self, tenant: str, user: str, project: str) -> Path:
        return self._design_dir(tenant, user, project) / "current.json"

    # -- opérations ------------------------------------------------------------
    def save_design(self, tenant: str, user: str, project: str, graph: Any, rev: int) -> Path:
        """Sérialise le graphe pour une révision donnée + met à jour le pointeur courant."""
        rev = max(0, int(rev or 0))
        directory = self._design_dir(tenant, user, project)
        directory.mkdir(parents=True, exist_ok=True)
        payload = {
            "rev": rev,
            "ts": time.time(),
            "graph": serialize_graph(graph),
        }
        rev_path = self._rev_path(tenant, user, project, rev)
        rev_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        self._current_path(tenant, user, project).write_text(
            json.dumps({"rev": rev, "ts": payload["ts"]}), encoding="utf-8")
        log.debug("design sauvegardé: %s rev=%s", rev_path, rev)
        return rev_path

    def load_design(self, tenant: str, user: str, project: str) -> Optional[Tuple[Any, int]]:
        """Charge le graphe courant -> (DesignGraph, rev) ou None."""
        rev = self._current_rev(tenant, user, project)
        if rev is None:
            history = self.history(tenant, user, project)
            rev = history[-1] if history else None
        if rev is None:
            return None
        loaded = self.load_revision(tenant, user, project, rev)
        if loaded is None:
            return None
        graph, actual_rev = loaded
        return graph, actual_rev

    def load_revision(self, tenant: str, user: str, project: str,
                      rev: int) -> Optional[Tuple[Any, int]]:
        path = self._rev_path(tenant, user, project, rev)
        if not path.is_file():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            graph = deserialize_graph(payload.get("graph") or {})
            if graph is None:
                return None
            return graph, int(payload.get("rev", rev))
        except Exception:
            log.warning("révision illisible: %s", path, exc_info=True)
            return None

    def history(self, tenant: str, user: str, project: str) -> List[int]:
        """Liste triée des révisions persistées."""
        directory = self._design_dir(tenant, user, project)
        if not directory.is_dir():
            return []
        revs: List[int] = []
        for file in directory.glob("rev_*.json"):
            try:
                revs.append(int(file.stem.split("_")[1]))
            except (IndexError, ValueError):
                continue
        return sorted(revs)

    def stats(self, tenant: str, user: str, project: str) -> dict:
        loaded = self.load_design(tenant, user, project)
        if loaded is None:
            return {}
        graph, rev = loaded
        return {"rev": rev, **graph_stats(graph)}

    # -- interne ------------------------------------------------------------
    def _current_rev(self, tenant: str, user: str, project: str) -> Optional[int]:
        path = self._current_path(tenant, user, project)
        if not path.is_file():
            return None
        try:
            return int(json.loads(path.read_text(encoding="utf-8")).get("rev"))
        except Exception:
            return None
