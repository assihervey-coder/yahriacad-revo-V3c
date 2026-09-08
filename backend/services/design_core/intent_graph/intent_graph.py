"""IntentGraph — arbre d'intentions utilisateur/agents (le POURQUOI du design)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

INTENT_KINDS = ("functional", "constraint", "quality", "business")
INTENT_STATUSES = ("open", "in_progress", "done", "rejected")


@dataclass
class Intent:
    """Intention capturée : quoi réaliser, à quelle priorité, dans quel état."""

    id: str
    description: str
    kind: str = "functional"       # functional | constraint | quality | business
    priority: int = 5              # 1 = plus haute priorité
    parent_id: Optional[str] = None
    children: List[str] = field(default_factory=list)
    status: str = "open"           # open | in_progress | done | rejected
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id, "description": self.description, "kind": self.kind,
            "priority": self.priority, "parent_id": self.parent_id,
            "children": list(self.children), "status": self.status,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Intent":
        return cls(
            id=str(d.get("id", "I0")),
            description=str(d.get("description", "")),
            kind=str(d.get("kind", "functional")),
            priority=int(d.get("priority", 5) or 5),
            parent_id=d.get("parent_id"),
            children=[str(c) for c in d.get("children", [])],
            status=str(d.get("status", "open")),
            metadata=dict(d.get("metadata", {})),
        )


class IntentGraph:
    """Graphe hiérarchique d'intentions — partagé par LLM, RL, router et UI."""

    def __init__(self, project_id: str = "") -> None:
        self.project_id = project_id
        self._intents: Dict[str, Intent] = {}

    # ------------------------------------------------------------------ mutations
    def add_intent(
        self,
        description: str,
        kind: str = "functional",
        priority: int = 5,
        parent_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Intent:
        """Ajoute une intention (ID auto "I1", "I2"...) et la rattache à son parent."""
        if kind not in INTENT_KINDS:
            kind = "functional"
        i = 1
        while f"I{i}" in self._intents:
            i += 1
        intent = Intent(
            id=f"I{i}", description=description, kind=kind, priority=int(priority),
            parent_id=parent_id, metadata=dict(metadata or {}),
        )
        self._intents[intent.id] = intent
        if parent_id is not None:
            parent = self.get(parent_id)          # KeyError si parent inconnu
            if intent.id not in parent.children:
                parent.children.append(intent.id)
        return intent

    def get(self, intent_id: str) -> Intent:
        """Renvoie l'intention `intent_id`, KeyError explicite sinon."""
        try:
            return self._intents[intent_id]
        except KeyError:
            raise KeyError(f"intention '{intent_id}' absente de l'intent graph") from None

    def mark(self, intent_id: str, status: str) -> Intent:
        """Change le statut d'une intention (open|in_progress|done|rejected)."""
        if status not in INTENT_STATUSES:
            raise ValueError(f"statut invalide: {status} (attendu parmi {INTENT_STATUSES})")
        intent = self.get(intent_id)
        intent.status = status
        return intent

    # -------------------------------------------------------------------- lecture
    def root(self) -> Optional[Intent]:
        """Racine = intention sans parent la plus prioritaire (None si vide)."""
        roots = [i for i in self._intents.values() if i.parent_id is None]
        if not roots:
            return None
        return min(roots, key=lambda i: (i.priority, i.id))

    def intents(self) -> List[Intent]:
        """Toutes les intentions (ordre d'insertion)."""
        return list(self._intents.values())

    def by_priority(self) -> List[Intent]:
        """Intentions triées par priorité croissante (1 = plus critique)."""
        return sorted(self._intents.values(), key=lambda i: (i.priority, i.id))

    def stats(self) -> Dict[str, Any]:
        """Synthèse : total, par kind, par statut."""
        by_kind: Dict[str, int] = {}
        by_status: Dict[str, int] = {}
        for i in self._intents.values():
            by_kind[i.kind] = by_kind.get(i.kind, 0) + 1
            by_status[i.status] = by_status.get(i.status, 0) + 1
        return {"total": len(self._intents), "by_kind": by_kind, "by_status": by_status}

    # ------------------------------------------------------------- sérialisation
    def to_dict(self) -> Dict[str, Any]:
        return {
            "project_id": self.project_id,
            "intents": [i.to_dict() for i in self._intents.values()],
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "IntentGraph":
        ig = cls(project_id=str(d.get("project_id", "") or ""))
        for raw in d.get("intents", []):
            intent = Intent.from_dict(raw)
            ig._intents[intent.id] = intent
        return ig
