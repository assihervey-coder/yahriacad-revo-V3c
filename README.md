# PCB_AI_DESIGNER_V3

> **AI-Native Electronic Design Automation Platform** — De l'intention en langage naturel au package de fabrication (Gerber / ODB++ / IPC-2581).

PCB_AI_DESIGNER_V3 est la troisième génération, unifiée et révolutionnaire, de la plateforme : elle fusionne la rigueur structurelle de la V1 avec toutes les capacités différenciantes de la V2, autour d'un noyau central unique — le **Design Core**.

---

## 🌟 Ce qui rend la V3 révolutionnaire

| Génération | Paradigme | Limite |
|---|---|---|
| V1 | Auto-router classique + structure rigoureuse | Pas d'intelligence sémantique |
| V2 | IA (LLM + RL) greffée sur un moteur de routage | Intelligence cloisonnée dans `ai_engine/` |
| **V3** | **AI-Native EDA : le Design Core est la vérité du projet, tous les cerveaux y accèdent** | — |

### Les 3 principes fondateurs

1. **🔥 Le Design Core est le centre du système.** `shared_mental_model` quitte `ai_engine/` pour intégrer `design_core/`. LLM, RL, Router, Simulator, DRC, DFM, Human Editor et Manufacturing Engine partagent le même modèle mental du design.
2. **🧠 Trois cerveaux complémentaires.**
   - **Cerveau symbolique** (LLM, RAG, Knowledge Graph, Constraint Engine) : comprend *ce que l'utilisateur veut construire*.
   - **Cerveau de décision** (RL, World Model, Policy/Value Networks) : décide *quelles actions géométriques exécuter*.
   - **Cerveau physique** (Simulateurs, DRC, ERC, DFM) : vérifie *ce qui est vrai dans le monde réel*.
3. **Le flux V3 complet.** UTILISATEUR → CHAT / IMPORT EDA → PARSER + NL→SKIDL → DESIGN CORE (Intent + Constraints + Design Graph) → SUPER AGENT → Exécution (Composants / Placement / Routage / Simulation) → SELF VERIFIER (CONTINUE / ROLLBACK) → AUTONOMOUS OPTIMIZER → DRC/ERC/DFM → HUMAN SURGICAL EDITOR → MANUFACTURING ENGINE → **Gerber / ODB++ / IPC-2581**.

---

## 🏗️ Architecture (vue d'ensemble)

```
pcb_ai_designer_v3/
├── .infra/            # Kubernetes, Helm, Docker, monitoring, logging, Terraform
├── frontend/          # Next.js 14 — éditeur, viewer 3D, chat, dashboards
├── backend/
│   ├── api_gateway/   # REST, GraphQL, WebSocket, MCP server, middleware
│   ├── orchestrator/  # workflow_engine, super_agent, 10 agents, state_manager
│   └── services/
│       ├── parser/              # netlist, schematic, PCB, NL→SKIDL, contraintes
│       ├── design_core/         # 🔥 NOYAU : design_graph, intent_graph,
│       │                        #   constraint_engine, constraint_bus,
│       │                        #   design_versioning, shared_mental_model
│       ├── ai_engine/           # llm_orchestrator, rag_engine, knowledge_graph,
│       │                        #   rl_agent, self_verifier, autonomous_optimizer, training
│       ├── placement_engine/    # placement initial/RL/contrainte/mécanique/thermique
│       ├── router/              # topologique, géométrique, paires différentielles,
│       │                        #   impédance, high-speed, vias, optimisation
│       ├── simulator/           # EM, thermique, SI, PI, mécanique + multi-physique
│       │                        #   + surrogate models neuronaux
│       ├── verification/        # ERC, DRC, DFM, règles, qualité
│       ├── pcb_plugin/          # KiCad live, Altium bridge, session restore
│       ├── firmware_bridge/     # Zephyr, Arduino, STM32 — pins & headers
│       ├── manufacturing_intelligence/ # PCBWay, JLCPCB, coûts, rendement
│       └── exporter/            # Gerber, ODB++, IPC-2581, BOM, Pick&Place
├── shared/            # schémas, contrats d'agents, events, géométrie, unités
├── tests/             # unit, integration, system, HIL, benchmarks (vs Quilter)
├── docs/              # architecture, api, ai, physics, eda, manufacturing
├── scripts/           # dev, data, training, deployment
└── configs/           # dev / staging / production / models / factories
```

> Séparation stricte des responsabilités : **Design Core** (vérité du projet) · **AI Engine** (intelligence) · **Placement/Routing** (exécution géométrique) · **Simulator** (réalité physique) · **Verification** (confiance) · **Orchestrator** (autonomie) · **Integrations** (écosystème EDA) · **Manufacturing Intelligence** (réalité industrielle).

---

## 🚀 Démarrage rapide

### Prérequis
- Python 3.11+, Node.js 20+, Docker & Docker Compose
- (Optionnel) CUDA 12.x pour l'entraînement RL

### Avec Make (recommandé)
```bash
make setup          # venv + dépendances + frontend
make dev            # backend + frontend + worker en parallèle
```

### Avec Docker Compose
```bash
docker compose up -d
# API Gateway      → http://localhost:8000
# Frontend         → http://localhost:3000
# GraphQL          → http://localhost:8000/graphql
# MCP Server       → http://localhost:8000/mcp
# Grafana          → http://localhost:3001
```

### Exemple : créer un design par le chat
```bash
curl -X POST http://localhost:8000/api/v1/chat/commands \
  -H "Content-Type: application/json" \
  -d '{"message": "Design a 4-layer ESP32 sensor board with USB-C and a BME680, JLCPCB assembly"}'
```
La plateforme enchaîne alors : intention → SKIDL → sélection composants → placement → routage → simulation → vérification → optimisation → export manufacturing.

---

## 🧪 Tests & benchmarks

```bash
make test            # tests unitaires + intégration
make test-ai         # évaluation des agents IA
make benchmark       # benchmarks placement/routage vs Quilter
```

## 📚 Documentation

- [ARCHITECTURE.md](ARCHITECTURE.md) — architecture détaillée & flux de données
- [docs/](docs/) — API, IA, physique, intégrations EDA, manufacturing
- [CONTRIBUTING.md](CONTRIBUTING.md) — guide de contribution

## 📄 Licence

Voir [LICENSE](LICENSE).
