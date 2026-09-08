#!/usr/bin/env python3
"""Entraînement du world model numpy sur des épisodes générés.

Le world model apprend la DYNAMIQUE de l'environnement de placement :
prédire l'état suivant (features 16D) après une action, sans rouler le
simulateur physique. Pipeline :
  1. génération de N épisodes (data_generator) ;
  2. pour chaque step : encodage de l'état, action échantillonnée, transition
     (features, features_next) collectée ;
  3. mise à jour de la dynamique linéaire (fit_transition, moindres carrés
     en ligne — numpy pur) ;
  4. sauvegarde en .npz (data/trained_models/world_models/world_v1.npz).

Usage :
    python scripts/training/train_world_model.py --episodes 50
    python scripts/training/train_world_model.py --episodes 200 --out path.npz
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "backend"))

DEFAULT_OUT = REPO_ROOT / "data" / "trained_models" / "world_models" / "world_v1.npz"


def main() -> int:
    """Point d'entrée : collecte des transitions + fit + save npz."""
    parser = argparse.ArgumentParser(description="Entraînement du world model (numpy)")
    parser.add_argument("--episodes", type=int, default=50,
                        help="épisodes de collecte de transitions")
    parser.add_argument("--steps-per-episode", type=int, default=12)
    parser.add_argument("--n-components", type=int, default=8)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--lr", type=float, default=1e-3,
                        help="taux d'apprentissage de la dynamique linéaire")
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    args = parser.parse_args()

    from services.ai_engine.rl_agent.action_space import ActionSpace
    from services.ai_engine.rl_agent.world_model import WorldModel, state_from_graph
    from services.ai_engine.training.data_generator import generate_placement_episode
    from services.ai_engine.training.training_pipeline import TrainingPipeline

    pipeline = TrainingPipeline(seed=args.seed)

    space = ActionSpace(["U1"]).place(max_grid=40)
    model = WorldModel(seed=args.seed)
    rng = np.random.default_rng(args.seed)
    errors: list[float] = []
    n_transitions = 0

    print(f"==> Collecte : {args.episodes} épisodes × {args.steps_per_episode} steps")
    for ep in range(1, args.episodes + 1):
        graph, _optimal = generate_placement_episode(args.n_components,
                                                     seed=args.seed + ep)
        refs = sorted(graph.components.keys())
        space.set_refs(refs)

        state = state_from_graph(graph)
        for _step in range(args.steps_per_episode):
            features = model.encoder(state)
            idx = int(rng.integers(0, space.size()))
            action = space.decode(idx)
            # Applique l'action réelle (ΔWL + violations via les helpers du pipeline)
            _delta_wl = pipeline._apply_action(graph, action)      # noqa: SLF001
            _violations = pipeline._violation_count(graph)         # noqa: SLF001
            next_state = state_from_graph(graph)
            features_next = model.encoder(next_state)

            mse = model.fit_transition(features, features_next, lr=args.lr)
            errors.append(mse)
            n_transitions += 1
            state = next_state

        if ep % 10 == 0:
            recent = float(np.mean(errors[-100:])) if errors else 0.0
            print(f"    épisode {ep}/{args.episodes} — transitions: {n_transitions}, "
                  f"MSE(100 dernières): {recent:.6f}")

    if not n_transitions:
        print("! aucune transition collectée", file=sys.stderr)
        return 1

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    model.save(str(out_path))

    final_mse = float(np.mean(errors[-100:]))
    print(f"==> World model sauvegardé : {out_path}")
    print(f"    transitions vues : {n_transitions} | MSE final : {final_mse:.6f}")
    print(f"    W: {model.W.shape}, ‖W−I‖ : "
          f"{float(np.linalg.norm(model.W - np.eye(model.W.shape[0]))):.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
