"""design_core — CENTRE DU SYSTÈME et source de vérité unique (PCB_AI_DESIGNER_V3).

Réexports : DesignGraph, IntentGraph, ConstraintEngine/Report, ConstraintBus,
DesignVersioning, SharedMentalModel + types associés.
"""
from services.design_core.constraint_bus import (
    TOPIC_REVALIDATED,
    TOPIC_UPDATED,
    TOPIC_VIOLATED,
    ConstraintBus,
    get_constraint_bus,
)
from services.design_core.constraint_engine import (
    BaseConstraint,
    ConstraintEngine,
    ConstraintReport,
    Violation,
)
from services.design_core.design_graph import (
    Component,
    DesignGraph,
    Keepout,
    Layer,
    Net,
    Pad,
    make_default_stackup,
)
from services.design_core.design_versioning import (
    Branch,
    DesignVersioning,
    Revision,
)
from services.design_core.intent_graph import Intent, IntentGraph
from services.design_core.shared_mental_model import (
    ConfidenceTracker,
    DecisionRecord,
    SharedMentalModel,
    Tradeoff,
)

__all__ = [
    # design graph (source de vérité)
    "DesignGraph", "Component", "Pad", "Net", "Layer", "Keepout", "make_default_stackup",
    # intent graph
    "IntentGraph", "Intent",
    # moteur de contraintes
    "ConstraintEngine", "ConstraintReport", "Violation", "BaseConstraint",
    # bus de contraintes
    "ConstraintBus", "get_constraint_bus", "TOPIC_UPDATED", "TOPIC_VIOLATED",
    "TOPIC_REVALIDATED",
    # versioning
    "DesignVersioning", "Revision", "Branch",
    # modèle mental partagé
    "SharedMentalModel", "DecisionRecord", "Tradeoff", "ConfidenceTracker",
]

__version__ = "3.0.0"
