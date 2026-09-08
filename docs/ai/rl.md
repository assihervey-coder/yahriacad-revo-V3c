# Reinforcement Learning — le cerveau décisionnel

## Composants (`backend/services/ai_engine/rl_agent/`)

### Action space
- `PlacementAction` : MOVE (dx,dy ∈ {-2..2} pas 0.5 mm), ROTATE (0/90/180/270), SWAP, NOP — 169 actions discrétisées.
- `RouteAction` : EXTEND, TURN, VIA, RIPUP, NOP.
- `encode()/decode()` bijectifs pour l'entraînement.

### World model
Encode l'état du design en 16 features (nombre de composants, densité, HPWL, violations, positions normalisées...), apprend la dynamique (linéaire entraînable) et **prédit la récompense** avant d'agir — permet au policy de « réfléchir » sans exécuter.

### Policy network (REINFORCE NumPy)
MLP léger (NumPy pur, torch optionnel en lazy) : `forward(features) → logits → softmax` ; `select_action` (ε-greedy) ; `train_batch(features, actions, advantages)` avec gradient log-softmax × advantage + baseline value.

### Value network
Régression MSE sur les retours escomptés (γ=0.99 par défaut, `configs/models/models.yaml`).

## Boucle d'entraînement (`training/training_pipeline.py`)

```bash
PYTHONPATH=.:backend python3 scripts/training/train_placement_policy.py --episodes 200
```

1. `data_generator.generate_placement_episode()` génère un board aléatoire + positions optimales approximées (centroïde itéré).
2. REINFORCE : reward = −ΔHPWL − k·violations ; policy+value entraînés par épisode.
3. Checkpoints toutes les 10 épisodes (`CheckpointManager`, rétention 5) dans `data/trained_models/policies/`.
4. `evaluation.evaluate_policy()` : récompense moyenne, HPWL moyen, win-rate vs baseline centroïde.

## Rôle dans la plateforme

- `RLPlacer` (placement_engine) : améliore le placement initial si une policy entraînée est disponible, sinon recours heuristique (simulated annealing HPWL).
- `RLOptimizer` (autonomous_optimizer) : propose des mutations évaluées par `FastEvaluator`, gardées par `keeper_logic`.
- `WorldModel` : prédiction de récompense pour l'arbitrage du Super Agent.

## Réentraîner

```bash
PYTHONPATH=.:backend python3 scripts/training/train_world_model.py    # world model
PYTHONPATH=.:backend python3 scripts/training/train_placement_policy.py --episodes 500
```

Les checkpoints sont chargés automatiquement au démarrage s'ils existent ; sans checkpoint, la plateforme fonctionne en mode heuristique complet (aucun échec).
