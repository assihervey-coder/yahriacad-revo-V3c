# ARCHITECTURE — PCB_AI_DESIGNER_V3

## 1. Vision

V3 n'est pas un auto-router amélioré : c'est une **plateforme EDA native-IA**. La différence fondamentale réside dans le déplacement du centre de gravité du système : le **Design Core** (`backend/services/design_core/`) devient la source de vérité unique du projet, et toutes les intelligences — symbolique, décisionnelle, physique — opèrent sur ce noyau partagé.

## 2. Les trois cerveaux

```
                    ┌──────────────────────────────┐
                    │        DESIGN CORE           │
                    │  design_graph · intent_graph │
                    │  constraint_engine + bus     │
                    │  design_versioning           │
                    │  shared_mental_model         │
                    └──────┬───────┬───────┬───────┘
           ┌───────────────┘       │       └───────────────┐
┌──────────▼─────────┐  ┌─────────▼─────────┐  ┌──────────▼─────────┐
│ 🧠 CERVEAU         │  │ 🤖 CERVEAU        │  │ 🔬 CERVEAU         │
│    SYMBOLIQUE      │  │    DÉCISIONNEL    │  │    PHYSIQUE        │
│                    │  │                   │  │                    │
│ llm_orchestrator   │  │ rl_agent          │  │ simulator (EM/Th/  │
│ rag_engine         │  │  world_model      │  │   SI/PI/Mech)      │
│ knowledge_graph    │  │  policy_network   │  │ erc/drc/dfm        │
│ constraint_engine  │  │  value_network    │  │ physical_verif.    │
│ intent_parser      │  │  action_space     │  │ quality_scoring    │
│                    │  │ autonomous_optim. │  │                    │
│ "QUOI construire"  │  │ "COMMENT agir"    │  │ "EST-CE VRAI ?"    │
└────────────────────┘  └───────────────────┘  └────────────────────┘
```

### Règle d'or
`shared_mental_model` vit dans `design_core/` (correction architecturale majeure V2→V3). Tout module qui influencent le design — LLM, RL, Router, Simulator, DRC, DFM, Human Editor, Manufacturing Engine — **lit et écrit** dans ce modèle mental partagé. Aucune intelligence cloisonnée.

## 3. Flux de données V3 (bout-en-bout)

```
UTILISATEUR
   │ (chat NL  ·  import KiCad/Altium  ·  netlist)
   ▼
API GATEWAY (REST / GraphQL / WebSocket / MCP)
   ▼
PARSER SERVICE ──► NL→SKIDL ──► netlist normalisée ──► constraint_extractor
   ▼
DESIGN CORE  ◄──────────────────────────────────────────────┐
   intent_graph      design_graph      constraint_engine     │
   (pourquoi)        (quoi + où)       (règles)              │
   shared_mental_model  design_versioning (branches/revisions)│
   ▼                                                          │
SUPER AGENT (orchestrator)                                    │
   planning ─ delegation ─ arbitration ─ decision_policy      │
   ▼                                                          │
   ├─► COMPONENT INTELLIGENCE (selector + kg compatibilité)
   ├─► PLACEMENT ENGINE  (initial → RL → contraintes → thermique)
   ├─► ROUTER            (topologique → géométrique → SI/impédance → vias)
   ├─► SIMULATOR         (multi-physics loop + surrogate models)
   ▼                                                          │
SELF VERIFIER ── VALID ? ──► CONTINUE ────────────────────────┤
   │ INVALID                                                  │
   ▼                                                          │
ROLLBACK MANAGER ─────────────────────────────────────────────┘
   ▼
AUTONOMOUS OPTIMIZER (proposer_llm · rl · évolutionnaire · bayésien
   + fast_evaluator + keeper_logic)
   ▼
DRC / ERC / DFM  (verification service, quality_scoring)
   ▼
HUMAN SURGICAL EDITOR (édition chirurgicale : component_move,
   route_edit, constraint_edit — chaque edit commit une révision)
   ▼
MANUFACTURING ENGINE (factory_profiles · PCBWay · JLCPCB ·
   cost_estimator · yield_predictor)
   ▼
EXPORTER : GERBER · ODB++ · IPC-2581 · BOM · Pick&Place
```

