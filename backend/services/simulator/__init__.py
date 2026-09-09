"""simulator — cerveau physique : thermique, CEM, SI, PI, mécanique + multi-physics."""
from services.simulator.base import BaseSim, SimResult
from services.simulator.thermal_sim import ThermalSim
from services.simulator.em_sim import EMIProxySim
from services.simulator.signal_integrity import SignalIntegritySim
from services.simulator.power_integrity import PowerIntegritySim
from services.simulator.mechanical_sim import MechanicalSim
from services.simulator.multi_physics_loop import (
    ConvergenceMonitor,
    MultiPhysicsCoupling,
    run_loop,
)
from services.simulator.surrogate_models import FastPredictor, NeuralSurrogate
from services.simulator.surrogate_models.beta_path import AUTOTRAIN_EVERY, run_sim_smart
from services.simulator.surrogate_models.manager import SurrogateManager, get_manager
from services.simulator.worker import SIM_REQUEST_TOPIC, SimulationWorker

__all__ = [
    "BaseSim", "SimResult",
    "ThermalSim", "EMIProxySim", "SignalIntegritySim",
    "PowerIntegritySim", "MechanicalSim",
    "MultiPhysicsCoupling", "ConvergenceMonitor", "run_loop",
    "NeuralSurrogate", "FastPredictor", "SurrogateManager", "get_manager",
    "run_sim_smart", "AUTOTRAIN_EVERY",
    "SimulationWorker", "SIM_REQUEST_TOPIC",
]
