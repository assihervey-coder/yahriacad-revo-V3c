"""Types d'événements V3 — tout le flux UTILISATEUR→EXPORT est événementiel."""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any


class EventTypes:
    # Capture d'intention
    INTENT_CAPTURED = "intent.captured"
    INTENT_PARSED = "intent.parsed"
    # Parsing / sélection
    IMPORT_COMPLETED = "import.completed"
    COMPONENTS_SELECTED = "components.selected"
    SKIDL_GENERATED = "skidl.generated"
    # Design core
    DESIGN_REVISED = "design.revised"
    CONSTRAINT_UPDATED = "constraint.updated"
    CONSTRAINT_VIOLATED = "constraint.violated"
    # Exécution agents
    JOB_STARTED = "job.started"
    AGENT_TASK_ASSIGNED = "agent.task.assigned"
    AGENT_TASK_COMPLETED = "agent.task.completed"
    PLACEMENT_PROPOSED = "placement.proposed"
    ROUTING_PROPOSED = "routing.proposed"
    SIMULATION_COMPLETED = "simulation.completed"
    # Vérification
    VERIFICATION_PASSED = "verification.passed"
    VERIFICATION_FAILED = "verification.failed"
    ROLLBACK_EXECUTED = "rollback.executed"
    OPTIMIZATION_ITERATION = "optimization.iteration"
    # Fin de chaîne
    DRC_COMPLETED = "drc.completed"
    MANUFACTURING_READY = "manufacturing.ready"
    EXPORT_COMPLETED = "export.completed"
    # Humain
    HUMAN_EDIT_COMMITTED = "human.edit.committed"
    ESCALATION_REQUESTED = "escalation.requested"


@dataclass
class Event:
    type: str
    payload: dict[str, Any] = field(default_factory=dict)
    project_id: str = ""
    tenant_id: str = "default"
    source: str = ""               # module émetteur, ex "design_core"
    correlation_id: str = ""       # relie les events d'un même job
    ts: float = field(default_factory=time.time)
    event_id: str = field(default_factory=lambda: uuid.uuid4().hex)


def make_event(
    type: str,
    payload: dict[str, Any] | None = None,
    *,
    project_id: str = "",
    tenant_id: str = "default",
    source: str = "",
    correlation_id: str = "",
) -> Event:
    return Event(
        type=type,
        payload=payload or {},
        project_id=project_id,
        tenant_id=tenant_id,
        source=source,
        correlation_id=correlation_id,
    )
