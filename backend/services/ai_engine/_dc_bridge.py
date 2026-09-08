"""Pont vers services.design_core — imports centralisés et lazy.

`services.design_core` est développé par un agent parallèle (2-a) avec le
contrat d'interfaces suivant :
    DesignGraph, IntentGraph, ConstraintEngine, DesignVersioning, SharedMentalModel

Ce module centralise l'accès runtime pour que le reste d'ai_engine puisse :
- typer via `TYPE_CHECKING` sans dépendance dure à l'import ;
- réimporter à la demande (le temps que l'agent 2-a termine) ;
- donner une erreur claire si le module n'existe pas encore.
"""
from __future__ import annotations

from typing import Any, Callable, Tuple

_DC_ERR = (
    "services.design_core indisponible — l'agent 2-a ne l'a pas encore écrit. "
    "Réessayez (PYTHONPATH doit contenir la racine + backend/)."
)


def _try_import() -> Tuple[Any, ...]:
    """Retourne les 5 classes design_core, ou lève ImportError explicite."""
    try:
        from services.design_core import (
            ConstraintEngine,
            DesignGraph,
            DesignVersioning,
            IntentGraph,
            SharedMentalModel,
        )
    except ImportError as exc:  # pragma: no cover — dépend de l'agent parallèle
        raise ImportError(_DC_ERR) from exc
    return DesignGraph, IntentGraph, ConstraintEngine, DesignVersioning, SharedMentalModel


def design_graph_cls() -> Callable[..., Any]:
    """Classe DesignGraph (import runtime)."""
    return _try_import()[0]


def intent_graph_cls() -> Callable[..., Any]:
    """Classe IntentGraph (import runtime)."""
    return _try_import()[1]


def constraint_engine_cls() -> Callable[..., Any]:
    """Classe ConstraintEngine (import runtime)."""
    return _try_import()[2]


def design_versioning_cls() -> Callable[..., Any]:
    """Classe DesignVersioning (import runtime)."""
    return _try_import()[3]


def shared_mental_model_cls() -> Callable[..., Any]:
    """Classe SharedMentalModel (import runtime)."""
    return _try_import()[4]


def is_available() -> bool:
    """True si services.design_core est importable."""
    try:
        _try_import()
        return True
    except ImportError:
        return False
