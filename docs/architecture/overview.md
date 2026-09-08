# Vue d'ensemble de l'architecture V3

## Positionnement

PCB_AI_DESIGNER_V3 n'est pas un auto-router amélioré : c'est une **plateforme EDA native-IA**. La différence tient dans le déplacement du centre de gravité : le **Design Core** est la source de vérité unique, et toutes les intelligences opèrent sur ce noyau partagé. Aucun module ne détient sa propre copie de l'état du design — une règle stricte qui élimine toute divergence.

## Les trois cerveaux complémentaires

| Cerveau | Modules | Question à laquelle il répond |
|---|---|---|
| 🧠 **Symbolique** | `ai_engine/llm_orchestrator`, `rag_engine`, `knowledge_graph`, `design_core/constraint_engine` | *Que veut construire l'utilisateur ? Quelles règles s'appliquent ?* |
| 🤖 **Décisionnel** | `ai_engine/rl_agent`, `autonomous_optimizer`, `placement_engine`, `router` | *Quelle action géométrique exécuter maintenant ?* |
| 🔬 **Physique** | `simulator/*`, `verification/*` (ERC/DRC/DFM) | *Ce qui vient d'être décidé est-il vrai dans le monde réel ?* |

## Le Design Core (`backend/services/design_core/`)

C'est la correction architecturale majeure V2→V3 : `shared_mental_model` a quitté `ai_engine/` pour intégrer le cœur. Six sous-modules :

1. **`design_graph/`** — composants, nets, couches, keepouts, positions. Tout est serializable (`to_dict/from_dict`), versionnable, et ponte vers `shared/schemas/design_schemas.py` pour l'API.
2. **`intent_graph/`** — arbre d'intentions (fonctionnelle, contrainte, qualité, business) avec priorités et statuts.
3. **`constraint_engine/`** — 11+ contraintes concrètes en 5 catégories (électrique, mécanique, manufacturing, thermique, coût) + rapport de violations pondéré.
4. **`constraint_bus/`** — diffusion temps réel des mises à jour/violations de contraintes.
5. **`design_versioning/`** — révisions atomiques, branches, snapshots, diff, restore. Toute action agent est commitée ; tout rollback est traçable.
6. **`shared_mental_model/`** — contextes par domaine, décisions, trade-offs, confiance agrégée, et `export_for_llm()` qui sérialise l'état mental en prompt compact.

### Règle d'or
> Tout module qui influence le design — LLM, RL, Router, Simulator, DRC, DFM, Human Editor, Manufacturing Engine — **lit et écrit** dans le `SharedMentalModel`. Il est interdit de dupliquer l'état ailleurs.

## Les 10 agents + le Super Agent

`planner` (découpe l'objectif) · `researcher` (RAG/datasheets) · `selector` (choix composants) · `code_generator` (SKIDL) · `placement` (positionnement) · `routing` (traces) · `simulation` (multi-physique) · `validator` (DRC/ERC/DFM) · `corrector` (corrections ciblées) · `manufacturing` (optimisation usine).

Le **Super Agent** (`orchestrator/super_agent/`) les coordonne via planning → delegation → arbitration (conflits : consensus par confiance, *physical wins*, escalade humaine, rollback révision) → decision_policy (machine à états : quand itérer, rollback, escalader, exporter).

## Séparation des responsabilités (fin de chaîne V3)

- **Design Core** = vérité du projet · **AI Engine** = intelligence · **Placement/Routing** = exécution géométrique · **Simulator** = réalité physique · **Verification** = confiance · **Orchestrator** = autonomie · **Integrations** = écosystème EDA (KiCad/Altium/firmware) · **Manufacturing Intelligence** = réalité industrielle · **Exporter** = Gerber/ODB++/IPC-2581.
