"""Moteur de contraintes multi-catégories — vérifie le DesignGraph.

Chaque contrainte concrète hérite de BaseConstraint et renvoie des Violations ;
le ConstraintEngine agrège le tout dans un ConstraintReport scoré 0..1.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from services.design_core.design_graph.graph import DesignGraph

log = logging.getLogger(__name__)

SEVERITY_WEIGHTS: Dict[str, float] = {"error": 1.0, "warning": 0.4, "info": 0.1}


@dataclass
class Violation:
    """Violations détectée par une contrainte sur le design courant."""

    constraint_id: str
    severity: str                 # error | warning | info
    category: str
    message: str
    location: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "constraint_id": self.constraint_id, "severity": self.severity,
            "category": self.category, "message": self.message,
            "location": dict(self.location),
        }


@dataclass
class ConstraintReport:
    """Résultat d'une passe d'évaluation : violations + score de conformité."""

    violations: List[Violation] = field(default_factory=list)
    checked: int = 0

    @property
    def passed(self) -> bool:
        """True si aucune violation de sévérité 'error'."""
        return not any(v.severity == "error" for v in self.violations)

    @property
    def score(self) -> float:
        """Score 0..1 = 1 - violations_pondérées / max(1, contraintes vérifiées)."""
        weighted = sum(SEVERITY_WEIGHTS.get(v.severity, 0.5) for v in self.violations)
        return max(0.0, min(1.0, 1.0 - weighted / max(1, self.checked)))

    def by_severity(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for v in self.violations:
            counts[v.severity] = counts.get(v.severity, 0) + 1
        return counts

    def to_dict(self) -> Dict[str, Any]:
        return {
            "checked": self.checked, "passed": self.passed,
            "score": round(self.score, 4),
            "by_severity": self.by_severity(),
            "violations": [v.to_dict() for v in self.violations],
        }


class BaseConstraint(ABC):
    """Contrainte abstraite : identité, catégorie, sévérité + check(graph)."""

    def __init__(
        self,
        constraint_id: str,
        category: str,
        severity: str = "error",
        description: str = "",
    ) -> None:
        self.constraint_id = constraint_id
        self.category = category
        self.severity = severity
        self.description = description or constraint_id

    @abstractmethod
    def check(self, graph: DesignGraph) -> List[Violation]:
        """Vérifie la contrainte sur le graphe et renvoie les violations."""

    def violation(
        self,
        message: str,
        location: Optional[Dict[str, Any]] = None,
        severity: Optional[str] = None,
    ) -> Violation:
        """Fabrique une Violation cohérente avec l'identité de la contrainte."""
        return Violation(
            constraint_id=self.constraint_id,
            severity=severity or self.severity,
            category=self.category,
            message=message,
            location=location or {},
        )

    def __repr__(self) -> str:  # pragma: no cover — confort debug
        return f"<{type(self).__name__} id={self.constraint_id} cat={self.category}>"


class ConstraintEngine:
    """Registre + évaluation de l'ensemble des contraintes actives."""

    def __init__(self) -> None:
        self._constraints: List[BaseConstraint] = []
        self._listeners: List[Callable[[ConstraintReport], None]] = []

    # ------------------------------------------------------------------ registre
    def register(self, constraint: BaseConstraint) -> "ConstraintEngine":
        """Enregistre une contrainte (chaînable)."""
        self._constraints.append(constraint)
        return self

    def register_defaults(self) -> "ConstraintEngine":
        """Enregistre les 11 contraintes standard de la plateforme."""
        # import local pour éviter tout cycle au chargement du package
        from services.design_core.constraint_engine.cost import MaxCostUSD
        from services.design_core.constraint_engine.electrical import (
            DecouplingCapProximity,
            DifferentialPairSymmetry,
            ImpedanceTarget,
            MinTraceWidth,
        )
        from services.design_core.constraint_engine.manufacturing import MaxComponentCount
        from services.design_core.constraint_engine.mechanical import (
            BoardOutline,
            KeepoutViolation,
            MaxBoardUtilization,
            MinClearance,
        )
        from services.design_core.constraint_engine.thermal import ThermalHotspot

        for constraint in (
            MinClearance(), BoardOutline(), KeepoutViolation(), MaxBoardUtilization(),
            MinTraceWidth(), ImpedanceTarget(), DifferentialPairSymmetry(),
            DecouplingCapProximity(), ThermalHotspot(), MaxComponentCount(), MaxCostUSD(),
        ):
            self.register(constraint)
        return self

    @property
    def constraints(self) -> List[BaseConstraint]:
        return list(self._constraints)

    def on_report(self, listener: Callable[[ConstraintReport], None]) -> None:
        """Abonne un callback appelé après chaque évaluation ( pont vers buses )."""
        self._listeners.append(listener)

    # ---------------------------------------------------------------- évaluation
    def evaluate(self, graph: DesignGraph) -> ConstraintReport:
        """Évalue toutes les contraintes ; une contrainte défaillante ne bloque pas."""
        violations: List[Violation] = []
        for constraint in self._constraints:
            try:
                violations.extend(constraint.check(graph))
            except Exception as exc:  # robustesse : jamais de crash du moteur
                log.exception("contrainte %s en erreur", constraint.constraint_id)
                violations.append(Violation(
                    constraint_id=constraint.constraint_id, severity="warning",
                    category=constraint.category,
                    message=f"évaluation impossible: {exc}", location={},
                ))
        report = ConstraintReport(violations=violations, checked=len(self._constraints))
        for listener in self._listeners:
            try:
                listener(report)
            except Exception:
                log.exception("listener de rapport défaillant")
        return report
