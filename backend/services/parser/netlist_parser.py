"""parse_netlist — importe une netlist KiCad (s-expression) ou JSON en DesignGraph.

Formats supportés (détection automatique) :
  1. s-expression KiCad simplifiée :
     (export (components (comp (ref "R1") (value "10k") (footprint "R_0603")) ...)
             (nets (net (code "1") (name "GND") (node (ref "R1") (pin "1")) ...)))
     — variante minimale acceptée : (netlist (nets (net ...)))
  2. JSON : {"components": [{"ref", "value", "footprint", "mpn"}...],
             "nets": [{"name"/"net_id", "pins"/"nodes": ...}...]}
"""
from __future__ import annotations

import json
import re
from collections.abc import Iterator
from typing import Any

from shared.utilities import get_logger, new_id

from services.design_core.design_graph.components import default_bbox_for_footprint
from services.design_core.design_graph.graph import DesignGraph

log = get_logger("parser.netlist")

SExprNode = str | list["SExprNode"]  # type: ignore[misc]


# ------------------------------------------------------------ s-expression ----
def _tokenize(text: str) -> Iterator[str]:
    """Tokenizer minimaliste : '(', ')', chaînes quotées (avec échappements), atomes."""
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c in " \t\r\n":
            i += 1
        elif c == "(":
            yield "("
            i += 1
        elif c == ")":
            yield ")"
            i += 1
        elif c == '"':
            j = i + 1
            buf: list[str] = []
            while j < n and text[j] != '"':
                if text[j] == "\\" and j + 1 < n:
                    buf.append(text[j + 1])
                    j += 2
                else:
                    buf.append(text[j])
                    j += 1
            yield "".join(buf)
            i = j + 1
        else:
            j = i
            while j < n and text[j] not in ' \t\r\n()"':
                j += 1
            yield text[i:j]
            i = j


def _parse_sexpr(text: str) -> list[Any]:
    """Parse une s-expression en arbre de listes Python (~lisp)."""
    stack: list[list[Any]] = [[]]
    for token in _tokenize(text):
        if token == "(":
            stack.append([])
        elif token == ")":
            top = stack.pop()
            if not stack:                       # tolérance : racine multiple
                stack.append([])
            stack[-1].append(top)
        else:
            stack[-1].append(token)
    return stack[0]


def _is_named(node: Any, tag: str) -> bool:
    return isinstance(node, list) and bool(node) and node[0] == tag


def _find_all(node: Any, tag: str, found: list[Any] | None = None) -> list[Any]:
    """Tous les sous-arbres nommés `tag` (récursif)."""
    if found is None:
        found = []
    if isinstance(node, list):
        for child in node:
            if _is_named(child, tag):
                found.append(child)
            _find_all(child, tag, found)
    return found


def _find_first(node: Any, tag: str) -> Any | None:
    """Premier sous-arbre nommé `tag` (récursif)."""
    if isinstance(node, list):
        for child in node:
            if _is_named(child, tag):
                return child
            hit = _find_first(child, tag)
            if hit is not None:
                return hit
    return None


def _value(node: Any, key: str) -> str | None:
    """Valeur texte d'un sous-nœud (key "valeur") directement sous `node`."""
    if not isinstance(node, list):
        return None
    for child in node[1:]:
        if _is_named(child, key) and len(child) >= 2 and isinstance(child[1], str):
            return child[1]
    return None


def _bbox_from_kicad_footprint(fp: str) -> tuple[float, float]:
    """Bbox (w, h) déduite d'une empreinte KiCad type 'Resistor_SMD:R_0603_1608Metric'."""
    return default_bbox_for_footprint(fp)


