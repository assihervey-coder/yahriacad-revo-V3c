# Pont Altium

## Vue d'ensemble (`backend/services/pcb_plugin/altium/`)

| Module | Rôle |
|---|---|
| `bridge.py` | Orchestration : import multi-format auto-détecté, export JSON/netlist/ASCII, compat `DesignGraph` |
| `formats.py` | Vocabulaire de records partagé (`|CLE=VAL|`), unités Altium (1/10000 in → mm), détection OLE |
| `ascii_pcb.py` | **PCB 5.0 ASCII** natif : lecture + écriture (composants, pads, nets, pistes, vias) |
| `pcbdoc.py` | **.PcbDoc binaire** (OLE, expérimental) : stream `FileHeader`, records 2 octets BE + texte |
| `netlist_io.py` | **Netlist Protel** : lecture + écriture (connectivité `[…]` composants, `(…)` nets) |
| `synchronization.py` | Comparaison de designs (refs, positions, nets) + résolution de conflits |

## Quatre canaux d'échange

### 1. JSON du pont (symétrique, le plus rapide)

```python
from services.pcb_plugin.altium.bridge import AltiumBridge

bridge = AltiumBridge()
graph = bridge.import_altium("export_altium.json")   # {components, nets, ...}
payload = bridge.export_altium(graph)                # ré-importable tel quel
```

Format : `{"components": [{"ref", "mpn", "footprint", "x_mm", "y_mm", ...}], "nets": [{"name", "pins": [[ref, pin], ...]}]}`.

### 2. PCB 5.0 ASCII (fichiers réels d'Altium Designer)

Altium sait sauvegarder une carte en ASCII (Fichier → Sauvegarder une copie →
PCB ASCII File). Chaque ligne est un record `|RECORD=n|CLE=VALEUR|...` :

```python
graph = bridge.import_auto(texte_ascii)      # ou bridge.import_ascii(texte)
texte = bridge.export_ascii(graph)           # expérimental côté Altium
```

Records interprétés : `2` Component, `3` Track, `4` Via, `7` Text
(designator/commentaire enfants), `8` Pad (avec `NETNAME`), `27` Net ;
les autres records sont ignorés sans erreur. Coordonnées converties
1/10000 pouce → mm ; couches `TOPLAYER`/`BOTTOMLAYER` → side `top`/`bottom`.

### 3. .PcbDoc binaire (expérimental)

Un `.PcbDoc` est un document OLE dont le stream `FileHeader` contient les
mêmes records en binaire (préfixe 2 octets big-endian). Le parseur extrait
composants, pads, nets nommés, pistes/vias portant `NETNAME` ; la
connectivité manquante (données binaires des records Net) se complète avec
une netlist Protel. Dépendance : `olefile` (incluse).

```python
graph = bridge.import_pcbdoc("carte.PcbDoc")   # expérimental
```

### 4. Netlist Protel (connectivité universelle)

Format historique ASCII importable par quasiment tous les outils EDA
(Altium Import Wizard, KiCad, ...) — le canal le plus fiable pour les nets :

```
[
U1
LQFP-48
STM32F103C8T6
]
(
GND
U1-44
C1-2
)
```

```python
graph = bridge.import_netlist(texte)     # positions à faire ensuite
texte = bridge.export_netlist(graph)     # nets dérivés des pads
```

## API REST (`/api/v1/integrations`)

| Endpoint | Description |
|---|---|
| `POST /altium/import` | `payload` (JSON) **ou** `content` (PCB ASCII / netlist) **ou** `content_base64` (PcbDoc binaire) → vrai projet ; `format` détecté retourné |
| `GET /altium/export/{id}?fmt=json\|netlist\|ascii` | Export dans le format voulu (fichier sauvé sous `exports/altium/`) |
| `POST /altium/sync/{id}` | Synchronisation avec l'état distant (conflits + résolution) |

## Synchronisation

```python
from services.pcb_plugin.altium.synchronization import AltiumSynchronizer

sync = AltiumSynchronizer(bridge)
report = sync.sync(graph)
# report.changed_components, report.conflicts, report.resolution
```

Un conflit est détecté quand un même `ref` diverge (position, nets, empreinte)
entre les deux mondes. Trois résolutions : `local_wins`, `remote_wins`,
`manual` (escalade vers le Human Surgical Editor).

## Bridge firmware

Quel que soit l'EDA d'origine, le `firmware_bridge` peut ensuite exporter les
pins vers Zephyr (devicetree overlay), Arduino (defines) ou STM32 HAL (init
snippets) — voir le panneau `FirmwarePreview` du frontend.
