# Les 10 agents spécialisés

Chaque agent hérite de `BaseAgent` (`orchestrator/agent_pipeline/base.py`) et implémente : `plan()` (décompose son objectif), `execute()` (agit sur le DesignGraph + commit une révision + écrit dans le SharedMentalModel), `verify()` (auto-contrôle), `rollback()` (restauration).

| Agent | Rôle | Cerveau | Entrées | Sorties |
|---|---|---|---|---|
| `planner` | Décompose l'intention en délégations ordonnées | 🧠 Symbolique | IntentGraph | plan de Delegations |
| `researcher` | Recherche composants, datasheets, règles (RAG + KG) | 🧠 Symbolique | component_hints | context["research"] |
| `selector` | Sélectionne les MPN et construit le DesignGraph initial | 🧠 Symbolique | intent + lib | DesignGraph (composants+nets) |
| `code_generator` | Génère le script SKIDL du design | 🧠 Symbolique | message NL | script SKIDL |
| `placement` | Positionne les composants | 🤖 Décisionnel | DesignGraph | placement + révision |
| `routing` | Route les nets (A*, impédance, différentiel) | 🤖 Décisionnel | DesignGraph placé | traces + révision |
| `simulation` | Thermique / EM / SI / PI | 🔬 Physique | DesignGraph routé | SimResults |
| `validator` | ERC/DRC/DFM + self-verification + qualité | 🔬 Physique | DesignGraph | rapports + pass/fail |
| `corrector` | Corrige les violations ciblées (déplace, re-route, écarte) | 🤖 Mixte | rapports | graph corrigé + taux |
| `manufacturing` | Coût, rendement, feedback usine, package | 🔬 Physique | design final | package + analyse |

## Cycle de vie d'une délégation

1. Le **Super Agent** choisit `next_action` (machine à états / LLM) et émet une `Delegation` (objectif, critères d'acceptation, `max_iterations`, `on_fail`: rollback/escalate/retry).
2. Le **Delegator** exécute : événements `agent.task.assigned` → `execute()` → `agent.task.completed`.
3. Le **Self Verifier** contrôle le résultat : `VALID` → continue ; `INVALID` → `RollbackManager` restaure la dernière révision valide.
4. En cas de conflit entre agents (ex. placement vs thermique), l'**Arbitrator** tranche selon la politique : consensus pondéré par confiance, *physical wins*, escalade humaine, ou retour à la dernière révision valide.

## Confiance et modèle mental

Après chaque exécution, l'agent écrit dans le `SharedMentalModel` :
- sa décision et sa rationale (`record_decision`), 
- ses arbitrage de critères (`record_tradeoff`), 
- sa confiance dans son domaine (`confidence.update("routing", 0.87)`).

`export_for_llm()` sérialise tout cela en prompt compact — utilisé par le Super Agent et les proposeurs LLM de l'optimiseur autonome.
