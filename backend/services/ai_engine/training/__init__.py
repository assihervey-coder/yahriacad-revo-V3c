"""Training — génération d'épisodes, pipeline REINFORCE, checkpoints, éval."""
from __future__ import annotations

from services.ai_engine.training.checkpoint_manager import CheckpointManager
from services.ai_engine.training.data_generator import (
    generate_batch,
    generate_placement_episode,
)
from services.ai_engine.training.dataset_manager import (
    DatasetManager,
    save_episode,
)
from services.ai_engine.training.evaluation import evaluate_policy
from services.ai_engine.training.training_pipeline import TrainingPipeline

__all__ = [
    "generate_placement_episode",
    "generate_batch",
    "save_episode",
    "DatasetManager",
    "TrainingPipeline",
    "evaluate_policy",
    "CheckpointManager",
]
