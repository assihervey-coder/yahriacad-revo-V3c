"""AutonomousOptimizer — boucle proposer → appliquer → évaluer → keeper.

Ne modifie JAMAIS le graphe d'entrée : travaille sur des copies et
retourne un NOUVEAU DesignGraph via OptimizationResult.best_graph.
Émet EventTypes.OPTIMIZATION_ITERATION à chaque itération.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from shared.utilities import get_logger
from shared.events import EventTypes, make_event
from services.ai_engine._event_helpers import publish_nowait
from services.ai_engine.autonomous_optimizer.fast_evaluator import EvalResult, FastEvaluator
from services.ai_engine.autonomous_optimizer.keeper_logic import Keeper
from services.ai_engine.autonomous_optimizer.proposer_llm import Proposal, ProposerLLM

log = get_logger("ai_engine.opt.optimizer")


@dataclass
class OptimizationResult:
    """Résultat d'une session d'optimisation autonome."""

    best_graph: Any                    # DesignGraph (nouvelle instance)
    best_score: float
    history: List[Dict[str, Any]] = field(default_factory=list)
    iterations: int = 0
    proposals_applied: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "best_score": self.best_score,
            "iterations": self.iterations,
            "proposals_applied": self.proposals_applied,
            "history": self.history[-20:],
        }


class AutonomousOptimizer:
    """Optimiseur autonome : combine des proposers et un keeper conservatif."""

    def __init__(self, fast_evaluator: FastEvaluator,
                 proposers: List[Any],  # List[ProposerLLM|RLOptimizer|...]
                 keeper: Optional[Keeper] = None,
                 emit_events: bool = True) -> None:
        self.evaluator = fast_evaluator
        if not proposers:
            raise ValueError("AutonomousOptimizer requiert au moins un proposer")
        self.proposers = list(proposers)
        self.keeper = keeper or Keeper()
        self.emit_events = emit_events

    # -------------------------------------------------------------- optimize
    def optimize(self, graph,  # noqa: ANN001
                 max_iters: int = 20,
                 objective: str = "balanced") -> OptimizationResult:
        """Boucle d'optimisation — retourne un NOUVEAU DesignGraph amélioré."""
        base = graph.copy()                      # graphe courant de la boucle
        best_graph = base.copy()
        try:
            best_score = self._score(self.evaluator.evaluate(base), objective)
        except Exception as exc:
            log.error("évaluation initiale impossible: %s", exc)
            raise

        history: List[Dict[str, Any]] = [{
            "iter": 0, "score": best_score, "applied": 0, "event": "init"}]
        proposals_applied = 0

        for it in range(1, max_iters + 1):
            eval_res = self.evaluator.evaluate(base)
            incumbent_score = self._score(eval_res, objective)

            # collecte de toutes les propositions de tous les proposers
            candidates: List[tuple[float, Proposal, Any]] = []
            for proposer in self.proposers:
                for proposal in self._safe_propose(proposer, base, eval_res):
                    cand = self._apply_proposal(base, proposal)
                    if cand is None:
                        continue
                    try:
                        cand_eval = self.evaluator.evaluate(cand)
                    except Exception as exc:
                        log.warning("évaluation candidate échouée: %s", exc)
                        continue
                    candidates.append(
                        (self._score(cand_eval, objective), proposal, cand))

            if not candidates:
                history.append({"iter": it, "score": round(incumbent_score, 5),
                                "event": "no_proposals"})
                self._emit(it, incumbent_score, None, kept=False)
                continue

            # le keeper tranche sur la MEILLEURE candidate (rollback sinon)
            candidates.sort(key=lambda t: t[0], reverse=True)
            cand_score, best_proposal, best_cand = candidates[0]
            if self.keeper.keep(cand_score, incumbent_score):
                base = best_cand                     # accepte
                proposals_applied += 1
                if cand_score > best_score:
                    best_score = cand_score
                    best_graph = best_cand.copy()
                history.append({
                    "iter": it, "score": round(cand_score, 5),
                    "applied": proposals_applied,
                    "proposal": best_proposal.to_dict(),
                    "event": "kept", "n_candidates": len(candidates),
                })
                self._emit(it, cand_score, best_proposal, kept=True)
            else:
                history.append({
                    "iter": it, "score": round(incumbent_score, 5),
                    "best_candidate": round(cand_score, 5),
                    "proposal": best_proposal.to_dict(),
                    "event": "rejected", "n_candidates": len(candidates)})
                self._emit(it, cand_score, best_proposal, kept=False)

        # garantie finale : best_graph est une copie neuve, jamais l'entrée
        return OptimizationResult(
            best_graph=best_graph,
            best_score=round(best_score, 5),
            history=history,
            iterations=max_iters,
            proposals_applied=proposals_applied,
        )

    # ------------------------------------------------------------- internals
    def _score(self, eval_result: EvalResult, objective: str) -> float:
        """Re-pondère le score selon l'objectif demandé."""
        b = eval_result.breakdown
        if objective == "cost":
            return -0.01 * b.get("cost", 0.0) - 10.0 * b.get("violations", 0.0)
        if objective == "thermal":
            return (-b.get("thermal_proxy", 0.0)
                    - 10.0 * b.get("violations", 0.0))
        if objective == "wire_length":
            return (-b.get("wire_length_norm", 0.0)
                    - 10.0 * b.get("violations", 0.0))
        return eval_result.score  # balanced

    @staticmethod
    def _safe_propose(proposer, graph, eval_res) -> List[Proposal]:  # noqa: ANN001
        try:
            return list(proposer.propose(graph, eval_res))
        except Exception as exc:
            log.warning("proposer %s a échoué: %s", type(proposer).__name__, exc)
            return []

    @staticmethod
    def _apply_proposal(graph, proposal: Proposal):  # noqa: ANN001
        """Applique une proposition sur une COPIE — None si non applicable."""
        try:
            cand = graph.copy()
            kind, p = proposal.kind, proposal.params
            if kind == "move_component":
                ref = str(p.get("ref", ""))
                if ref not in cand.components:
                    return None
                comp = cand.components[ref]
                if "x" in p and "y" in p:
                    cand.place(ref, float(p["x"]), float(p["y"]))
                else:
                    cand.place(ref, comp.x + float(p.get("dx", 0.0)),
                               comp.y + float(p.get("dy", 0.0)))
            elif kind == "rotate":
                ref = str(p.get("ref", ""))
                if ref not in cand.components:
                    return None
                comp = cand.components[ref]
                rot_delta = float(p.get("rot_delta", 90.0))
                cand.place(ref, comp.x, comp.y,
                           rotation=(comp.rotation + rot_delta) % 360)
            elif kind == "swap":
                ra, rb = str(p.get("ref_a", "")), str(p.get("ref_b", ""))
                if ra not in cand.components or rb not in cand.components:
                    return None
                ca, cb = cand.components[ra], cand.components[rb]
                ax, ay, bx, by = ca.x, ca.y, cb.x, cb.y
                cand.place(ra, bx, by)
                cand.place(rb, ax, ay)
            else:
                return None
            return cand
        except Exception as exc:
            log.warning("application de proposition échouée: %s", exc)
            return None

    def _emit(self, it: int, score: float, proposal: Optional[Proposal],
              kept: bool) -> None:
        if not self.emit_events:
            return
        try:
            publish_nowait(make_event(
                EventTypes.OPTIMIZATION_ITERATION,
                payload={
                    "iteration": it, "score": round(score, 5), "kept": kept,
                    "proposal": proposal.to_dict() if proposal else None,
                },
                source="ai_engine.optimizer",
            ))
        except Exception as exc:
            log.debug("émission OPTIMIZATION_ITERATION échouée: %s", exc)
