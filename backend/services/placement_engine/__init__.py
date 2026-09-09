"""placement_engine — cerveau décisionnel appliqué (RL sur géométrie du placement)."""
from services.placement_engine.constraint_placement import ConstraintPlacer, find_free_spot
from services.placement_engine.engine import PlacementEngine, PlacementResult
from services.placement_engine.initial_placement import InitialPlacer
from services.placement_engine.mechanical_placement import MechanicalPlacer
from services.placement_engine.optimizer import PlacementOptimizer
from services.placement_engine.rl_placement import ACTIONS, FEATURE_DIM, RLPlacer
from services.placement_engine.thermal_placement import ThermalPlacer

__all__ = [
    "InitialPlacer", "RLPlacer", "ACTIONS", "FEATURE_DIM",
    "ConstraintPlacer", "find_free_spot", "MechanicalPlacer",
    "ThermalPlacer", "PlacementOptimizer", "PlacementEngine", "PlacementResult",
]
