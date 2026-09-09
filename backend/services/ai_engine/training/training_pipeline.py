"""TrainingPipeline — boucle REINFORCE complète sur RLAgent."""
from __future__ import annotations

import time
from typing import Any

import numpy as np
from shared.utilities import get_logger

from services.ai_engine.autonomous_optimizer.fast_evaluator import FastEvaluator
from services.ai_engine.rl_agent.action_space import ActionSpace
from services.ai_engine.rl_agent.policy_network import PolicyNetwork
from services.ai_engine.rl_agent.rl_agent import RLAgent
from services.ai_engine.rl_agent.value_network import ValueNetwork
from services.ai_engine.rl_agent.world_model import WorldModel, state_from_graph
from services.ai_engine.training.checkpoint_manager import CheckpointManager
from services.ai_engine.training.data_generator import generate_placement_episode

log = get_logger("ai_engine.training.pipeline")


class TrainingPipeline:
    """Pipeline d'entraînement du policy network de placement (REINFORCE).

    reward par step = −Δwire_length − violations (convention plate-forme).
    """

    def __init__(self, steps_per_episode: int = 12, seed: int = 0,
                 checkpoint_dir: str = "data/trained_models/policies") -> None:
        self.steps_per_episode = steps_per_episode
        self.seed = seed
        self.checkpoint_dir = checkpoint_dir

    # -------------------------------------------------------------- helpers
    @staticmethod
    def _apply_action(graph, action) -> float:  # noqa: ANN001
        """Applique une PlacementAction in-place, retourne le Δwire_length."""
        evaluator = FastEvaluator()
        before = evaluator.evaluate(graph).breakdown.get("wire_length", 0.0)
        kind = action.kind.value
        ref = action.ref
        if kind == "move" and ref in graph.components:
            comp = graph.components[ref]
            graph.place(ref, comp.x + action.dx, comp.y + action.dy)
        elif kind == "rotate" and ref in graph.components:
            comp = graph.components[ref]
            graph.place(ref, comp.x, comp.y,
                        rotation=(comp.rotation + action.rot_delta) % 360)
        after = evaluator.evaluate(graph).breakdown.get("wire_length", 0.0)
        return after - before

    @staticmethod
    def _violation_count(graph) -> int:  # noqa: ANN001
        try:
            from services.ai_engine.self_verifier.deterministic import check_deterministic
            return len(check_deterministic(graph))
        except Exception:
            return 0

    # ---------------------------------------------------------------- train
    def train_placement_policy(self, episodes: int = 100,
                               checkpoint_dir: str | None = None,
                               n_components: int = 8,
                               lr_policy: float = 1e-3,
                               lr_value: float = 1e-3) -> dict[str, Any]:
        """Boucle REINFORCE complète — retourne les métriques d'entraînement."""
        checkpoint_dir = checkpoint_dir or self.checkpoint_dir
        ckpt = CheckpointManager(checkpoint_dir)

        # construit l'agent une fois (taille d'action fixée sur 8 refs max)
        _, first_opt = generate_placement_episode(n_components, seed=self.seed)
        dummy_refs = ["U1"]
        space = ActionSpace(dummy_refs).place(max_grid=40)
        policy = PolicyNetwork(space.size(), feature_dim=16, seed=self.seed)
        value = ValueNetwork(feature_dim=16, seed=self.seed)
        agent = RLAgent(policy, value, WorldModel(seed=self.seed), space)

        evaluator = FastEvaluator()
        history: list[dict[str, Any]] = []
        t0 = time.time()

        for ep in range(1, episodes + 1):
            graph, _optimal = generate_placement_episode(
                n_components, seed=self.seed + ep)
            refs = sorted(graph.components.keys())
            space.set_refs(refs)

            ep_states: list[np.ndarray] = []
            ep_actions: list[int] = []
            ep_rewards: list[float] = []
            ep_wl_start = evaluator.evaluate(graph).breakdown.get("wire_length", 0.0)

            state = state_from_graph(graph)
            for _step in range(self.steps_per_episode):
                feats = agent.observe(state)
                idx = agent.select_action(eps=0.15)
                action = space.decode(idx)
                delta_wl = self._apply_action(graph, action)
                violations = self._violation_count(graph)
                reward = -delta_wl - 0.1 * violations
                ep_states.append(feats)
                ep_actions.append(idx)
                ep_rewards.append(reward)
                state = state_from_graph(graph)

            metrics = agent.learn(ep_rewards, ep_states, ep_actions,
                                  lr_policy=lr_policy, lr_value=lr_value)
            ep_wl_end = evaluator.evaluate(graph).breakdown.get("wire_length", 0.0)
            ep_metrics = {
                "episode": ep,
                "mean_reward": float(np.mean(ep_rewards)) if ep_rewards else 0.0,
                "total_reward": float(np.sum(ep_rewards)),
                "wire_length_start": ep_wl_start,
                "wire_length_end": ep_wl_end,
                "policy_loss": metrics.get("policy_loss", 0.0),
                "value_loss": metrics.get("value_loss", 0.0),
            }
            history.append(ep_metrics)

            if ep % 10 == 0:
                log.info(
                    "ep %d/%d — reward moy %.3f, WL %.1f→%.1f, policy_loss %.4f",
                    ep, episodes, ep_metrics["mean_reward"],
                    ep_wl_start, ep_wl_end, ep_metrics["policy_loss"])
                ckpt.save(f"policy_ep{ep}", {
                    "policy": {"W": policy.W.tolist(), "b": policy.b.tolist()},
                    "value": {"w": value.w.tolist(), "b": value.b},
                    "history": history[-10:],
                }, step=ep)

        # checkpoint final + sauvegarde des réseaux
        ckpt.save("policy_final", {
            "policy": {"W": policy.W.tolist(), "b": policy.b.tolist()},
            "value": {"w": value.w.tolist(), "b": value.b},
            "history": history[-20:],
        }, step=episodes)
        agent.save_all(checkpoint_dir)

        mean_rewards = [h["mean_reward"] for h in history]
        return {
            "episodes": episodes,
            "mean_reward_last10": float(np.mean(mean_rewards[-10:]))
            if mean_rewards else 0.0,
            "mean_reward_all": float(np.mean(mean_rewards)) if mean_rewards else 0.0,
            "best_episode_reward": max((h["total_reward"] for h in history),
                                       default=0.0),
            "duration_s": round(time.time() - t0, 2),
            "checkpoint_dir": checkpoint_dir,
            "history_tail": history[-10:],
        }
