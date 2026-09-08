# Manufacturing Intelligence — la réalité industrielle

## Profils usine (`factory_profiles.py`, `configs/factories/*.yaml`)

| Usine | min trace | min clearance | min forage | couches max | assemblage |
|---|---|---|---|---|---|
| **JLCPCB** | 0.127 mm | 0.127 mm | 0.2 mm | 20 | oui (SMT économique) |
| **PCBWay** | 0.1 mm | 0.1 mm | 0.2 mm | 14 | oui |

Les profils alimentent directement le `DFMEngine` et le `CostEstimator` — une même carte est évaluée différemment selon l'usine cible.

## Clients API (`pcbway.py`, `jlcpcb.py`)

```python
from services.manufacturing_intelligence import ManufacturingIntelligence

mi = ManufacturingIntelligence()
analyse = mi.analyze(graph, factory="jlcpcb")
# {"profile": {...}, "cost": CostBreakdown, "yield": YieldPrediction, "feedback": [...]}
```

Avec `JLCPCB_API_KEY`/`PCBWAY_API_KEY` : appels réels (quotes, upload gerbers, dispo composants). Sans clé : estimation locale déterministe — la CI fonctionne sans réseau.

## Cost estimator

`CostBreakdown` : `board_usd` (base + aire × facteur + surcoût couches) + `assembly_usd` (par composant SMD + setup) + `components_usd` (prix MPN × marge) → `total_usd`. `optimize_for_cost()` suggère : réduire les couches, regrouper les valeurs de passifs, passer en 1 oz...

## Yield predictor

`YieldPrediction.expected_yield` (0..1) : heuristique pondérée (violations DFM, densité > 70 %, traces proches du minimum usine, nombre de vias) + modèle sklearn optionnel si entraîné. Chaque `risk_factor` est exploitable par le manufacturing agent.

## Boucle de feedback

`manufacturing_feedback.py` transforme le rapport DFM en `ProfileAdjustment` publiées sur le constraint_bus (`manufacturing.feedback`) : le Design Core **resserre lui-même ses contraintes** selon l'usine cible — le design converge vers ce qui est réellement fabriquable au meilleur coût.
