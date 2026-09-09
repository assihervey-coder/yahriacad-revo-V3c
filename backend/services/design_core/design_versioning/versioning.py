"""DesignVersioning — historique de révisions et branches du DesignGraph.

Chaque commit stocke un snapshot complet (graph.to_dict()) ; restore/diff/
persist permettent rollback, comparaison et reprise de session.
"""
from __future__ import annotations

import builtins
import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from services.design_core.design_graph.graph import DesignGraph

log = logging.getLogger(__name__)

# Racine données : <repo>/data/projects (surchargeable par PCB3_DATA_DIR)
_REPO_ROOT = Path(__file__).resolve().parents[4]
DATA_ROOT = Path(os.getenv("PCB3_DATA_DIR", str(_REPO_ROOT / "data" / "projects")))


@dataclass
class Revision:
    """Une révision = snapshot complet du design à un instant donné."""

    rev: int
    message: str
    author: str
    ts: float
    snapshot: dict[str, Any]
    parent_rev: int | None = None

    def to_dict(self, include_snapshot: bool = True) -> dict[str, Any]:
        d = {
            "rev": self.rev, "message": self.message, "author": self.author,
            "ts": self.ts, "parent_rev": self.parent_rev,
        }
        if include_snapshot:
            d["snapshot"] = self.snapshot
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Revision:
        return cls(
            rev=int(d.get("rev", 0) or 0),
            message=str(d.get("message", "") or ""),
            author=str(d.get("author", "agent") or "agent"),
            ts=float(d.get("ts", 0.0) or 0.0),
            snapshot=dict(d.get("snapshot", {})),
            parent_rev=d.get("parent_rev"),
        )


@dataclass
class Branch:
    """Branche de design pointant sur une révision de tête."""

    name: str
    head_rev: int = 0
    created_from: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "head_rev": self.head_rev, "created_from": self.created_from}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Branch:
        return cls(
            name=str(d.get("name", "main")),
            head_rev=int(d.get("head_rev", 0) or 0),
            created_from=d.get("created_from"),
        )


