"""WorldModelProposer — propositions accélérées par le world model (MPC).

Lien manquant entre le cerveau décisionnel (RL) et l'optimiseur autonome :
au lieu d'évaluer réellement chaque mouvement (évaluateur complet), ce proposer
  1. génère un pool de candidats (moves vers le centroïde des connexions),
  2. les FAIT IMAGINER par le WorldModel (dynamique d'ensemble + récompense
     apprise, rollout depth=2, MPC greedy),
  3. ne transmet à l'évaluateur réel que le top-k.

Coût : O(pool × depth) prédictions numpy (~µs chacune) au lieu d'autant
d'évaluations complètes. Les propositions restent des `Proposal` standard :
le keeper valide toujours sur l'évaluateur réel (sécurité inchangée).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from shared.utilities import get_logger

from services.ai_engine.autonomous_optimizer.fast_evaluator import board_extents
from services.ai_engine.autonomous_optimizer.proposer_llm import Proposal
from services.ai_engine.rl_agent.action_space import PlacementAction, PlacementActionKind
from services.ai_engine.rl_agent.world_model import WorldModel, state_from_graph
from services.router.topological import component_nets, net_pad_positions

log = get_logger("ai_engine.opt.world_proposer")


class WorldModelProposer:
    """Proposer « imagine-puis-propose » piloté par le world model."""

    def __init__(self, world_model: Optional[WorldModel] = None,
                 pool_size: int = 40, top_k: int = 4,
                 rollout_depth: int = 2, gamma: float = 0.95,
                 max_refs: int = 8) -> None:
        self.world_model = world_model or WorldModel()
        self.pool_size = int(pool_size)
        self.top_k = int(top_k)
        self.rollout_depth = int(rollout_depth)
        self.gamma = float(gamma)
        self.max_refs = int(max_refs)
        self.last_imagined: List[Dict[str, Any]] = []

    # ------------------------------------------------------------------ public
    def propose(self, graph,  # noqa: ANN001
                eval_result=None,  # noqa: ANN001 — compat interface proposers
                k: Optional[int] = None) -> List[Proposal]:
        """Top-k propositions classées par récompense imaginée."""
        top_k = self.top_k if k is None else int(k)
        refs = self._refs_by_degree(graph)
        if not refs:
            return []
        candidates = self._candidate_moves(graph, refs)
        if not candidates:
            return []

        state = state_from_graph(graph)
        scored = self.world_model.rollout(
            state, candidates, depth=self.rollout_depth, gamma=self.gamma)
        self.last_imagined = [
            {
                "ref": a.ref,
                "dx": a.dx,
                "dy": a.dy,
                "imagined_reward": round(v, 5),
                "uncertainty": round(
                    self.world_model.last_uncertainty.get("max_std", 0.0), 5),
            }
            for a, v in scored[:top_k]
        ]
        proposals: List[Proposal] = []
        for action, value in scored[:top_k]:
            if abs(action.dx) < 1e-9 and abs(action.dy) < 1e-9:
                continue
            proposals.append(Proposal(
                kind="move_component",
                params={"ref": action.ref, "dx": action.dx, "dy": action.dy},
                rationale=(f"world model : récompense imaginée {value:+.4f} "
                           f"(depth {self.rollout_depth}, "
                           f"σ {self.world_model.last_uncertainty.get('max_std', 0.0):.4f})"),
            ))
        log.info("world_proposer : %d candidats imaginés → %d propositions",
                 len(candidates), len(proposals))
        return proposals

    # ------------------------------------------------------------------ privé
    @staticmethod
    def _refs_by_degree(graph) -> List[str]:  # noqa: ANN001
        """Refs triés par degré de connexion décroissant (cap max_refs)."""
        degree: Dict[str, int] = {ref: 0 for ref in graph.components}
        for net in graph.nets.values():
            for ref, _pad in getattr(net, "pins", []) or []:
                if ref in degree:
                    degree[ref] += 1
        return sorted(degree, key=lambda r: degree[r], reverse=True)

    def _candidate_moves(self, graph, refs: List[str]) -> List[PlacementAction]:  # noqa: ANN001
        """Pool de moves vers le centroïde des pads des nets connectés."""
        board_w, board_h = board_extents(graph)
        actions: List[PlacementAction] = []
        steps = (0.5, 1.0, 2.0)
        for ref in refs[: self.max_refs]:
            comp = graph.components.get(ref)
            if comp is None:
                continue
            nets = component_nets(graph, ref)
            pad_pts: List[Any] = []
            for net in nets:
                pad_pts.extend(pos for _, pos in net_pad_positions(graph, net))
            if not pad_pts:
                continue
            cx = sum(p.x for p in pad_pts) / len(pad_pts)
            cy = sum(p.y for p in pad_pts) / len(pad_pts)
            direction_x = 1.0 if cx >= comp.x else -1.0
            direction_y = 1.0 if cy >= comp.y else -1.0
            for step in steps:
                dx = min(abs(cx - comp.x), step) * direction_x
                dy = min(abs(cy - comp.y), step) * direction_y
                if abs(dx) < 1e-9 and abs(dy) < 1e-9:
                    continue
                actions.append(PlacementAction(
                    kind=PlacementActionKind.MOVE, ref=ref, dx=dx, dy=dy))
            if len(actions) >= self.pool_size:
                break
        return actions[: self.pool_size]
