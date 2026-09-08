"""ProposerLLM — propositions de modification (LLM ou heuristique centroïde)."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from shared.utilities import get_logger
from services.ai_engine.llm_orchestrator.orchestrator import LLMOrchestrator

log = get_logger("ai_engine.opt.proposer")


@dataclass
class Proposal:
    """Proposition de modification appliquable à un DesignGraph."""

    kind: str                     # "move_component" | "rotate" | "swap"
    params: Dict[str, Any] = field(default_factory=dict)
    rationale: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {"kind": self.kind, "params": self.params,
                "rationale": self.rationale}


def _net_degree(graph) -> Dict[str, int]:  # noqa: ANN001
    """Nombre de nets par composant."""
    degree: Dict[str, int] = {ref: 0 for ref in graph.components}
    for net in graph.nets.values():
        refs = {str(pin[0]) for pin in (getattr(net, "pins", []) or [])
                if isinstance(pin, (list, tuple)) and len(pin) >= 2}
        for ref in refs:
            degree[ref] = degree.get(ref, 0) + 1
    return degree


def _neighbor_centroid(graph, ref: str) -> Optional[Tuple[float, float]]:  # noqa: ANN001
    """Centroïde des composants connectés à `ref` (via nets/pins)."""
    xs, ys = [], []
    for net in graph.nets.values():
        pins = getattr(net, "pins", []) or []
        refs = {str(pin[0]) for pin in pins
                if isinstance(pin, (list, tuple)) and len(pin) >= 2}
        if ref not in refs:
            continue
        for other in refs:
            if other == ref:
                continue
            comp = graph.components.get(other)
            if comp is not None:
                xs.append(comp.x)
                ys.append(comp.y)
    if not xs:
        return None
    return sum(xs) / len(xs), sum(ys) / len(ys)


def _nets_of(graph, ref: str) -> List[str]:  # noqa: ANN001
    """Identifiants des nets contenant `ref`."""
    out = []
    for net_id, net in graph.nets.items():
        for pin in (getattr(net, "pins", []) or []):
            if isinstance(pin, (list, tuple)) and len(pin) >= 2 and str(pin[0]) == ref:
                out.append(str(net_id))
                break
    return out


def _hpwl(net, comps) -> float:  # noqa: ANN001
    """HPWL d'un net sur les positions des composants de ses pins."""
    xs, ys = [], []
    for pin in (getattr(net, "pins", []) or []):
        comp = comps.get(str(pin[0])) if isinstance(pin, (list, tuple)) else None
        if comp is not None:
            xs.append(comp.x)
            ys.append(comp.y)
    if len(xs) < 2:
        return 0.0
    return (max(xs) - min(xs)) + (max(ys) - min(ys))


def _estimate_delta_hpwl(graph, ref: str, dx: float, dy: float) -> float:  # noqa: ANN001
    """Δ HPWL estimé du déplacement (dx, dy) de `ref` (sur ses nets)."""
    comp = graph.components.get(ref)
    if comp is None or (dx == 0 and dy == 0):
        return 0.0
    delta = 0.0
    for net_id in _nets_of(graph, ref):
        net = graph.nets.get(net_id)
        if net is None:
            continue
        before = _hpwl(net, graph.components)
        ghost = dict(graph.components)
        ghost[ref] = _Ghost(comp.x + dx, comp.y + dy)
        delta += _hpwl(net, ghost) - before
    return delta


class _Ghost:
    """Composant fantôme (position seule) pour l'estimation Δ HPWL."""

    def __init__(self, x: float, y: float) -> None:
        self.x, self.y = x, y


def _heuristic_proposals(graph, k: int) -> List[Proposal]:  # noqa: ANN001
    """Heuristique greedy : déplace les composants vers le centroïde de leurs
    connexions (calculé depuis pins/nets), triés par GAIN HPWL estimé.

    Chaque composant est candidat (hub ou non) ; seuls les déplacements qui
    réduisent le HPWL sont proposés, les meilleurs d'abord.
    """
    degree = _net_degree(graph)
    scored: List[tuple[float, str, int, float, float]] = []
    for ref, deg in degree.items():
        comp = graph.components.get(ref)
        if comp is None:
            continue
        centroid = _neighbor_centroid(graph, ref)
        if centroid is None:
            continue
        dx = round(max(-2.0, min(2.0, (centroid[0] - comp.x) / 2.0)), 2)
        dy = round(max(-2.0, min(2.0, (centroid[1] - comp.y) / 2.0)), 2)
        if abs(dx) < 0.25 and abs(dy) < 0.25:
            continue
        delta = _estimate_delta_hpwl(graph, ref, dx, dy)
        if delta < -1e-9:
            scored.append((delta, ref, deg, dx, dy))
    scored.sort(key=lambda t: t[0])  # gain le plus négatif d'abord
    return [
        Proposal(kind="move_component",
                 params={"ref": ref, "dx": dx, "dy": dy},
                 rationale=(f"{ref} ({deg} nets) : ΔHPWL estimé {delta:+.2f} mm "
                            f"— rapprochement du centroïde (dx={dx}, dy={dy})"))
        for delta, ref, deg, dx, dy in scored[:max(1, k)]
    ]


class ProposerLLM:
    """Propose des modifications : LLM si dispo, sinon heuristique centroïde."""

    def __init__(self, orchestrator: Optional[LLMOrchestrator] = None) -> None:
        self.orchestrator = orchestrator

    def propose(self, graph,  # noqa: ANN001
                eval_result,  # noqa: ANN001 — EvalResult
                k: int = 3) -> List[Proposal]:
        """Retourne jusqu'à k propositions ordonnées."""
        heur = _heuristic_proposals(graph, k)
        if self.orchestrator is None:
            return heur
        try:
            llm_props = self._llm_propose(graph, eval_result, k)
            if llm_props:
                # mixte : meilleures heuristiques d'abord, LLM en appoint
                merged = heur[:max(1, k // 2)] + llm_props
                return merged[:k]
        except Exception as exc:
            log.warning("proposition LLM échouée (%s) → heuristique", exc)
        return heur

    def _llm_propose(self, graph, eval_result, k: int) -> List[Proposal]:  # noqa: ANN001
        assert self.orchestrator is not None
        comps = {ref: {"x": c.x, "y": c.y, "nets": _net_degree(graph).get(ref, 0)}
                 for ref, c in list(graph.components.items())[:30]}
        raw = self.orchestrator.ask(
            question=(
                f"Breakdown: {json.dumps(eval_result.breakdown)}\n"
                f"Composants: {json.dumps(comps)}\n"
                f"Propose {k} améliorations de placement (JSON liste) : "
                '[{"kind": "move_component"|"rotate"|"swap", "params": {...}, '
                '"rationale": "..."}]. move params: {ref, dx, dy} ; rotate: '
                "{ref, rot_delta} ; swap: {ref_a, ref_b}."
            ),
            system=(
                "Tu es l'agent PLACEMENT. Tu proposes des déplacements précis "
                "qui réduisent la longueur de fil et les violations."
            ),
            temperature=0.2,
        )
        txt = raw.strip()
        if txt.startswith("```"):
            txt = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", txt)
        data = json.loads(txt)
        out: List[Proposal] = []
        for item in data if isinstance(data, list) else []:
            kind = str(item.get("kind", "move_component"))
            if kind not in ("move_component", "rotate", "swap"):
                continue
            out.append(Proposal(kind=kind, params=dict(item.get("params", {})),
                                rationale=str(item.get("rationale", ""))))
        return out[:k]
