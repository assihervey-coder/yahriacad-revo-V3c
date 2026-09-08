"""surrogate_models — surrogates ML pour accélérer les prédictions de sims."""
from services.simulator.surrogate_models.neural_surrogates import NeuralSurrogate
from services.simulator.surrogate_models.fast_prediction import FastPredictor, FEATURE_NAMES

__all__ = ["NeuralSurrogate", "FastPredictor", "FEATURE_NAMES"]