def _parse_sexpr_netlist(text: str) -> DesignGraph:
    """Parse la s-expression KiCad et construit le DesignGraph."""
    tree = _parse_sexpr(text)
    graph = DesignGraph(project_id=new_id("import"), name="netlist-import")

    # --- composants : section (components (comp ...)) sinon déduits des nodes
    for comp in _find_all(tree, "comp"):
        ref = _value(comp, "ref")
        if not ref:
            continue
        footprint = _value(comp, "footprint") or ""
        mpn = ""
        for prop in _find_all(comp, "property"):
            if (_value(prop, "name") or "").upper() in ("MPN", "PART NUMBER", "MANUFACTURER PN"):
                mpn = _value(prop, "value") or ""
        graph.add_component(
            ref=ref, value=_value(comp, "value") or "", footprint=footprint, mpn=mpn,
            bbox=_bbox_from_kicad_footprint(footprint),
        )

    # --- nets : (nets (net (code "..") (name "..") (node (ref "..") (pin ".."))))
    for i, net_node in enumerate(_find_all(tree, "net"), start=1):
        name = _value(net_node, "name") or ""
        code = _value(net_node, "code") or str(i)
        net_id = re.sub(r"[^A-Za-z0-9_\-]", "_", name) if name else f"N{i}"
        if net_id in graph.nets:
            net_id = f"{net_id}_{code}"
        graph.add_net(net_id=net_id, name=name or net_id)
        for node in _find_all(net_node, "node"):
            ref = _value(node, "ref")
            pin = _value(node, "pin") or "1"
            if not ref:
                continue
            if ref not in graph.components:
                graph.add_component(ref=ref)     # composant implicite (netlist minimal)
            graph.connect(ref, pin, net_id)

    if not graph.components and not graph.nets:
        log.warning("netlist s-expr sans composants ni nets reconnus")
    return graph


# ------------------------------------------------------------------- JSON -----
def _pins_of(net: dict[str, Any]) -> list[tuple[str, str]]:
    """Extrait les pins d'un net JSON sous toutes les formes tolérées."""
    pins: list[tuple[str, str]] = []
    raw = net.get("pins", net.get("nodes", net.get("connections", [])))
    for entry in raw or []:
        if isinstance(entry, dict):
            pins.append((str(entry.get("ref", "")), str(entry.get("pin", entry.get("pad", "1")))))
        elif isinstance(entry, (list, tuple)) and len(entry) >= 2:
            pins.append((str(entry[0]), str(entry[1])))
    return [(ref, pad) for ref, pad in pins if ref]


def _parse_json_netlist(data: dict[str, Any]) -> DesignGraph:
    """Parse le format JSON {"components": [...], "nets": [...]}."""
    graph = DesignGraph(
        project_id=str(data.get("project_id") or new_id("import")),
        name=str(data.get("name", "netlist-import") or "netlist-import"),
    )
    for comp in data.get("components", []):
        if not isinstance(comp, dict) or "ref" not in comp:
            continue
        footprint = str(comp.get("footprint", "") or "")
        graph.add_component(
            ref=str(comp["ref"]),
            value=str(comp.get("value", "") or ""),
            footprint=footprint,
            mpn=str(comp.get("mpn", "") or ""),
            bbox=_bbox_from_kicad_footprint(footprint),
        )
    for i, net in enumerate(data.get("nets", []), start=1):
        if not isinstance(net, dict):
            continue
        net_id = str(net.get("net_id", net.get("name", f"N{i}")) or f"N{i}")
        name = str(net.get("name", net_id) or net_id)
        graph.add_net(net_id=net_id, name=name, class_name=str(net.get("class_name", "default") or "default"))
        for ref, pad in _pins_of(net):
            if ref not in graph.components:
                graph.add_component(ref=ref)     # composant implicite
            graph.connect(ref, pad, net_id)
    return graph


# ------------------------------------------------------------------ public ----
def parse_netlist(text: str) -> DesignGraph:
    """Point d'entrée : détecte le format (s-expr ou JSON) et retourne un DesignGraph."""
    stripped = (text or "").strip()
    if not stripped:
        raise ValueError("netlist vide : impossible de parser")
    if stripped.startswith("{"):
        return _parse_json_netlist(json.loads(stripped))
    if stripped.startswith("("):
        return _parse_sexpr_netlist(stripped)
    raise ValueError("format de netlist non reconnu (attendu: s-expression ou JSON)")
