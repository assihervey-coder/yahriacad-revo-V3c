"""surrogate_models — surrogates ML pour accélérer les prédictions de sims.

Chaîne β complète : SurrogateDataset (collecte JSONL) → SurrogateManager
(entraînement quand assez d'échantillons, métriques MAE/R²) → FastPredictor
(inférence rapide marquée β avec latence).
"""
from services.simulator.surrogate_models.neural_surrogates import NeuralSurrogate
from services.simulator.surrogate_models.fast_prediction import FastPredictor, FEATURE_NAMES
from services.simulator.surrogate_models.dataset import SurrogateDataset
from services.simulator.surrogate_models.manager import (
    BenchmarkResult,
    SurrogateManager,
    SurrogateStatus,
)

__all__ = [
    "NeuralSurrogate",
    "FastPredictor",
    "FEATURE_NAMES",
    "SurrogateDataset",
    "SurrogateManager",
    "SurrogateStatus",
    "BenchmarkResult",
]
