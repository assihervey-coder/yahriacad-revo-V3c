"""Évaluation de politique — vs baseline centroïde (win rate)."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import numpy as np

from shared.utilities import get_logger
from services.ai_engine.autonomous_optimizer.fast_evaluator import FastEvaluator
from services.ai_engine.rl_agent.action_space import ActionSpace
from services.ai_engine.rl_agent.rl_agent import RLAgent
from services.ai_engine.rl_agent.world_model import state_from_graph
from services.ai_engine.training.data_generator import generate_placement_episode
from services.ai_engine.training.training_pipeline import TrainingPipeline

log = get_logger("ai_engine.training.evaluation")


def _centroid_baseline(graph) -> Dict[str, tuple]:  # noqa: ANN001
    """Baseline : place chaque composant au centroïde de ses voisins."""
    from services.ai_engine.autonomous_optimizer.proposer_llm import (
        _neighbor_centroid)

    out: Dict[str, tuple] = {}
    for ref, comp in graph.components.items():
        centroid = _neighbor_centroid(graph, ref)
        if centroid is not None:
            out[ref] = centroid
    return out


def evaluate_policy(agent: RLAgent, episodes: int = 20,
                    n_components: int = 8, seed: int = 1000,
                    steps: int = 10) -> Dict[str, float]:
    """Évalue une politique entraînée contre la baseline centroïde.

    Retourne : avg_reward, avg_wire_length, win_rate (part des épisodes où
    la politique bat la baseline centroïde sur la wire length).
    """
    evaluator = FastEvaluator()
    rewards: List[float] = []
    final_wls: List[float] = []
    wins = 0

    for ep in range(episodes):
        graph, _opt = generate_placement_episode(n_components, seed=seed + ep)
        refs = sorted(graph.components.keys())
        agent.action_space.set_refs(refs)
        agent.episode_buffer.clear()

        # trajectoire de la politique
        ep_rewards: List[float] = []
        state = state_from_graph(graph)
        for _ in range(steps):
            feats = agent.observe(state)
            idx = agent.select_action(greedy=True)
            action = agent.action_space.decode(idx)
            delta_wl = TrainingPipeline._apply_action(graph, action)
            ep_rewards.append(-delta_wl)
            state = state_from_graph(graph)

        rl_wl = evaluator.evaluate(graph).breakdown.get("wire_length", 0.0)

        # baseline centroïde sur une copie fraîche
        baseline_graph, _ = generate_placement_episode(n_components, seed=seed + ep)
        for ref, (cx, cy) in _centroid_baseline(baseline_graph).items():
            baseline_graph.place(ref, cx, cy)
        base_wl = evaluator.evaluate(baseline_graph).breakdown.get(
            "wire_length", 0.0)

        rewards.append(float(np.mean(ep_rewards)) if ep_rewards else 0.0)
        final_wls.append(rl_wl)
        if rl_wl <= base_wl:
            wins += 1

    result = {
        "avg_reward": round(float(np.mean(rewards)), 5) if rewards else 0.0,
        "avg_wire_length": round(float(np.mean(final_wls)), 3) if final_wls else 0.0,
        "win_rate": round(wins / episodes, 3) if episodes else 0.0,
        "episodes": float(episodes),
    }
    log.info("évaluation politique: %s", result)
    return result
