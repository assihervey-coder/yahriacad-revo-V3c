# Signal Integrity & Power Integrity

## Signal Integrity (`backend/services/simulator/signal_integrity.py`)

### Impédance microstrip
Largeur de trace inversée depuis la cible (formule microstrip standard, itération) :

```
Z0 ≈ 87/√(εr+1.41) · ln(5.98·h/(0.8w+t))     (w/h < 1)
```

FR4 typique : εr=4.3, h=210 µm, t=35 µm → **50 Ω ≈ 0.35 mm** de trace. `impedance_control.py` assigne automatiquement les largeurs par classe de net (50 Ω high_speed, 0.5 mm power, 0.2 mm default).

### Délai de propagation
`t = L / (c/√εr_eff)` — utilisé pour le length matching des groupes appariés (tolérance ±0.5 mm, serpentins générés par `high_speed.py`).

### Coefficient de réflexion
`|Γ| = |(ZL−Z0)/(ZL+Z0)|` — un net est **fail** si |Γ| > 0.2 ou si le mismatch de longueur dépasse la tolérance du groupe.

## Power Integrity (`backend/services/simulator/power_integrity.py`)

### IR drop
Résistance de trace estimée `R = ρ_cu·L/(w·h)` (ρ_cu = 1.72e-8 Ω·m, h = 35 µm), courant estimé par la puissance des composants sur le net : `I = ΣP/U`. Le verdict est **fail** si le droop dépasse 50 mV.

### EMC proxy (`em_sim.py`)
- Capacité parallèle-plaque des plans : `C = ε₀·εr·A/d` (qualité du découplage global).
- Crosstalk estimé entre traces parallèles du même layer (`k/d²`).
- Aire de boucle PWR→GND par net (rayonnement).

## Règles d'application

Les contraintes correspondantes vivent dans le `constraint_engine` (catégorie `electrical`) : `ImpedanceTarget` exige une cible sur les nets `high_speed`/`differential`, `DifferentialPairSymmetry` vérifie l'appariement des longueurs. Le **cerveau physique** (sims) et le **cerveau de règles** (contraintes) se complètent : l'un calcule le réel, l'autre exprime l'intention.
