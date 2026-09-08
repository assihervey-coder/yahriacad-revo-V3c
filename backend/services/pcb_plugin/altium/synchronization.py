"""Synchronisation Altium ↔ DesignGraph — compare par (ref, position, nets).

Le synchroniseur garde un snapshot du dernier état synchronisé ; à chaque passe
il détecte les composants modifiés côté local et côté Altium, signale les
conflits (modifiés des deux côtés) et applique une résolution.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple

from shared.utilities import get_logger

log = get_logger(__name__)


@dataclass
class SyncReport:
    """Résultat d'une passe de synchronisation Altium."""

    changed_components: List[str] = field(default_factory=list)
    conflicts: List[str] = field(default_factory=list)
    resolution: str = "none"
    details: Dict[str, Any] = field(default_factory=dict)


def _nets_signature(comp: Any) -> List[Tuple[str, str]]:
    """Signature des nets d'un composant : [(pad_name, net_id)] triée."""
    out: List[Tuple[str, str]] = []
    for pad in list(getattr(comp, "pads", []) or []):
        out.append((str(getattr(pad, "name", "")), str(getattr(pad, "net_id", "") or "")))
    return sorted(out)


def _state(graph: Any) -> Dict[str, Dict[str, Any]]:
    """ref → signature comparable (position, rotation, side, nets)."""
    out: Dict[str, Dict[str, Any]] = {}
    for ref, comp in graph.components.items():
        out[ref] = {
            "position": (round(float(comp.x), 6), round(float(comp.y), 6)),
            "rotation": round(float(getattr(comp, "rotation", 0.0) or 0.0), 6),
            "nets": _nets_signature(comp),
        }
    return out


class AltiumSynchronizer:
    """Synchronise le graphe local avec l'état Altium tenu par un AltiumBridge."""

    def __init__(self, bridge: Any, resolution: str = "local_wins") -> None:
        self.bridge = bridge
        self.resolution = resolution  # local_wins | remote_wins
        self._snapshot: Dict[str, Dict[str, Any]] = {}

    def sync(self, graph: Any, remote: Any = None,
             resolution: str = "") -> SyncReport:
        """Une passe de sync : détecte changements/conflits et applique la résolution."""
        resolution = resolution or self.resolution
        remote_graph = remote if remote is not None else getattr(self.bridge, "remote_graph", None)
        if remote_graph is None:
            self._snapshot = _state(graph)
            self.bridge.remote_graph = graph
            return SyncReport(resolution="init", details={"refs": len(self._snapshot)})

        local_state, remote_state = _state(graph), _state(remote_graph)
        changed_local = sorted(
            ref for ref, st in local_state.items()
            if self._snapshot.get(ref) != st
        )
        changed_remote = sorted(
            ref for ref, st in remote_state.items()
            if self._snapshot.get(ref) != st
        )
        conflicts = sorted(set(changed_local) & set(changed_remote))

        applied = 0
        if resolution == "remote_wins":
            for ref in set(changed_remote) - set(conflicts):
                if ref in remote_state and ref in remote_graph.components:
                    graph.components[ref] = copy.deepcopy(remote_graph.components[ref])
                    applied += 1

        self._snapshot = _state(graph)
        self.bridge.remote_graph = graph
        report = SyncReport(
            changed_components=sorted(set(changed_local) | set(changed_remote)),
            conflicts=conflicts,
            resolution=resolution or "local_wins",
            details={"local_changed": changed_local, "remote_changed": changed_remote,
                     "applied_remote": applied},
        )
        if conflicts:
            log.warning("sync Altium: %d conflit(s) %s", len(conflicts), conflicts)
        return report