## 4. Les 10 agents spécialisés

| Agent | Rôle | Cerveau principal |
|---|---|---|
| `planner` | Décompose l'intention en plan de tâches | Symbolique (LLM) |
| `researcher` | Recherche composants/datasheets/règles (RAG, KG) | Symbolique |
| `selector` | Sélectionne les composants optimaux | Symbolique |
| `code_generator` | Génère SKIDL/scripts de build | Symbolique |
| `placement` | Place les composants | Décisionnel (RL) |
| `routing` | Route les nets | Décisionnel (RL) |
| `simulation` | Simule EM/Th/SI/PI | Physique |
| `validator` | DRC/ERC/DFM + self-verification | Physique |
| `corrector` | Diagnostique et corrige les violations | Mixte (LLM+RL) |
| `manufacturing` | Optimise pour l'usine cible | Physique + données usine |

Le **Super Agent** (`orchestrator/super_agent/`) les coordonne via `planning/`, `delegation/`, `arbitration/` (résolution de conflits entre agents) et `decision_policy/` (quand déléguer, quand itérer, quand rollback, quand escalader à l'humain).

## 5. Modèle mental partagé — contrat d'interface

```python
# design_core/shared_mental_model — accessible partout
from services.design_core.shared_mental_model import SharedMentalModel

smm = SharedMentalModel(design_graph, intent_graph)
smm.update_context("routing", {"layer_budget": 4, "crowded_regions": [...]})
smm.record_decision(actor="placement_agent", decision="CPU au centre",
                    rationale="minimiser longueur bus DDR", confidence=0.87)
smm.record_tradeoff("cost", "signal_integrity", chose="si", weight=0.7)
confidence = smm.confidence.global_score()   # agrégat multi-facteurs
```

Chaque agent : **lit** le SMM avant d'agir, **écrit** ses décisions/trade-offs/confiances après action. Le `constraint_bus` diffuse les changements de contraintes à tous les abonnés en temps réel.

## 6. Frontend (Next.js)

- `viewer_3d/` — rendu WebGL/three.js du PCB, layer viewer
- `pcb_editor/` — placement, routage, contraintes
- `surgical_editor/` — édition chirurgicale humaine (component_move, route_edit, constraint_edit)
- `chat_interface/` — chat, commandes de design, activité des agents en direct (WebSocket)
- `dashboard/` — projets, jobs, optimisation, qualité
- `simulation_dashboard/` — thermique, EM, SI, PI
- `firmware_preview/`, `credit_dashboard/`

Services front : `api_client` (REST), `websocket_live` (events agents), `grpc_web`, `mcp_client`. State : Zustand (`project_store`, `design_store`, `agent_store`, `simulation_store`).

## 7. Infrastructure

- **API Gateway** : FastAPI (REST) + Strawberry/Ariadne (GraphQL) + WebSocket + MCP server (tools/resources/permissions) + middleware (auth JWT, rate limiting, audit, multi-tenant)
- **Orchestration** : workflow engine (pipelines/tasks/jobs) compatible Prefect/Temporal, checkpoints + rollback_state
- **Multi-tenant** : `data/projects/{tenant_id}/{user_id}/{project_id}/`
- **Observabilité** : Prometheus + Grafana (métriques), Loki/Elastic (logs), tracing
- **Déploiement** : Docker multi-images (backend/ai/simulator/router/frontend), Kubernetes base + overlays (dev/staging/prod), Helm chart, Terraform (cloud/storage/databases/networking)

## 8. Versioning & sécurité du design

`design_versioning` offre révisions, branches et snapshots. Toute action agent est commitée atomiquement ; le `rollback_manager` du `self_verifier` restaure le dernier état valide. Les éditions humaines passent par le même pipeline de révision — un seul historique de vérité.
