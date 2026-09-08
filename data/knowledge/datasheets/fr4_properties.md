# FR-4 — Propriétés matériaux

- Er (constante diélectrique) : 4.2 à 4.8 à 1 MHz (typ. 4.5 pour FR4 standard,
  ~4.2 pour les prépregs 2116 usés en impédance contrôlée).
- Tanδ (facteur de dissipation) : 0.017 à 0.025 à 1 MHz — dégrade les signaux
  > 1 GHz ; préférer Isola FR408HR, Megtron 6 ou Rogers au-delà.
- Tg (température de transition vitreuse) : 130-140 °C standard, 170-180 °C
  pour FR4 haute Tg (recommandé pour leLead-free reflow et forte puissance).
- Conductivité thermique : ~0.3 W/m.K (très faible : les plans de cuivre et
  les vias thermiques font le travail de refroidissement).
- Épaisseurs prépreg courantes : 1080 (~0.075 mm), 2116 (~0.115 mm), 7628 (~0.185 mm).

Impédance microstrip 50 Ω sur FR4 : pour un prépreg 1080 (h≈0.1 mm), une
trace d'environ 0.2 mm de large donne ~50 Ω. Toujours vérifier par calculateur
d'impédance avec le stack-up exact de l'usine.