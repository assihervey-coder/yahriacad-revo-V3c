# Pont Altium

## Vue d'ensemble (`backend/services/pcb_plugin/altium/`)

| Module | Rôle |
|---|---|
| `bridge.py` | Import/export JSON Altium (export généré par le pont Altium côté script) ↔ `DesignGraph` |
| `synchronization.py` | Comparaison de designs (refs, positions, nets) + résolution de conflits |

## Import

```python
from services.pcb_plugin.altium.bridge import AltiumBridge

bridge = AltiumBridge()
graph = bridge.import_altium("export_altium.json")
```

Format attendu (JSON généré par le script de pont côté Altium) :

```json
{
  "components": [
    {"ref": "U1", "mpn": "STM32F103C8T6", "footprint": "LQFP-48",
     "x_mm": 30.0, "y_mm": 25.0, "rotation_deg": 0, "side": "top"}
  ],
  "nets": [
    {"name": "GND", "class": "power", "pins": [["U1", "44"], ["C1", "2"]]}
  ]
}
```

## Synchronisation

```python
from services.pcb_plugin.altium.synchronization import AltiumSynchronizer

sync = AltiumSynchronizer(bridge)
report = sync.sync(graph)
# report.changed_components, report.conflicts, report.resolution
```

Un conflit est détecté quand un même `ref` diverge (position, nets, empreinte) entre les deux mondes. Trois résolutions : `local_wins`, `remote_wins`, `manual` (escalade vers le Human Surgical Editor).

## Bridge firmware

Quel que soit l'EDA d'origine, le `firmware_bridge` peut ensuite exporter les pins vers Zephyr (devicetree overlay), Arduino (defines) ou STM32 HAL (init snippets) — voir le panneau `FirmwarePreview` du frontend.
