"""RLOptimizer — propositions d'actions via PolicyNetwork (fallback aléatoire biaisé)."""
from __future__ import annotations

import random
from typing import Optional, Tuple

import numpy as np

from shared.utilities import get_logger
from services.ai_engine.autonomous_optimizer.fast_evaluator import board_extents
from services.ai_engine.autonomous_optimizer.proposer_llm import Proposal
from services.ai_engine.rl_agent.action_space import ActionSpace, PlacementActionKind
from services.ai_engine.rl_agent.policy_network import PolicyNetwork
from services.ai_engine.rl_agent.world_model import state_from_graph

log = get_logger("ai_engine.opt.rl_optimizer")


class RLOptimizer:
    """Optimiseur décisionnel : PolicyNetwork sur features du graphe.

    Sans policy entraînée → mouvement aléatoire biaisé vers le centroïde
    des connexions (déterministe au tirage près, borne l'exploration).
    """

    def __init__(self, policy: Optional[PolicyNetwork] = None,
                 seed: int = 0) -> None:
        self.policy = policy
        self.rng = random.Random(seed)
        self._action_space: Optional[ActionSpace] = None
        self._last_refs: Tuple[str, ...] = ()

    def _ensure_action_space(self, refs: Tuple[str, ...]) -> ActionSpace:
        if self._action_space is None or self._last_refs != refs:
            self._action_space = ActionSpace(list(refs)).place(max_grid=40)
            if self.policy is not None and self.policy.n_actions != self._action_space.size():
                log.warning("policy n_actions=%d != espace=%d — policy ignorée",
                            self.policy.n_actions, self._action_space.size())
                self.policy = None
            self._last_refs = refs
        return self._action_space

    def propose(self, graph,  # noqa: ANN001
                eval_result=None,  # noqa: ANN001 — compat interface proposers
                k: int = 1) -> list:
        """Interface commune aux proposers — délègue à `step()`."""
        out = []
        for _ in range(max(1, k)):
            out.append(self.step(graph))
        return out

    def step(self, graph) -> Proposal:  # noqa: ANN001
        """Propose UNE action de placement pour le graphe courant."""
        refs = tuple(sorted(graph.components.keys()))
        if not refs:
            return Proposal(kind="move_component", params={},
                            rationale="aucun composant")
        space = self._ensure_action_space(refs)

        if self.policy is not None:
            try:
                state = state_from_graph(graph)
                feats = self.policy.feature_dim
                features = self._features(state, feats)
                idx = self.policy.select_action(features, greedy=False, eps=0.15)
                action = space.decode(idx)
                if action.kind == PlacementActionKind.MOVE:
                    return Proposal(kind="move_component",
                                    params={"ref": action.ref,
                                            "dx": action.dx, "dy": action.dy},
                                    rationale=f"RL policy (idx {idx})")
                if action.kind == PlacementActionKind.ROTATE:
                    return Proposal(kind="rotate",
                                    params={"ref": action.ref,
                                            "rot_delta": action.rot_delta},
                                    rationale=f"RL policy (idx {idx})")
                if action.kind == PlacementActionKind.SWAP:
                    other = self.rng.choice(refs)
                    return Proposal(kind="swap",
                                    params={"ref_a": action.ref, "ref_b": other},
                                    rationale=f"RL policy swap (idx {idx})")
                return self._centroid_biased(graph, refs)
            except Exception as exc:
                log.warning("policy step échoué (%s) → heuristique", exc)
        return self._centroid_biased(graph, refs)

    # ------------------------------------------------------------ internals
    @staticmethod
    def _features(state: dict, dim: int) -> np.ndarray:
        """Reconstruit le vecteur feature du world model (16 dims)."""
        from services.ai_engine.rl_agent.world_model import WorldModel
        return WorldModel().encoder(state)[:dim]

    def _centroid_biased(self, graph, refs: Tuple[str, ...]) -> Proposal:  # noqa: ANN001
        """Mouvement aléatoire biaisé : composant connecté → vers centroïde."""
        from services.ai_engine.autonomous_optimizer.proposer_llm import (
            _neighbor_centroid, _net_degree)

        degree = _net_degree(graph)
        candidates = [r for r in refs if degree.get(r, 0) > 0] or list(refs)
        ref = self.rng.choice(candidates)
        comp = graph.components[ref]
        bw, bh = board_extents(graph)
        centroid = _neighbor_centroid(graph, ref)
        if centroid is not None:
            dx = max(-2.0, min(2.0, (centroid[0] - comp.x) / 2.0))
            dy = max(-2.0, min(2.0, (centroid[1] - comp.y) / 2.0))
            jitter_x = self.rng.uniform(-0.5, 0.5)
            jitter_y = self.rng.uniform(-0.5, 0.5)
            dx = round(max(-2.0, min(2.0, dx + jitter_x)), 2)
            dy = round(max(-2.0, min(2.0, dy + jitter_y)), 2)
        else:
            dx = round(self.rng.uniform(-2.0, 2.0), 2)
            dy = round(self.rng.uniform(-2.0, 2.0), 2)
        return Proposal(
            kind="move_component", params={"ref": ref, "dx": dx, "dy": dy},
            rationale=f"mouvement biaisé centroïde ({dx:.2f},{dy:.2f})",
        )
