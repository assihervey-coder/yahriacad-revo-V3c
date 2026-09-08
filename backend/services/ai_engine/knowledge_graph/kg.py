"""KnowledgeGraph — nœuds/arêtes typés, requêtes, sérialisation JSON."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional

from shared.utilities import get_logger

log = get_logger("ai_engine.kg.base")


@dataclass
class Node:
    """Nœud du graphe (composant, règle, usine, interface...)."""

    id: str
    kind: str                       # "component" | "rule" | "factory" | ...
    props: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {"id": self.id, "kind": self.kind, "props": self.props}


@dataclass
class Edge:
    """Arête typée du graphe."""

    src: str
    dst: str
    relation: str                   # "pinout" | "compatible_footprint" | ...
    props: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {"src": self.src, "dst": self.dst,
                "relation": self.relation, "props": self.props}


class KnowledgeGraph:
    """Graphe de connaissance léger (dict/list), persistable en JSON."""

    def __init__(self) -> None:
        self.nodes: Dict[str, Node] = {}
        self.edges: List[Edge] = []
        self._edge_index: Dict[str, List[int]] = {}

    # ---------------------------------------------------------------- build
    def add_node(self, node_id: str, kind: str,
                 props: Optional[Dict[str, Any]] = None) -> Node:
        """Ajoute (ou met à jour) un nœud."""
        if node_id in self.nodes:
            self.nodes[node_id].props.update(props or {})
            return self.nodes[node_id]
        node = Node(id=node_id, kind=kind, props=props or {})
        self.nodes[node_id] = node
        return node

    def add_edge(self, src: str, dst: str, relation: str,
                 props: Optional[Dict[str, Any]] = None) -> Edge:
        """Ajoute une arête (anti-doublon simple sur (src,dst,relation))."""
        if not self.has_edge(src, dst, relation):
            edge = Edge(src=src, dst=dst, relation=relation, props=props or {})
            self._edge_index.setdefault(relation, []).append(len(self.edges))
            self.edges.append(edge)
            return edge
        return next(e for e in self.edges
                    if e.src == src and e.dst == dst and e.relation == relation)

    def has_edge(self, src: str, dst: str, relation: str) -> bool:
        return any(e.src == src and e.dst == dst and e.relation == relation
                   for e in self.edges)

    # --------------------------------------------------------------- query
    def query(self, kind: Optional[str] = None,
              relation: Optional[str] = None) -> List[Dict[str, Any]]:
        """Requête : nœuds par kind et/ou arêtes par relation.

        Si `relation` seul → retourne les arêtes correspondantes ;
        si `kind` seul → les nœuds ; les deux → les arêtes dont les
        extrémités matchent le kind.
        """
        if relation is not None:
            edges = [e.to_dict() for e in self.edges if e.relation == relation]
            if kind is None:
                return edges
            return [e for e in edges
                    if self.nodes.get(e["src"], Node("", "")).kind == kind
                    or self.nodes.get(e["dst"], Node("", "")).kind == kind]
        if kind is not None:
            return [n.to_dict() for n in self.nodes.values() if n.kind == kind]
        return [n.to_dict() for n in self.nodes.values()]

    def neighbors(self, node_id: str, relation: Optional[str] = None) -> List[str]:
        """Voisins d'un nœud (les deux sens), filtrés par relation."""
        out: List[str] = []
        for e in self.edges:
            if relation is not None and e.relation != relation:
                continue
            if e.src == node_id:
                out.append(e.dst)
            elif e.dst == node_id:
                out.append(e.src)
        return out

    # ---------------------------------------------------------- persistence
    def to_dict(self) -> Dict[str, Any]:
        """Sérialisation complète."""
        return {
            "nodes": [n.to_dict() for n in self.nodes.values()],
            "edges": [e.to_dict() for e in self.edges],
        }

    def from_dict(self, data: Dict[str, Any]) -> "KnowledgeGraph":
        """Charge un graphe depuis un dict (in-place)."""
        self.nodes, self.edges, self._edge_index = {}, [], {}
        for nd in data.get("nodes", []):
            self.add_node(nd["id"], nd.get("kind", "generic"), nd.get("props", {}))
        for ed in data.get("edges", []):
            self.add_edge(ed["src"], ed["dst"], ed["relation"], ed.get("props", {}))
        return self

    def save(self, path: str) -> None:
        """Sauvegarde JSON."""
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=1)

    def load(self, path: str) -> bool:
        """Chargement JSON — True si succès."""
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.from_dict(data)
            return True
        except (OSError, ValueError) as exc:
            log.warning("KG.load(%s) échoué: %s", path, exc)
            return False

    def __len__(self) -> int:
        return len(self.nodes)

    def iter_nodes(self) -> Iterable[Node]:
        return self.nodes.values()
