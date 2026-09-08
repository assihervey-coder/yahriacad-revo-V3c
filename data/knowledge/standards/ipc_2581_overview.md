# IPC-2581 — Échange de données de fabrication

IPC-2581 est un format XML ouvert d'échange entre conception et fabrication
(CAD-to-CAM). Il transporte : stack-up (couches, matériaux, épaisseurs),
netlist, composants et BOM, outline de carte, trous, pads, pistes, et les
notes de fabrication (DFM, matières, finitions).

Avantages vs Gerber seul : un fichier unique, des données électriques ET
géométriques, traçabilité des révisions, et moins d'ambiguïté pour l'usine.
La plateforme exporte un package IPC-2581 en complément des Gerber RS-274X
et Excellon pour les usines qui le supportent (JLCPCB, PCBWay).