# Contribution — PCB_AI_DESIGNER_V3

Merci de contribuer à la plateforme EDA native-IA. Ce document fixe les règles non négociables.

## Principes architecturaux (à respecter absolument)

1. **Design Core = centre du système.** Toute nouvelle fonctionnalité qui influence le design doit lire/écrire via `design_core` (`design_graph`, `intent_graph`, `constraint_engine`, `shared_mental_model`). Il est interdit de dupliquer l'état du design dans un autre service.
2. **Trois cerveaux, responsabilités séparées.**
   - Symbolique (`ai_engine/llm_orchestrator`, `rag_engine`, `knowledge_graph`) : sémantique, intentions, connaissances.
   - Décisionnel (`ai_engine/rl_agent`, `autonomous_optimizer`, `placement_engine`, `router`) : actions géométriques.
   - Physique (`simulator`, `verification`) : vérité physique, jamais « estimée à la main ».
3. **Toute action d'agent est vérifiable et réversible.** Chaque mutation du design passe par `design_versioning` (révision atomique) et peut être annulée par `self_verifier.rollback_manager`.
4. **Multi-tenant strict.** Tout accès données passe par le middleware tenant : `data/projects/{tenant_id}/{user_id}/{project_id}/`.

## Conventions de code

- Python 3.11+, typage complet, `dataclasses`/`pydantic` pour les modèles.
- Imports : `shared.*`, `services.*`, `orchestrator.*`, `api_gateway.*` (PYTHONPATH = racine + `backend/`).
- Lint : `ruff check .` · Format : `ruff format .` · Types : `mypy services shared`.
- Frontend : TypeScript strict, ESLint, Prettier, composants fonctionnels React.
- Tests obligatoires pour tout nouveau module : `tests/unit/` (rapide, sans I/O réseau).

## Workflow Git

1. Branche : `feat/<domaine>-<sujet>` (ex. `feat/router-diff-pairs`).
2. Commits atomiques, style Conventional Commits (`feat:`, `fix:`, `perf:`, `docs:`, `refactor:`, `test:`).
3. PR avec description, captures UI si pertinent, checklist CI verte.
4. Revue requise sur : `design_core/`, `ai_engine/rl_agent`, `verification/`, `exporter/`.

## Ajouter un agent

1. Créer la classe dans `backend/orchestrator/agent_pipeline/` héritant de `BaseAgent`.
2. Implémenter `plan()`, `execute()`, `verify()`, `rollback()`.
3. L'enregistrer dans le registre des agents et déclarer son rôle dans `shared/contracts/agent_contracts.py::AgentRole`.
4. Ajouter les tests unitaires + un scénario d'intégration.

## Signaler un bug

Ouvrez une issue avec : version, repro minimal, logs (`make logs`), comportement attendu vs observé.

## Sécurité

Ne commitez jamais de clés API (`.env` est ignoré). Signalez toute vulnérabilité en privé.
