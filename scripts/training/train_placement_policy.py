#!/usr/bin/env python3
"""Entraînement de la politique de placement (REINFORCE) — CLI.

Enveloppe scripts/ autour de
services.ai_engine.training.training_pipeline.TrainingPipeline :
épisodes générés par data_generator, boucle REINFORCE complète,
checkpoints gérés par CheckpointManager (rétention 5 par défaut).

Usage :
    python scripts/training/train_placement_policy.py --episodes 100
    python scripts/training/train_placement_policy.py --episodes 500 --n-components 12
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "backend"))

DEFAULT_CHECKPOINT_DIR = str(REPO_ROOT / "data" / "trained_models" / "policies")


def main() -> int:
    """Point d'entrée CLI : lance la boucle REINFORCE et rapporte les métriques."""
    parser = argparse.ArgumentParser(description="Entraînement policy placement (REINFORCE)")
    parser.add_argument("--episodes", type=int, default=100,
                        help="nombre d'épisodes d'entraînement")
    parser.add_argument("--n-components", type=int, default=8,
                        help="composants par épisode (graphe aléatoire)")
    parser.add_argument("--steps-per-episode", type=int, default=12,
                        help="actions par épisode")
    parser.add_argument("--lr-policy", type=float, default=1e-3)
    parser.add_argument("--lr-value", type=float, default=1e-3)
    parser.add_argument("--seed", type=int, default=0, help="reproductibilité")
    parser.add_argument("--checkpoint-dir", default=DEFAULT_CHECKPOINT_DIR)
    parser.add_argument("--eval-episodes", type=int, default=10,
                        help="épisodes d'évaluation après entraînement (0 = off)")
    args = parser.parse_args()

    from services.ai_engine.rl_agent.action_space import ActionSpace
    from services.ai_engine.rl_agent.policy_network import PolicyNetwork
    from services.ai_engine.rl_agent.rl_agent import RLAgent
    from services.ai_engine.rl_agent.value_network import ValueNetwork
    from services.ai_engine.rl_agent.world_model import WorldModel
    from services.ai_engine.training.data_generator import generate_placement_episode
    from services.ai_engine.training.evaluation import evaluate_policy
    from services.ai_engine.training.training_pipeline import TrainingPipeline

    pipeline = TrainingPipeline(
        steps_per_episode=args.steps_per_episode,
        seed=args.seed,
        checkpoint_dir=args.checkpoint_dir,
    )
    print(f"==> REINFORCE placement : {args.episodes} épisodes "
          f"({args.n_components} comps, {args.steps_per_episode} steps)")
    metrics = pipeline.train_placement_policy(
        episodes=args.episodes,
        checkpoint_dir=args.checkpoint_dir,
        n_components=args.n_components,
        lr_policy=args.lr_policy,
        lr_value=args.lr_value,
    )

    print(json.dumps({k: v for k, v in metrics.items() if not isinstance(v, (list, dict))},
                     ensure_ascii=False, indent=2))

    if args.eval_episodes > 0:
        print(f"==> Évaluation sur {args.eval_episodes} épisodes (vs baseline centroïde)")
        space = ActionSpace(["U1"]).place(max_grid=40)
        agent = RLAgent(
            PolicyNetwork(space.size(), feature_dim=16, seed=args.seed),
            ValueNetwork(feature_dim=16, seed=args.seed),
            WorldModel(seed=args.seed), space,
        )
        results = evaluate_policy(agent, episodes=args.eval_episodes)
        print(json.dumps(results, ensure_ascii=False, indent=2, default=str))

    print("==> Checkpoints dans", args.checkpoint_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
