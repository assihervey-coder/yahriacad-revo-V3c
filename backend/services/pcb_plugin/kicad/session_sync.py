"""Synchronisation bidirectionnelle d'une session KiCad live.

Gère le mapping des refs entre le graphe local et le snapshot distant, la
détection de conflits (même ref modifié des deux côtés) et le push/pull de
révisions via le KiCadLiveHost + design_versioning.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from shared.utilities import get_logger

from services.pcb_plugin._compat import graph_from_dict, graph_to_dict

log = get_logger(__name__)


@dataclass
class SyncConflict:
    """Conflit sur un ref présent des deux côtés avec des états divergents."""

    ref: str
    fields: List[str] = field(default_factory=list)
    local: Dict[str, Any] = field(default_factory=dict)
    remote: Dict[str, Any] = field(default_factory=dict)


def _comp_state(comp: Any) -> Dict[str, Any]:
    """Signature comparable d'un composant (position + rotation + side)."""
    return {
        "x": round(float(getattr(comp, "x", 0.0)), 6),
        "y": round(float(getattr(comp, "y", 0.0)), 6),
        "rotation": round(float(getattr(comp, "rotation", 0.0) or 0.0), 6),
        "side": str(getattr(comp, "side", "top") or "top"),
    }


def _graph_state(graph_like: Any) -> Dict[str, Dict[str, Any]]:
    """Mapping ref → état, depuis un DesignGraph ou un snapshot dict."""
    if graph_like is None:
        return {}
    if hasattr(graph_like, "components") and not isinstance(graph_like, dict):
        return {ref: _comp_state(c) for ref, c in graph_like.components.items()}
    try:
        graph = graph_from_dict(graph_like)
        return _graph_state(graph)
    except Exception as exc:
        log.warning("snapshot distant illisible: %s", exc)
        return {}


class SessionSynchronizer:
    """Synchronise le design local avec la session KiCad distante."""

    def __init__(self, host: Any, versioning: Any = None) -> None:
        self.host = host
        self.versioning = versioning
        self.refs: Dict[str, Dict[str, Any]] = {}   # mapping des refs (dernier état sync)
        self.last_pushed_rev: int = 0
        self.last_pulled_rev: int = 0

    # -- helpers versioning (duck-typed) ------------------------------------
    def _commit(self, graph: Any, message: str) -> None:
        commit = getattr(self.versioning, "commit", None)
        if callable(commit):
            try:
                commit(graph, message)
            except Exception as exc:
                log.warning("versioning.commit échoué: %s", exc)

    def _current_rev(self) -> int:
        current = getattr(self.versioning, "current", None)
        if callable(current):
            try:
                rev = current()
                if rev is not None:
                    return int(getattr(rev, "rev", 0) or 0)
            except Exception:
                pass
        for attr in ("next_rev", "revision", "rev"):
            val = getattr(self.versioning, attr, None)
            if isinstance(val, int):
                return val
        return max(self.last_pushed_rev, self.last_pulled_rev)

    # -- API -----------------------------------------------------------------
    def detect_conflicts(self, local_rev: Any,
                         remote_snapshot: Any) -> List[SyncConflict]:
        """Détecte les refs modifiés en local ET en remote depuis la dernière sync."""
        local_state = _graph_state(local_rev)
        remote_state = _graph_state(remote_snapshot)
        conflicts: List[SyncConflict] = []
        for ref in sorted(set(local_state) & set(remote_state)):
            base = self.refs.get(ref)
            if base is None:
                continue  # première fois qu'on voit ce ref : pas d'historique divergent
            local_now, remote_now = local_state[ref], remote_state[ref]
            local_changed = any(base.get(k) != v for k, v in local_now.items())
            remote_changed = any(base.get(k) != v for k, v in remote_now.items())
            if local_changed and remote_changed:
                fields = [k for k in local_now
                          if local_now.get(k) != remote_now.get(k)]
                conflicts.append(SyncConflict(ref=ref, fields=fields,
                                              local=local_now, remote=remote_now))
        return conflicts

    async def push_revision(self, rev: Any) -> bool:
        """Pousse une révision (graph) vers KiCad et met à jour le mapping refs."""
        ok = await self.host.push_design(rev)
        if ok:
            self.refs.update(_graph_state(rev))
            self.last_pushed_rev = self._current_rev() + 1
            self._commit(rev, "sync: push vers KiCad")
        return ok

    async def pull_if_newer(self) -> Optional[Any]:
        """Récupère le design distant s'il est plus récent que le dernier pull."""
        remote = await self.host.pull_design()
        if remote is None:
            return None
        remote_rev = int(getattr(remote, "revision", 0) or 0)
        if remote_rev and remote_rev <= self.last_pulled_rev:
            log.info("remote (rev %d) pas plus récent — pull ignoré", remote_rev)
            return None
        self.last_pulled_rev = max(self.last_pulled_rev, remote_rev)
        self.refs.update(_graph_state(remote))
        self._commit(remote, "sync: pull depuis KiCad")
        return remote

    async def sync_bidirectional(self, local_graph: Any) -> Dict[str, Any]:
        """Push + pull en une passe, avec rapport de conflits."""
        remote = await self.host.pull_design() if self.host.connected else None
        conflicts = self.detect_conflicts(local_graph, remote)
        pushed = await self.push_revision(local_graph)
        return {"pushed": pushed, "conflicts": [vars(c) for c in conflicts],
                "refs": len(self.refs)}
