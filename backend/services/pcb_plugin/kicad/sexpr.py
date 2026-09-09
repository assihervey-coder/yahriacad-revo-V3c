"""Mini parseur s-expression pour KiCad — tokenizer maison, zéro dépendance."""
from __future__ import annotations

from collections.abc import Iterator
from typing import Any

Node = str | int | float | list["Node"]

_WS = " \t\r\n"
_DELIMS = _WS + '()"'


class SExprError(ValueError):
    """S-expression malformée."""


def _atom(raw: str) -> Node:
    """Convertit un atome brut en int/float/str."""
    try:
        return int(raw)
    except ValueError:
        pass
    try:
        return float(raw)
    except ValueError:
        return raw


def _tokenize(text: str) -> Iterator[tuple[str, Any]]:
    """Génère ('(' | ')') ou ('atom', valeur) — gère les chaînes quotées avec échappements."""
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c in _WS:
            i += 1
        elif c == "(":
            yield ("(", None)
            i += 1
        elif c == ")":
            yield (")", None)
            i += 1
        elif c == '"':
            i += 1
            buf: list[str] = []
            while i < n and text[i] != '"':
                if text[i] == "\\" and i + 1 < n:
                    buf.append(text[i + 1])
                    i += 2
                else:
                    buf.append(text[i])
                    i += 1
            if i >= n:
                raise SExprError("chaîne quotée non terminée")
            i += 1  # guillemet fermant
            yield ("atom", "".join(buf))
        else:
            j = i
            while j < n and text[j] not in _DELIMS:
                j += 1
            yield ("atom", text[i:j])
            i = j


class SExprParser:
    """Parse un fichier s-expression KiCad en listes Python imbriquées."""

    def __init__(self, text: str) -> None:
        self.text = text

    def parse(self) -> list[Node]:
        """Retourne la liste racine (ex: [('kicad_pcb', 'version', ...)])."""
        root: list[Node] = []
        stack: list[list[Node]] = [root]
        for kind, val in _tokenize(self.text):
            if kind == "(":
                new: list[Node] = []
                stack[-1].append(new)
                stack.append(new)
            elif kind == ")":
                if len(stack) == 1:
                    raise SExprError("parenthèse fermante inattendue")
                stack.pop()
            else:
                stack[-1].append(_atom(val))
        if len(stack) != 1:
            raise SExprError("parenthèses non fermées")
        return root


def parse(text: str) -> list[Node]:
    """Raccourci : SExprParser(text).parse()."""
    return SExprParser(text).parse()


def find(node: Any, key: str) -> list[Any] | None:
    """Premier sous-nœud liste dont la tête vaut `key`."""
    if not isinstance(node, list):
        return None
    for child in node:
        if isinstance(child, list) and child and child[0] == key:
            return child
    return None


def find_all(node: Any, key: str) -> list[list[Any]]:
    """Tous les sous-nœuds listes dont la tête vaut `key`."""
    out: list[list[Any]] = []
    if isinstance(node, list):
        for child in node:
            if isinstance(child, list) and child and child[0] == key:
                out.append(child)
    return out


def atom(node: Any, key: str, default: Any = None) -> Any:
    """Valeur qui suit `key` dans une liste : (at 10 20) → atom(node, 'at', 1) == 10."""
    child = find(node, key)
    if child is not None and len(child) > 1:
        return child[1]
    return default


def as_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def as_str(v: Any, default: str = "") -> str:
    return default if v is None else str(v)
