# Flux de données V3 — de l'intention au package de fabrication

```
UTILISATEUR
   │  (chat NL · import KiCad/Altium · netlist)
   ▼
API GATEWAY (REST / GraphQL / WebSocket / MCP)        middleware: auth · rate_limit · audit · tenant
   ▼
PARSER SERVICE ──► NL→SKIDL ──► netlist normalisée ──► constraint_extractor
   ▼
DESIGN CORE  ◄────────────────────────────────────────────────────────┐
   intent_graph (pourquoi)   design_graph (quoi + où)                 │
   constraint_engine (règles)  constraint_bus (diffusion)             │
   design_versioning (révisions/branches)                             │
   shared_mental_model (contexte · décisions · trade-offs · confiance)│
   ▼                                                                  │
SUPER AGENT : planning → delegation → arbitration → decision_policy    │
   ▼                                                                  │
   ├── COMPONENT INTELLIGENCE (selector + knowledge_graph)            │
   ├── PLACEMENT ENGINE (initial → RL → contraintes → thermique)      │
   ├── ROUTER (topologique → A* → impédance → paires diff. → vias)    │
   ├── SIMULATOR (thermique/EM/SI/PI + surrogate models)              │
   ▼                                                                  │
SELF VERIFIER ──► VALID ───► CONTINUE ─────────────────────────────────┤
   │ INVALID                                                          │
   ▼                                                                  │
ROLLBACK MANAGER (design_versioning.restore) ──────────────────────────┘
   ▼
AUTONOMOUS OPTIMIZER (proposer_llm · rl · évolutionnaire · bayésien
   + fast_evaluator + keeper_logic)  ←→  révisions atomiques
   ▼
DRC / ERC / DFM (verification) + QUALITY SCORING (0..100)
   ▼
HUMAN SURGICAL EDITOR (component_move · route_edit · constraint_edit)
   — chaque édition humaine est commitée comme révision du même historique
   ▼
MANUFACTURING ENGINE (factory_profiles · PCBWay · JLCPCB ·
   cost_estimator · yield_predictor · manufacturing_feedback)
   ▼
EXPORTER : GERBER (RS-274X) · ODB++ · IPC-2581 · BOM · Pick&Place
```

## Étape par étape

1. **Capture d'intention** — le message chat est parsé par `IntentParser` (cerveau symbolique) → `IntentGraph` (racine + sous-intentions priorisées) ; les contraintes citées en langage naturel sont extraites par `ConstraintExtractor` et enregistrées dans le `ConstraintEngine`.
2. **Sélection composants** — le `selector` matche les MPN via la bibliothèque (`component_lib_matcher`, 18+ composants réels seedés) et construit le premier `DesignGraph` + nets.
3. **Placement** — passes en cascade : initial (grille/connecteurs au bord), optimisation HPWL (simulated annealing), contraintes (découplage <3 mm, power au bord), thermique (hotspots espacés).
4. **Routage** — MST topologique par net, A* sur grille 0,25 mm avec obstacles, largeurs assignées par impédance cible (microstrip), paires différentielles parallèles, serpentins de length-matching, rip-up & reroute.
5. **Simulation** — solveur thermique diffusion 2D (Jacobi), proxies EM/SI/PI, boucle multi-physique avec feedback (thermique→placement, SI→routage) et surrogate models neuronaux pour l'évaluation rapide.
6. **Self-verification** — checks déterministes + physiques + confiance ; **VALID** → continue, **INVALID** → rollback manager restaure la dernière révision valide via `design_versioning`.
7. **Optimisation autonome** — quatre proposeurs (LLM, RL, évolutionnaire, bayésien) évalués par `FastEvaluator`, gardés par `keeper_logic` (amélioration stricte + patience).
8. **Vérification finale** — ERC + DRC + DFM vs profil usine cible + `QualityScorer` (0..100, 7 dimensions pondérées).
9. **Édition chirurgicale humaine** — l'humain retouche au niveau géométrique ; chaque édition passe par le même pipeline de révision.
10. **Manufacturing & export** — coût/rendement par usine, package complet : Gerber RS-274X + Excellon, ODB++, IPC-2581, BOM CSV, Pick&Place.

## Événements

Tout le flux est événementiel (`shared/events`) : chaque étape publie (`placement.proposed`, `routing.proposed`, `verification.passed`, `rollback.executed`, `export.completed`...). Le frontend s'abonne via WebSocket `/ws/{project_id}` et affiche l'activité des agents en direct.
