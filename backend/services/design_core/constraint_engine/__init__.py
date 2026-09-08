"""constraint_engine — moteur de vérification multi-catégories du design core."""
from services.design_core.constraint_engine.cost import MaxCostUSD
from services.design_core.constraint_engine.electrical import (
    DEFAULT_CLASS_WIDTH_MM,
    DecouplingCapProximity,
    DifferentialPairSymmetry,
    ImpedanceTarget,
    MinTraceWidth,
)
from services.design_core.constraint_engine.engine import (
    BaseConstraint,
    ConstraintEngine,
    ConstraintReport,
    Violation,
)
from services.design_core.constraint_engine.manufacturing import MaxComponentCount
from services.design_core.constraint_engine.mechanical import (
    BoardOutline,
    KeepoutViolation,
    MaxBoardUtilization,
    MinClearance,
)
from services.design_core.constraint_engine.thermal import ThermalHotspot

__all__ = [
    "ConstraintEngine", "ConstraintReport", "Violation", "BaseConstraint",
    "MinClearance", "BoardOutline", "KeepoutViolation", "MaxBoardUtilization",
    "MinTraceWidth", "ImpedanceTarget", "DifferentialPairSymmetry",
    "DecouplingCapProximity", "ThermalHotspot", "MaxComponentCount", "MaxCostUSD",
    "DEFAULT_CLASS_WIDTH_MM",
]
