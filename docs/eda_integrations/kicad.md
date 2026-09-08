# Intégration KiCad

## Vue d'ensemble (`backend/services/pcb_plugin/kicad/`)

| Module | Rôle |
|---|---|
| `importer.py` | Parse netlist `.net` (s-expression) et `.kicad_pcb` simplifié → `DesignGraph` |
| `exporter.py` | `DesignGraph` → `.kicad_pcb` valide (modules, pads transformés par rotation, segments, vias, nets) |
| `live_host.py` | Pont WebSocket vers une session KiCad ouverte (push/pull design en direct) |
| `session_sync.py` | Synchronisation bidirectionnelle avec détection de conflits |

## Import d'une netlist

```python
from services.pcb_plugin.kicad.importer import import_kicad_netlist

graph = import_kicad_netlist(open("mon_projet.net").read())
graph.stats()   # {'components': 14, 'nets': 21, ...}
```

Formats supportés : s-expression KiCad (`(components (comp (ref "R1") ...))`, `(nets (net (node (ref "U1") (pin "5"))))`) et JSON. Les bboxes sont déduites des empreintes courantes (0402/0603/0805/SOIC/QFN...).

## Export vers KiCad

```python
from services.pcb_plugin.kicad.exporter import export_kicad_pcb

kicad_text = export_kicad_pcb(graph)
open("out.kicad_pcb", "w").write(kicad_text)
```

Génère : header version 20221018, couches déclarées, un `(module ...)` par composant (pads transformés par la rotation), les `(segment ...)` de chaque `Net.path` avec largeur/net/couche, les `(via ...)`.

## Mode live

```python
import asyncio
from services.pcb_plugin.kicad.live_host import KiCadLiveHost

async def main():
    host = KiCadLiveHost("ws://localhost:7999")
    await host.connect()
    host.on_design_change(lambda snap: print("changement reçu:", snap.get("revision")))
    await host.push_design(graph)

asyncio.run(main())
```

Sans session KiCad ouverte, le host reste en mode offline (warnings, aucune exception) — utile en CI.

## Synchronisation de session

`SessionSynchronizer` compare la révision locale et le snapshot distant (`detect_conflicts`), pousse ou tire selon l'horloge de révision. `session_restorer.py` sauvegarde/restaure des sessions complètes sous `data/projects/{tenant}/{user}/{project}/`.

## Cycle recommandé

1. **Schéma dans KiCad** → export netlist → import V3.
2. **Placement/routage IA dans V3** (agents + optimiseur + self-verifier).
3. **Édition chirurgicale** éventuelle dans l'UI V3.
4. **Export `.kicad_pcb`** → retouches finales dans KiCad si souhaité.
5. **Export manufacturing** (Gerber/ODB++/IPC-2581) directement depuis V3.
