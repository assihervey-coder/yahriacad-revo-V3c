# Simulation thermique — solveur de diffusion 2D

## Principe (`backend/services/simulator/thermal_sim.py`)

Le solveur résout l'**équation de Laplace en régime permanent** sur une grille 2D discrétisée à 1 mm :

```
∂²T/∂x² + ∂²T/∂y² = -q/k      →      T_new[i,j] = (T[i±1,j] + T[i,j±1]) / 4 + q[i,j]/(4k)
```

- **Sources** : chaque composant injecte `power_w` sur sa cellule (positions absolues).
- **Bordures** : isothermes à 25 °C (ambiant, dissipatif idéal).
- **Résolution** : itérations de Jacobi, tolérance 1e-4, max 5 000 itérations, conductivité effective FR4.
- **Sorties** : `max_temp_c`, position du hotspot, `mean_temp_c`, verdict `passed` (max < 85 °C).

## Hypothèses et limites

| Réalité | Modèle | Impact |
|---|---|---|
| Conduction 3D + vias thermiques | Conduction 2D effective | Hotspots légèrement surestimés |
| Convection naturelle | Bordures isothermes | Températures moyennes précises à ±10 % |
| Transitoire (montée en T) | Régime permanent | Conservatif pour la fiabilité |

Pour un dimensionnement précis (copper pours, via farms), remplacer `BaseSim` par une intégration FEM (le contrat `SimResult` est stable).

## Boucle multi-physique

`multi_physics_loop/feedback.py` : si le thermique échoue → suggestions de déplacement (régulateurs au bord, espacement hotspots) → re-placement → re-routage → re-simulation (max 3 itérations, `convergence.py` détecte la stabilisation).

## Surrogate models

`surrogate_models/neural_surrogates.py` : MLP NumPy entraîné sur les résultats du solveur (features : nb composants, densité, puissance totale, HPWL → max_temp_c). Utilisé par `FastPredictor` pour évaluer des centaines de candidats de placement sans refaire tourner le solveur complet.
