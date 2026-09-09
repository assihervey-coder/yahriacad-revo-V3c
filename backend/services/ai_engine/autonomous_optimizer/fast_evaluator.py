"""FastEvaluator — évaluation rapide d'un DesignGraph (score, breakdown)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from shared.utilities import get_logger

log = get_logger("ai_engine.opt.fast_evaluator")


@dataclass
class EvalResult:
    """Résultat d'évaluation — score : plus haut = mieux."""

    score: float
    breakdown: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"score": self.score, "breakdown": self.breakdown}


def board_extents(graph) -> tuple[float, float]:  # noqa: ANN001
    """Extents de carte déduits (ou fournis par le graphe)."""
    try:
        from services.ai_engine.self_verifier.deterministic import _board_extents
        ext = _board_extents(graph)
        if ext:
            return ext
    except Exception:
        pass
    comps = list(getattr(graph, "components", {}).values())
    if not comps:
        return 60.0, 40.0
    xs = [c.x for c in comps]
    ys = [c.y for c in comps]
    return max(60.0, (max(xs) - min(xs)) * 1.2), max(40.0, (max(ys) - min(ys)) * 1.2)


def effective_wire_length(graph) -> tuple[float, float]:  # noqa: ANN001
    """(longueur routée + HPWL des nets non routés, hpwl seul).

    `graph.total_wire_length()` ne compte que les nets ROUTÉS (path) ;
    pour l'optimisation de placement on ajoute le HPWL (rectiligne) des
    nets non routés, calculé sur les positions des composants connectés.
    """
    routed_len = 0.0
    try:
        routed_len = float(graph.total_wire_length())
    except Exception:
        routed_len = 0.0

    hpwl = 0.0
    comps = getattr(graph, "components", {}) or {}
    for net in (getattr(graph, "nets", {}) or {}).values():
        if getattr(net, "routed", False) and getattr(net, "path", None) is not None:
            continue
        xs: list[float] = []
        ys: list[float] = []
        for pin in (getattr(net, "pins", None) or []):
            try:
                ref = str(pin[0])
            except (TypeError, IndexError):
                continue
            comp = comps.get(ref)
            if comp is not None:
                xs.append(float(comp.x))
                ys.append(float(comp.y))
        if len(xs) >= 2:
            hpwl += (max(xs) - min(xs)) + (max(ys) - min(ys))
    return routed_len + hpwl, hpwl


class FastEvaluator:
    """Score = −wl_normalisée − 10·violations − thermal_proxy − 0.01·cost.

    Utilise ConstraintEngine (design_core) si fourni pour compter les
    violations ; sinon compte les violations déterministes de base.
    La longueur de fil effective = routée + HPWL des nets non routés.
    """

    VIOLATION_WEIGHT = 10.0

    def __init__(self, constraint_engine=None) -> None:  # noqa: ANN001
        self.constraint_engine = constraint_engine

    # ------------------------------------------------------------- evaluate
    def evaluate(self, graph) -> EvalResult:  # noqa: ANN001
        """Évalue un graphe (rapide, déterministe)."""
        components = dict(getattr(graph, "components", {}) or {})
        nets = dict(getattr(graph, "nets", {}) or {})
        board_w, board_h = board_extents(graph)
        board_area = max(1.0, board_w * board_h)

        # wire length (routée + HPWL) + normalisation
        wl, hpwl = effective_wire_length(graph)
        n_nets = max(1, len(nets))
        wl_norm = wl / (10.0 * n_nets)

        # violations
        violations = self._violations(graph)

        # thermal proxy : densité de puissance locale max
        thermal = 0.0
        for comp in components.values():
            power = float(getattr(comp, "power_w", 0.0) or 0.0)
            if power <= 0.05:
                continue
            w, h = comp.bbox
            density = power / max(1e-3, (w / 10.0) * (h / 10.0))
            thermal = max(thermal, min(10.0, density))

        # cost
        try:
            cost = float(graph.cost_usd())
        except Exception:
            cost = sum(float(getattr(c, "price_usd", 0.0) or 0.0)
                       for c in components.values())

        score = -wl_norm - self.VIOLATION_WEIGHT * violations - thermal - 0.01 * cost
        breakdown = {
            "wire_length": round(wl, 3),
            "hpwl": round(hpwl, 3),
            "wire_length_norm": round(wl_norm, 4),
            "violations": float(violations),
            "thermal_proxy": round(thermal, 4),
            "cost": round(cost, 4),
            "n_components": float(len(components)),
            "board_area": round(board_area, 2),
        }
        return EvalResult(score=round(score, 5), breakdown=breakdown)

    # ---------------------------------------------------------- violations
    def _violations(self, graph) -> float:  # noqa: ANN001
        """Nombre de violations via ConstraintEngine sinon checks internes."""
        if self.constraint_engine is not None:
            for meth in ("check", "evaluate", "violations", "validate"):
                fn = getattr(self.constraint_engine, meth, None)
                if fn is None:
                    continue
                try:
                    result = fn(graph)
                    if isinstance(result, (int, float)):
                        return float(result)
                    if isinstance(result, list):
                        return float(len(result))
                    if isinstance(result, dict):
                        for key in ("violations", "n_violations", "count"):
                            if key in result:
                                return float(result[key])
                    # design_core.ConstraintReport (violations, checked)
                    viol = getattr(result, "violations", None)
                    if viol is not None:
                        return float(len(viol))
                except Exception as exc:
                    log.debug("constraint_engine.%s échoué: %s", meth, exc)
        # fallback : checks déterministes count
        try:
            from services.ai_engine.self_verifier.deterministic import check_deterministic
            return float(len(check_deterministic(graph)))
        except Exception:
            return 0.0
