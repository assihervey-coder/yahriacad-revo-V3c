# Conventions développeur

## Imports & PYTHONPATH

Le PYTHONPATH est **racine + backend/** (déjà configuré dans `pyproject.toml`, le Makefile, les Dockerfiles) :

```python
from shared.geometry import Point, RoutePath            # bibliothèque commune
from shared.events import get_event_bus, EventTypes     # événements
from services.design_core import DesignGraph            # noyau
from services.ai_engine import LLMOrchestrator          # IA
from orchestrator.agent_pipeline import BaseAgent       # agents
from api_gateway.deps import get_tenant                 # API
```

Interdits : imports relatifs profonds, chemins en dur hors `data/projects/{tenant}/...`, duplication de l'état du design.

## Style

- Python 3.11+, type hints partout, dataclasses/pydantic v2, docstrings courtes en français.
- `ruff format` + `ruff check` (config dans `pyproject.toml`), `mypy` sur services + shared.
- Frontend : TypeScript strict, composants fonctionnels, Zustand pour l'état, pas d'`any`.

## Dépendances lourdes

torch / openai / faiss / sklearn / pyyaml sont **optionnels** : toujours en import lazy avec fallback NumPy/stdlib. Tout le code doit s'importer avec la stdlib + numpy + pydantic.

## Ajouter un agent

1. Classe dans `backend/orchestrator/agent_pipeline/` héritant de `BaseAgent` (implémenter `plan/execute/verify/rollback`).
2. Déclarer le rôle dans `shared/contracts/agent_contracts.py::AgentRole`.
3. L'enregistrer dans `registry.build_agents()`.
4. L'agent doit : lire le `SharedMentalModel` avant d'agir, **commiter une révision** après mutation, publier ses événements.
5. Tests unitaires + un scénario d'intégration.

## Ajouter une contrainte

Hériter de `BaseConstraint` (`design_core/constraint_engine/`), catégoriser (electrical/mechanical/manufacturing/thermal/cost), implémenter `check(graph) -> list[Violation]`, l'enregistrer dans `ConstraintEngine.register_defaults()` + test.

## Ajouter un simulateur

Hériter de `BaseSim` (`simulator/base.py`), retourner un `SimResult(metrics, passed)` documenté (voir docs/physics/), l'ajouter à la boucle multi-physique + `QualityScorer`.

## Événements

Toute action notable publie via `get_event_bus()` avec un type de `EventTypes` — le frontend et les dashboards en dépendent. Un événement = payload JSON-sérialisable, jamais un objet vivant.

## Tests

- Unitaires : rapides, sans I/O réseau, dans `tests/unit/` (95+ actuellement).
- Intégration : API via TestClient dans `tests/integration/`.
- Tout nouveau module = au moins un test unitaire ; la CI (`GitHub Actions`) bloque sur rouge.
