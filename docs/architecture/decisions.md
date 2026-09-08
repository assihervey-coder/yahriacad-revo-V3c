# Décisions d'architecture (ADR)

## ADR-001 — `shared_mental_model` vit dans le Design Core

**Contexte.** En V2, le modèle mental vivait dans `ai_engine/` : le Router, le DRC, le Manufacturing Engine et l'éditeur humain n'y avaient pas accès naturellement, ce qui créait des vues divergentes du design.

**Décision.** Déplacer `shared_mental_model` dans `design_core/`. Tout module qui influence le design lit/écrit via cette interface unique (`update_context`, `record_decision`, `record_tradeoff`, `confidence`).

**Conséquences.** Une seule source de vérité pour le « pourquoi » des décisions ; l'arbitration du Super Agent peut voter avec les confiances réelles ; coût : discipline d'écriture exigée de chaque agent.

## ADR-002 — Bus d'événements asynchrone comme colonne vertébrale

**Contexte.** Le flux V3 implique ~10 services et 10 agents ; un appel synchrone en cascade serait fragile et non observable.

**Décision.** `shared/events/event_bus.py` : `InProcessEventBus` par défaut (zéro dépendance, tests), `RedisEventBus` en production (mixité in-process + pub/sub inter-services). Chaque étape du flux publie des événements typés (`EventTypes`).

**Conséquences.** Observabilité native (le frontend streame `/ws`), découplage des services, rejeu possible via l'historique.

## ADR-003 — Provider LLM avec mock déterministe par défaut

**Contexte.** La plateforme doit être testable en CI sans clé API et sans réseau.

**Décision.** `llm_orchestrator/provider.py` : protocole `LLMProvider` + `MockLLMProvider` déterministe (réponses structurées par mots-clés), `OpenAIProvider`/`ZAIProvider` en import lazy. `LLM_PROVIDER=mock` par défaut.

**Conséquences.** CI 100 % déterministe ; bascule production par variable d'environnement ; les prompts réels sont validés par le même chemin de code.

## ADR-004 — NumPy-first, torch optionnel

**Contexte.** Les réseaux RL (policy/value/world model) et les surrogates ne nécessitent pas de GPU à l'échelle des designs typiques (≤ 500 composants).

**Décision.** Tout le cerveau décisionnel est implémenté en NumPy pur (REINFORCE, MSE value, world model linéaire). torch est une dépendance optionnelle (extras `ai`/`training`) importée en lazy pour accélérer si présente.

**Conséquences.** Installation légère, import toujours possible, montée en puissance GPU opt-in.

## ADR-005 — Les simulateurs sont de vrais solveurs, pas des stubs

**Contexte.** « Le cerveau physique doit dire le vrai » : des proxies faux rendraient la self-verification mensongère.

**Décision.** Le simulateur thermique résout réellement l'équation de Laplace (diffusion steady-state, itérations de Jacobi sur grille 2D NumPy). SI/PI/EM sont des calculs analytiques documentés (microstrip, coefficient de réflexion, IR drop, capacité parallèle-plaque). Les surrogate models apprennent à prédire ces résultats, jamais à les remplacer en décision finale.

**Conséquences.** Résultats reproductibles ; coûts de calcul maîtrisés ; précision FEM/SPICE externe possible plus tard en remplaçant `BaseSim`.

## ADR-006 — Multi-tenant au niveau du chemin de données

**Contexte.** `data/projects/{tenant_id}/{user_id}/{project_id}/` impose l'isolation structurellement.

**Décision.** Le middleware `tenant` extrait le tenant (header `X-Tenant-Id` ou JWT) et tous les services persistant dérivent leurs chemins de ce contexte. Aucun chemin de données en dur ailleurs.

**Conséquences.** Isolation simple à auditer ; migration vers un stockage objet possible en remplaçant la couche de persistance.
