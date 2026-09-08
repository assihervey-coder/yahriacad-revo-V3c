# Découplage et PDN — règles d'ingénierie

## Découplage
- 100 nF (X7R, 0402/0603) par pin d'alimentation VDD de chaque CI, au plus
  près du pin, via court (< 1 mm) vers le plan de masse.
- 10 µF bulk par zone fonctionnelle ; 22-47 µF sur la sortie d'un LDO pour
  la stabilité (suivre la datasheet : LDO type AMS1117 → 22 µF tantalum/Cer X5R).
- Les condensateurs 0402 ont moins d'ESL que 0805 → meilleure réponse HF.

## PDN (Power Delivery Network)
- Impédance cible : Z_target = Vripple / Itransient (ex : 3.3 V, 5 % ripple,
  500 mA transitoire → 0.33 Ω, dominé par les condensateurs en dessous de 10 MHz).
- Preferer un plan de masse continu (jamais de split sous une ligne rapide).
- Via thermiques : matrice de 4-9 vias sous un pad thermal d'un régulateur
  ou d'un QFN pour évacuer la chaleur vers le plan.