class DesignVersioning:
    """Versioning type git simplifié : commits, branches, restore, diff, persist."""

    def __init__(self, project_id: str) -> None:
        self.project_id = project_id
        self._revisions: dict[int, Revision] = {}
        self._next_rev: int = 1
        self._branches: dict[str, Branch] = {"main": Branch(name="main", head_rev=0, created_from=None)}
        self._current_branch: str = "main"

    # -------------------------------------------------------------------- commits
    def commit(self, graph: DesignGraph, message: str, author: str = "agent") -> Revision:
        """Crée une révision (snapshot du graphe) au sommet de la branche courante."""
        head = self._branches[self._current_branch].head_rev
        revision = Revision(
            rev=self._next_rev, message=message, author=author, ts=time.time(),
            snapshot=graph.to_dict(), parent_rev=head or None,
        )
        self._revisions[revision.rev] = revision
        self._next_rev += 1
        self._branches[self._current_branch].head_rev = revision.rev
        log.info("révision r%d committée sur '%s' (%s)", revision.rev, self._current_branch, message)
        return revision

    def current(self) -> Revision | None:
        """Révision de tête de la branche courante (None si aucun commit)."""
        head = self._branches[self._current_branch].head_rev
        return self._revisions.get(head)

    def get(self, rev: int) -> Revision:
        """Révision par numéro, KeyError explicite sinon."""
        try:
            return self._revisions[int(rev)]
        except KeyError:
            raise KeyError(f"révision r{rev} inexistante") from None

    def list(self) -> builtins.list[Revision]:
        """Toutes les révisions, triées par numéro."""
        return [self._revisions[r] for r in sorted(self._revisions)]

    # ------------------------------------------------------------------- branches
    def branch(self, name: str, from_rev: int | None = None) -> Branch:
        """Crée une branche pointant sur from_rev (ou la tête courante)."""
        if name in self._branches:
            raise ValueError(f"branche '{name}' existe déjà")
        base = from_rev if from_rev is not None else self._branches[self._current_branch].head_rev
        if base and base not in self._revisions:
            raise KeyError(f"révision r{base} inexistante")
        br = Branch(name=name, head_rev=base or 0, created_from=base or None)
        self._branches[name] = br
        return br

    def checkout(self, name: str) -> Branch:
        """Bascule la branche courante (les commits suivants s'y accumulent)."""
        if name not in self._branches:
            raise KeyError(f"branche '{name}' inexistante")
        self._current_branch = name
        return self._branches[name]

    def branches(self) -> dict[str, Branch]:
        """Toutes les branches, par nom."""
        return dict(self._branches)

    # -------------------------------------------------------------------- restore
    def restore(self, rev: int) -> DesignGraph:
        """Reconstruit le DesignGraph d'une révision (rollback)."""
        snapshot = self.get(rev).snapshot
        log.info("restore r%d (projet %s)", rev, self.project_id)
        return DesignGraph.from_dict(snapshot)

    def diff(self, a_rev: int, b_rev: int) -> dict[str, Any]:
        """Résumé des différences entre deux révisions (composants, nets, board)."""
        sa, sb = self.get(a_rev).snapshot, self.get(b_rev).snapshot
        ca = {c.get("ref", ""): c for c in sa.get("components", [])}
        cb = {c.get("ref", ""): c for c in sb.get("components", [])}
        moved: dict[str, dict[str, list[float]]] = {}
        for ref in ca.keys() & cb.keys():
            a, b = ca[ref], cb[ref]
            if (a.get("x"), a.get("y"), a.get("rotation")) != (b.get("x"), b.get("y"), b.get("rotation")):
                moved[ref] = {
                    "from": [a.get("x", 0.0), a.get("y", 0.0)],
                    "to": [b.get("x", 0.0), b.get("y", 0.0)],
                }
        na = {n.get("net_id", "") for n in sa.get("nets", [])}
        nb = {n.get("net_id", "") for n in sb.get("nets", [])}
        return {
            "a_rev": a_rev, "b_rev": b_rev,
            "components_added": sorted(cb.keys() - ca.keys()),
            "components_removed": sorted(ca.keys() - cb.keys()),
            "components_moved": moved,
            "nets_added": sorted(nb - na),
            "nets_removed": sorted(na - nb),
            "board_size": {"a": sa.get("board_size"), "b": sb.get("board_size")},
        }

    # ---------------------------------------------------------------- persistance
    def default_path(self) -> Path:
        """Chemin de persistance standard : data/projects/<project_id>/versions.json."""
        return DATA_ROOT / (self.project_id or "default") / "versions.json"

    def persist(self, path: str | None = None) -> Path:
        """Sérialise l'historique complet en JSON (défaut : data/projects/...)."""
        target = Path(path) if path else self.default_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "project_id": self.project_id,
            "next_rev": self._next_rev,
            "current_branch": self._current_branch,
            "branches": [b.to_dict() for b in self._branches.values()],
            "revisions": [r.to_dict(include_snapshot=True) for r in self.list()],
        }
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        log.info("versioning persisté -> %s (%d révisions)", target, len(self._revisions))
        return target

    @classmethod
    def load(cls, path: str) -> DesignVersioning:
        """Recharge un historique persisté (classmethod)."""
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        versioning = cls(project_id=str(payload.get("project_id", "") or ""))
        versioning._next_rev = int(payload.get("next_rev", 1) or 1)
        versioning._current_branch = str(payload.get("current_branch", "main") or "main")
        versioning._branches = {
            b["name"]: Branch.from_dict(b) for b in payload.get("branches", [])
        } or {"main": Branch(name="main")}
        for raw in payload.get("revisions", []):
            revision = Revision.from_dict(raw)
            versioning._revisions[revision.rev] = revision
        return versioning
