"""Loader de datasheets — data/knowledge/datasheets + corpus d'exemple.

`ensure_sample_corpus()` crée un mini-corpus de référence RÉEL (~6 fichiers)
couvrant datasheets / standards / notes d'application, commun aux trois loaders.
"""
from __future__ import annotations

import os

from shared.utilities import get_logger

log = get_logger("ai_engine.rag.datasheets")

DATA_DIR = os.environ.get("AI_KNOWLEDGE_DIR", "data/knowledge")


def datasheets_dir() -> str:
    """Répertoire des datasheets (créé si absent)."""
    path = os.path.join(DATA_DIR, "datasheets")
    os.makedirs(path, exist_ok=True)
    return path


class DatasheetLoader:
    """Loader spécialisé pour les datasheets composants."""

    def __init__(self, retriever=None) -> None:
        self.retriever = retriever

    def ingest(self) -> int:
        """Indexe data/knowledge/datasheets dans le retriever lié."""
        if self.retriever is None:
            raise RuntimeError("DatasheetLoader nécessite un retriever")
        return self.retriever.index_dir(datasheets_dir())


# ---------------------------------------------------------------------------
# Mini-corpus de référence (contenu technique réel et vérifiable)
# ---------------------------------------------------------------------------
_CORPUS: list[tuple[str, str, str]] = [
    ("standards", "ipc_2221_clearance.md", """# IPC-2221 — Clearances (Table 6-1, B4)

## Tension vs clearance (extérieur, sans revêtement)

| Tension (V DC/AC pk) | B1 (0.8mm min) | B2 (B1>2.5mm) | B4 (>=100V) |
|---|---|---|---|
| 0-15 | 0.05 mm | 0.1 mm | 0.1 mm |
| 16-30 | 0.1 mm | 0.1 mm | 0.1 mm |
| 31-50 | 0.1 mm | 0.1 mm | 0.6 mm |
| 51-100 | 0.1 mm | 0.1 mm | 0.6 mm |
| 101-170 | 0.6 mm | 0.6 mm | 1.5 mm |
| 171-250 | 1.5 mm | 1.5 mm | 3.0 mm |

Règle pratique : pour du 3.3V/5V logique, 0.2 mm de clearance est un standard
de fabrication confortable. Pour du 230V, viser 3 mm minimum entre primaire
et secondaire. Les traces de puissance doivent élargir leur clearance avec la
tension de crête."""),
    ("standards", "ipc_2581_overview.md", """# IPC-2581 — Échange de données de fabrication

IPC-2581 est un format XML ouvert d'échange entre conception et fabrication
(CAD-to-CAM). Il transporte : stack-up (couches, matériaux, épaisseurs),
netlist, composants et BOM, outline de carte, trous, pads, pistes, et les
notes de fabrication (DFM, matières, finitions).

Avantages vs Gerber seul : un fichier unique, des données électriques ET
géométriques, traçabilité des révisions, et moins d'ambiguïté pour l'usine.
La plateforme exporte un package IPC-2581 en complément des Gerber RS-274X
et Excellon pour les usines qui le supportent (JLCPCB, PCBWay)."""),
    ("datasheets", "fr4_properties.md", """# FR-4 — Propriétés matériaux

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
d'impédance avec le stack-up exact de l'usine."""),
    ("application_notes", "usb_c_wiring.md", """# USB-C — Notes de câblage (appareil UFP 2.0)

## Câblage minimal (USB 2.0 device)
- VBUS : 5V, condensateur de 1 µF côté récepteur ; diode TVS recommandée.
- CC1 / CC2 : résistances pull-down 5.1 kΩ (Rd) SUR CHAQUE pin CC pour un
  device sink — sans Rd, aucune source n'alimentera VBUS.
- DP / DM : paire différentielle 90 Ω, matching de longueur intra-paire
  ±0.5 mm, longueur totale < 100 mm idéalement, plan de masse continu dessous.
- Dconnector : USB-C possède 2x DP, 2x DM, 2x SBU — en device 2.0, connecter
  DP-A4/A5 et DP-B4/B5 ensemble, DM-A6/A7 et DM-B6/B7 ensemble (soudures en
  A5<->B5 pour CC via 2 résistances séparées).

## Erreurs fréquentes
- Oublier le pull-down Rd sur CC → la carte ne reçoit jamais de power.
- Router DP/DM à travers un split de plan → crosstalk et EMI.
- Vias de test sur CC à moins de 5.1 kΩ au GND par erreur."""),
    ("datasheets", "esp32_wroom_32e_summary.md", """# ESP32-WROOM-32E — Résumé datasheet (Espressif)

## Caractéristiques clés
- MCU : Xtensa LX6 dual-core 240 MHz, 520 KB SRAM, 448 KB ROM.
- WiFi 802.11 b/g/n 2.4 GHz + BLE 4.2 BR/EDR.
- Tension d'alimentation : 3.0 V à 3.6 V (typ. 3.3 V) — logique NON 5V-tolérante.
- Courant : ~80-240 mA en TX WiFi (pics à 500 mA) → prévoir un régulateur
  capable d'au moins 500 mA et un condensateur de 470 µF+ près du module.
- Température : -40 à +85 °C.

## Pins critiques
- EN : reset actif bas, pull-up 10 kΩ + condensateur 1 µF vers GND.
- IO0 : boot strapping (haut = flash boot normal) ; pull-up 10 kΩ.
- GPIO34/35/36/39 : entrées SEULEMENT (pas de pull-up internes).
- GPIO6-11 : reliés à la flash SPI interne — NE PAS UTILISER.
- Antenne PCB intégrée : garder une zone libre sans cuivre (keepout) de
  8-10 mm autour de l'antenne, l'antenne en bord de carte.

## Découplage
- 100 nF sur chaque pin VDD + 10 µF bulk + 470 µF si WiFi actif.
- 22 µF minimum sur VDD33 selon datasheet Espressif (bloc B1)."""),
    ("manufacturing", "jlcpcb_capabilities.md", """# JLCPCB — Capacités de fabrication (économiques, vérifiées 2024)

| Paramètre | Standard | Avancé |
|---|---|---|
| Couches | 1-14 | jusqu'à 20 |
| Min trace/spacing | 0.127 mm (5 mil) | 0.09 mm (3.5 mil) |
| Min trou mécanique | 0.3 mm | 0.2 mm |
| Min via (fini) | 0.2 mm | 0.15 mm |
| Épaisseur cuivre | 1 oz (35 µm) std | 2-3 oz |
| Épaisseur carte | 0.4-2.0 mm | autres sur demande |
| Couleur masque | vert std | 10 couleurs |

Assemblage (PCBA) :
- Min composant : 0201 ; BGA supporté.
- Température de reflux lead-free : ~245-250 °C → composants ≥ 260 °C rating.
- Parts library : basic parts sans frais additionnels, extended parts avec
  frais de chargement.

DFM conseils : 0.2 mm via minimum pour réduire les coûts ; annular ring
≥ 0.125 mm ; garde de 0.3 mm depuis l'outline ; V-Cut ou tab-routing selon
le panneau."""),
    ("application_notes", "decoupling_and_pdn.md", """# Découplage et PDN — règles d'ingénierie

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
  ou d'un QFN pour évacuer la chaleur vers le plan."""),
    ("application_notes", "i2c_design_notes.md", """# I2C — Notes de conception

- Bus open-drain : résistances de pull-up OBLIGATOIRES sur SDA et SCL.
  Valeur typique 4.7 kΩ à 3.3 V (2.2 kΩ pour un bus très chargé à 400 kHz,
  10 kΩ acceptable pour un bus court à 100 kHz).
- Vitesse : 100 kHz (standard), 400 kHz (fast), 1 MHz (fast+).
- Longueur : garder < 30 cm ; au-delà, réduire la capacité ou utiliser un
  buffer (P82B96).
- Mixed voltage : un device 5V sur un bus 3.3V nécessite un level shifter
  (ex : PCA9306) — les pins 3.3V ne sont pas 5V-tolérantes sur la plupart des MCU.
- Pull-up sur une seule paire de résistances pour tout le bus (pas une paire
  par device)."""),
]


def ensure_sample_corpus(base_dir: str | None = None) -> list[str]:
    """Crée le mini-corpus de référence (~6-8 fichiers .md) si absent.

    Retourne la liste des chemins écrits (ou déjà présents).
    """
    root = base_dir or DATA_DIR
    written: list[str] = []
    for sub, fname, content in _CORPUS:
        d = os.path.join(root, sub)
        os.makedirs(d, exist_ok=True)
        fpath = os.path.join(d, fname)
        if not os.path.exists(fpath):
            with open(fpath, "w", encoding="utf-8") as f:
                f.write(content)
        written.append(fpath)
    log.info("corpus d'exemple assuré : %d fichiers", len(written))
    return written
