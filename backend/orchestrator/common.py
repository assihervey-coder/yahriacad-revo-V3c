"""Helpers communs de l'orchestrateur.

Contient les utilitaires partagés par le workflow engine, le super agent et
le pipeline d'agents :
  - publication d'événements thread-safe / loop-safe sur le bus,
  - sondage défensif d'attributs (les services V3 sont développés en parallèle,
    on code contre leurs interfaces sans les recréer),
  - sérialisation / reconstruction de DesignGraph,
  - graph minimal duck-typé (SimpleDesignGraph) pour tests et repli,
  - persistance des paquets d'export.
"""
from __future__ import annotations

import asyncio
import importlib
import inspect
import json
import math
import os
import threading
import time
import zipfile
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from shared.events import Event, get_event_bus, make_event
from shared.utilities import get_logger, new_id

log = get_logger("orchestrator.common")

# ---------------------------------------------------------------------------
# Répertoire de données (écrasable pour les tests)
# ---------------------------------------------------------------------------

def data_root() -> Path:
    """Racine des données : data/projects (relative au projet)."""
    return Path(os.getenv("PCB_DATA_DIR", "data/projects"))

# ---------------------------------------------------------------------------
# Boucle principale + publication d'événements thread-safe
# ---------------------------------------------------------------------------

_MAIN_LOOP: Optional[asyncio.AbstractEventLoop] = None
_LOOP_LOCK = threading.Lock()


def register_main_loop(loop: Optional[asyncio.AbstractEventLoop]) -> None:
    """Enregistre la boucle principale (API / runner) pour publier depuis les threads."""
    global _MAIN_LOOP
    with _LOOP_LOCK:
        _MAIN_LOOP = loop


def get_main_loop() -> Optional[asyncio.AbstractEventLoop]:
    with _LOOP_LOCK:
        return _MAIN_LOOP


def _running_loop() -> Optional[asyncio.AbstractEventLoop]:
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        return None


async def _safe_publish(bus: Any, event: Event) -> None:
    try:
        await bus.publish(event)
    except Exception:  # un event ne doit jamais casser le métier
        log.debug("publication event %s échouée", event.type, exc_info=True)


def publish_event(event: Event) -> None:
    """Publie un event depuis n'importe quel contexte (boucle async, thread, sync)."""
    try:
        bus = get_event_bus()
        loop = _running_loop()
        if loop is not None:
            loop.create_task(_safe_publish(bus, event))
            return
        main = get_main_loop()
        if main is not None and main.is_running():
            asyncio.run_coroutine_threadsafe(_safe_publish(bus, event), main)
            return
        asyncio.run(_safe_publish(bus, event))
    except Exception:
        log.debug("publish_event erreur", exc_info=True)


def publish(event_type: str, payload: Dict[str, Any] | None = None, **kwargs: Any) -> Event:
    """Construit et publie un event en une ligne."""
    event = make_event(event_type, payload or {}, **kwargs)
    publish_event(event)
    return event

# ---------------------------------------------------------------------------
# Sondage défensif d'attributs (interfaces services développées en parallèle)
# ---------------------------------------------------------------------------

def try_import(module_name: str, attr_names: Iterable[str]) -> Dict[str, Any]:
    """Importe un module et retourne {attr: objet|None} sans jamais lever."""
    out: Dict[str, Any] = {a: None for a in attr_names}
    try:
        module = importlib.import_module(module_name)
    except Exception as exc:  # service pas encore écrit par l'agent parallèle
        log.debug("import %s indisponible: %s", module_name, exc)
        return out
    for attr in attr_names:
        out[attr] = getattr(module, attr, None)
    return out


def get_field(obj: Any, *names: str, default: Any = None) -> Any:
    """Lit obj[names[0]] ou obj.names[0]... en tolérant dict / objet / None."""
    if obj is None:
        return default
    for name in names:
        if isinstance(obj, dict):
            if name in obj and obj[name] is not None:
                return obj[name]
        else:
            value = getattr(obj, name, None)
            if value is not None:
                return value
    return default


def set_field(obj: Any, key: str, value: Any) -> None:
    """Écrit un champ sur un dict ou un objet, sans lever."""
    if obj is None:
        return
    if isinstance(obj, dict):
        obj[key] = value
        return
    try:
        setattr(obj, key, value)
    except Exception:
        pass


def as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def call_probe(obj: Any, method_name: str, *argsets: tuple, default: Any = None) -> Any:
    """Appelle obj.method_name(...) en essayant plusieurs signatures d'arguments."""
    if obj is None:
        return default
    func = getattr(obj, method_name, None)
    if not callable(func):
        return default
    argsets = argsets or (() ,)
    for args in argsets:
        try:
            return func(*args)
        except TypeError:
            continue
        except Exception:
            return default
    return default


def flex_call(func: Any, *args: Any, **kwargs: Any) -> Any:
    """Appelle func en essayant plusieurs formes de signature (args, kwargs filtrés)."""
    if func is None:
        raise TypeError("flex_call: func est None")
    try:
        sig = inspect.signature(func)
    except (ValueError, TypeError):
        try:
            return func(*args, **kwargs)
        except TypeError:
            return func(*args)
    params = list(sig.parameters.values())
    accepts_var_kw = any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params)
    named = {p.name for p in params
             if p.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD,
                           inspect.Parameter.KEYWORD_ONLY)}
    filtered = kwargs if accepts_var_kw else {k: v for k, v in kwargs.items() if k in named}
    try:
        return func(*args, **filtered)
    except TypeError:
        pass
    return func(*args)

# ---------------------------------------------------------------------------
# Révisions
# ---------------------------------------------------------------------------

def extract_rev(revision: Any) -> Optional[int]:
    """Extrait un numéro de révision d'un int / str / Revision / tuple."""
    if revision is None or isinstance(revision, bool):
        return None
    if isinstance(revision, int):
        return revision
    if isinstance(revision, float):
        return int(revision)
    if isinstance(revision, (tuple, list)):
        return extract_rev(revision[0]) if revision else None
    if isinstance(revision, str):
        digits = "".join(ch for ch in revision if ch.isdigit())
        return int(digits) if digits else None
    inner = get_field(revision, "rev", "revision", "number", "id", default=None)
    if inner is not None:
        return extract_rev(inner)
    return None


def revisions_list(versioning: Any) -> List[Dict[str, Any]]:
    """versioning.list() -> liste normalisée [{rev, message, author, ts}]."""
    if versioning is None:
        return []
    items = call_probe(versioning, "list")
    if not items:
        return []
    out: List[Dict[str, Any]] = []
    for item in items:
        out.append({
            "rev": extract_rev(item),
            "message": str(get_field(item, "message", default="")),
            "author": str(get_field(item, "author", default="")),
            "ts": get_field(item, "ts", "timestamp", "created_ts", default=None),
        })
    return out

# ---------------------------------------------------------------------------
# Géométrie défensive (bbox, pads, stats)
# ---------------------------------------------------------------------------

_FOOTPRINT_SIZES: Dict[str, Tuple[float, float]] = {
    "0402": (1.0, 0.5), "0603": (1.6, 0.8), "0805": (2.0, 1.25), "1206": (3.2, 1.6),
    "sot-23": (2.9, 1.6), "sot23": (2.9, 1.6), "soic-8": (5.0, 4.0), "soic8": (5.0, 4.0),
    "qfn-32": (5.0, 5.0), "qfn32": (5.0, 5.0), "qfp-64": (10.0, 10.0),
    "esp32-wroom-32e": (18.0, 25.5), "esp32": (18.0, 25.5), "bme680": (3.5, 3.0),
    "ams1117": (4.6, 3.5), "sop-8": (5.0, 4.0), "tssop-16": (5.0, 4.4),
}


def component_bbox(comp: Any) -> Tuple[float, float]:
    """(largeur, hauteur) estimée d'un composant, tolérante au format."""
    bbox = get_field(comp, "bbox_mm", "bbox", "size", default=None)
    if isinstance(bbox, (tuple, list)) and len(bbox) >= 2:
        try:
            return (as_float(bbox[0], 4.0), as_float(bbox[1], 4.0))
        except Exception:
            pass
    footprint = str(get_field(comp, "footprint", "package", default="") or "").lower()
    for key, size in _FOOTPRINT_SIZES.items():
        if key in footprint:
            return size
    ref = str(get_field(comp, "ref", "reference", default=""))
    if ref.upper().startswith("U") or ref.upper().startswith("J"):
        return (6.0, 6.0)
    return (2.0, 1.2)


def pad_names(comp: Any) -> List[str]:
    """Liste des noms de pads d'un composant (dicts, str ou objets)."""
    pads = get_field(comp, "pads", default=None)
    if not pads:
        return []
    names: List[str] = []
    if isinstance(pads, dict):
        return [str(k) for k in pads.keys()]
    for pad in pads:
        if isinstance(pad, dict):
            names.append(str(pad.get("name") or pad.get("pad") or ""))
        elif isinstance(pad, str):
            names.append(pad)
        else:
            names.append(str(get_field(pad, "name", "pad", default=pad)))
    return [n for n in names if n]


def _rect_of(comp: Any) -> Tuple[float, float, float, float]:
    x = as_float(get_field(comp, "x", "x_mm", "pos_x", default=0.0))
    y = as_float(get_field(comp, "y", "y_mm", "pos_y", default=0.0))
    w, h = component_bbox(comp)
    return (x - w / 2.0, y - h / 2.0, x + w / 2.0, y + h / 2.0)


def overlapping_components(graph: Any, clearance_mm: float = 0.2) -> List[Tuple[str, str]]:
    """Détecte les recouvrements de boîtes englobantes (contrôle ERC local)."""
    comps = get_field(graph, "components", default={}) or {}
    refs = list(comps.keys())
    rects = {ref: _rect_of(comps[ref]) for ref in refs}
    overlaps: List[Tuple[str, str]] = []
    for i, ref_a in enumerate(refs):
        for ref_b in refs[i + 1:]:
            a, b = rects[ref_a], rects[ref_b]
            if (a[0] < b[2] + clearance_mm and b[0] < a[2] + clearance_mm
                    and a[1] < b[3] + clearance_mm and b[1] < a[3] + clearance_mm):
                overlaps.append((ref_a, ref_b))
    return overlaps

# ---------------------------------------------------------------------------
# Sérialisation de graphes
# ---------------------------------------------------------------------------

def _dump_component(ref: str, comp: Any) -> Dict[str, Any]:
    pads = []
    for name in pad_names(comp):
        pads.append({"name": name})
    return {
        "ref": ref,
        "value": str(get_field(comp, "value", default="") or ""),
        "footprint": str(get_field(comp, "footprint", "package", default="") or ""),
        "mpn": str(get_field(comp, "mpn", "part_number", default="") or ""),
        "x": as_float(get_field(comp, "x", "x_mm", "pos_x", default=0.0)),
        "y": as_float(get_field(comp, "y", "y_mm", "pos_y", default=0.0)),
        "rotation": as_float(get_field(comp, "rotation", "rotation_deg", "rot", default=0.0)),
        "side": str(get_field(comp, "side", default="top") or "top"),
        "pads": pads,
        "power_w": as_float(get_field(comp, "power_w", "power", default=0.0)),
        "price_usd": as_float(get_field(comp, "price_usd", "price", default=0.0)),
    }


def _dump_net(net_id: str, net: Any) -> Dict[str, Any]:
    pins_raw = get_field(net, "pins", default=[]) or []
    pins: List[List[str]] = []
    for pin in pins_raw:
        if isinstance(pin, dict):
            pins.append([str(pin.get("ref", "")), str(pin.get("pad", ""))])
        elif isinstance(pin, (list, tuple)) and len(pin) >= 2:
            pins.append([str(pin[0]), str(pin[1])])
        else:
            pins.append([str(pin), "1"])
    return {
        "net_id": str(net_id),
        "name": str(get_field(net, "name", default=net_id) or net_id),
        "class_name": str(get_field(net, "class_name", "class", default="default") or "default"),
        "pins": pins,
        "routed": bool(get_field(net, "routed", default=False)),
    }


def serialize_graph(graph: Any) -> Dict[str, Any]:
    """Convertit un DesignGraph (réel ou duck-typé) en dict JSON-safe."""
    if graph is None:
        return {}
    if isinstance(graph, dict):
        return graph
    for method in ("to_dict", "as_dict"):
        func = getattr(graph, method, None)
        if callable(func):
            try:
                dumped = func()
                if isinstance(dumped, dict) and "components" in dumped:
                    return dumped
            except Exception:
                pass
    comps = get_field(graph, "components", default={}) or {}
    nets = get_field(graph, "nets", default={}) or {}
    out = {
        "project_id": str(get_field(graph, "project_id", default="") or ""),
        "board_size": list(get_field(graph, "board_size", "board_size_mm", default=(100.0, 80.0)) or (100.0, 80.0)),
        "layers": as_int(get_field(graph, "layers", default=2), 2),
        "components": {str(ref): _dump_component(str(ref), c) for ref, c in comps.items()},
        "nets": {str(nid): _dump_net(str(nid), n) for nid, n in nets.items()},
    }
    return out


def graph_stats(graph: Any) -> Dict[str, Any]:
    """Statistiques d'un graphe, en passant par graph.stats() si disponible."""
    if graph is None:
        return {"components": 0, "nets": 0}
    stats = call_probe(graph, "stats")
    if isinstance(stats, dict) and stats:
        return stats
    comps = get_field(graph, "components", default={}) or {}
    nets = get_field(graph, "nets", default={}) or {}
    unrouted = 0
    for net in nets.values():
        if not bool(get_field(net, "routed", default=False)):
            unrouted += 1
    return {"components": len(comps), "nets": len(nets), "unrouted": unrouted}


def deserialize_graph(data: Optional[Dict[str, Any]]) -> Any:
    """Reconstruit un graphe depuis un dict (DesignGraph réel si dispo, sinon duck-typé).

    Deux formats de snapshot coexistent et sont TOUS DEUX acceptés :
      - format canonique design_core (to_dict) : components/nets en LISTES ;
      - format duck-typé / SimpleDesignGraph : components/nets en DICTS.
    Le format canonique est rechargé via DesignGraph.from_dict (inverse exact
    de to_dict) — c'était le bug silencieux qui rendait les révisions
    sauvegardées par DesignStateManager illisibles.
    """
    if not data:
        return None
    comps = data.get("components") or {}
    nets = data.get("nets") or {}
    mods = try_import("services.design_core", ["DesignGraph"])
    cls = mods.get("DesignGraph")
    if cls is not None:
        # 1) format canonique (listes) → inverse exact de to_dict()
        if isinstance(comps, list) or isinstance(nets, list):
            try:
                graph = cls.from_dict(data)
                if graph is not None:
                    return graph
            except Exception:
                log.debug("DesignGraph.from_dict (format liste) impossible", exc_info=True)
        # 2) format duck-typé (dicts) → reconstruction add_component/add_net
        try:
            try:
                graph = cls()
            except TypeError:
                graph = cls(project_id=str(data.get("project_id") or "restored"))
            for ref, comp in comps.items():
                try:
                    flex_call(graph.add_component, ref, comp)
                except Exception:
                    try:
                        graph.add_component(ref)
                    except Exception:
                        pass
            for net_id, net in nets.items():
                payload = {k: v for k, v in (net or {}).items()
                           if k not in ("pins", "routed", "net_id")}
                try:
                    flex_call(graph.add_net, net_id, payload)
                except Exception:
                    try:
                        graph.add_net(net_id)
                    except Exception:
                        pass
            for ref, comp in comps.items():
                try:
                    graph.place(ref, as_float(get_field(comp, "x", default=0.0)),
                                as_float(get_field(comp, "y", default=0.0)),
                                as_float(get_field(comp, "rotation", default=0.0)))
                except Exception:
                    pass
            for net_id, net in nets.items():
                for pin in (net or {}).get("pins") or []:
                    try:
                        graph.connect(str(pin[0]), str(pin[1]), str(net_id))
                    except Exception:
                        pass
            return graph
        except Exception:
            log.debug("reconstruction DesignGraph impossible — fallback duck-typé", exc_info=True)
    return SimpleDesignGraph.from_dict(data)

# ---------------------------------------------------------------------------
# SimpleDesignGraph — implémentation duck-typée minimale (repli / tests)
# ---------------------------------------------------------------------------

class SimpleDesignGraph:
    """DesignGraph minimal compatible avec l'interface décrite des services.

    Implémente : components dict, nets dict, place(ref,x,y,rotation),
    connect(ref,pad,net_id), add_component, add_net, unrouted_nets(),
    total_wire_length(), stats(), copy(). Utilisé quand services.design_core
    n'est pas encore disponible (agents en parallèle) ou pour les tests.
    """

    def __init__(self, components: Optional[Dict[str, Dict[str, Any]]] = None,
                 nets: Optional[Dict[str, Dict[str, Any]]] = None,
                 board_size: Tuple[float, float] = (100.0, 80.0),
                 layers: int = 2, project_id: str = "") -> None:
        self.components: Dict[str, Dict[str, Any]] = components or {}
        self.nets: Dict[str, Dict[str, Any]] = nets or {}
        self.board_size = (float(board_size[0]), float(board_size[1]))
        self.layers = int(layers)
        self.project_id = project_id

    # -- construction ------------------------------------------------------
    def add_component(self, ref: str, payload: Any = None, **kw: Any) -> Dict[str, Any]:
        comp: Dict[str, Any] = {
            "ref": ref, "value": "", "footprint": "", "mpn": "",
            "x": 0.0, "y": 0.0, "rotation": 0.0, "side": "top",
            "pads": ["1", "2"], "power_w": 0.0, "price_usd": 0.0,
        }
        if isinstance(payload, dict):
            comp.update(payload)
        comp.update(kw)
        comp["ref"] = ref
        comp.setdefault("pads", ["1", "2"])
        self.components[ref] = comp
        return comp

    def add_net(self, net_id: str, payload: Any = None, **kw: Any) -> Dict[str, Any]:
        net: Dict[str, Any] = {
            "net_id": net_id, "name": net_id, "class_name": "default",
            "pins": [], "routed": False,
        }
        if isinstance(payload, dict):
            net.update(payload)
        net.update(kw)
        net["net_id"] = net_id
        net.setdefault("pins", [])
        self.nets[net_id] = net
        return net

    def connect(self, ref: str, pad: Any, net_id: str) -> None:
        if ref not in self.components:
            raise KeyError(f"composant inconnu: {ref}")
        net = self.nets.get(net_id) or self.add_net(net_id)
        pin = (ref, str(pad))
        if pin not in net["pins"]:
            net["pins"].append(pin)
        comp = self.components[ref]
        pads = comp.get("pads")
        if isinstance(pads, list) and str(pad) not in [str(p) for p in pads]:
            pads.append(pad)
        comp.setdefault("pad_nets", {})[str(pad)] = net_id

    def place(self, ref: str, x: float, y: float, rotation: float = 0.0) -> None:
        if ref not in self.components:
            raise KeyError(f"composant inconnu: {ref}")
        comp = self.components[ref]
        comp["x"], comp["y"], comp["rotation"] = float(x), float(y), float(rotation)

    # -- requêtes ----------------------------------------------------------
    def unrouted_nets(self) -> List[Dict[str, Any]]:
        return [n for n in self.nets.values() if not n.get("routed")]

    def total_wire_length(self) -> float:
        total = 0.0
        for net in self.nets.values():
            points: List[Tuple[float, float]] = []
            for ref, _pad in net.get("pins", []):
                comp = self.components.get(ref)
                if comp:
                    points.append((float(comp.get("x", 0.0)), float(comp.get("y", 0.0))))
            for i in range(1, len(points)):
                total += math.dist(points[i - 1], points[i])
        return round(total, 3)

    def stats(self) -> Dict[str, Any]:
        return {
            "components": len(self.components),
            "nets": len(self.nets),
            "unrouted": len(self.unrouted_nets()),
            "wire_length_mm": self.total_wire_length(),
            "board_size": list(self.board_size),
            "layers": self.layers,
        }

    # -- cycle de vie ------------------------------------------------------
    def copy(self) -> "SimpleDesignGraph":
        clone = json.loads(json.dumps(self.to_dict()))
        return SimpleDesignGraph.from_dict(clone)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "project_id": self.project_id,
            "board_size": list(self.board_size),
            "layers": self.layers,
            "components": json.loads(json.dumps(self.components, default=str)),
            "nets": json.loads(json.dumps(self.nets, default=str)),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SimpleDesignGraph":
        data = data or {}
        raw_comps = data.get("components") or {}
        comps = {}
        if isinstance(raw_comps, list):
            for comp in raw_comps:
                comp = dict(comp) if isinstance(comp, dict) else {"ref": str(comp)}
                ref = str(comp.get("ref") or len(comps))
                comp.setdefault("pads", ["1", "2"])
                comps[ref] = comp
        else:
            for ref, comp in raw_comps.items():
                comp = dict(comp) if isinstance(comp, dict) else {"ref": ref}
                comp.setdefault("pads", ["1", "2"])
                comps[ref] = comp
        raw_nets = data.get("nets") or {}
        nets = {}
        if isinstance(raw_nets, list):
            for net in raw_nets:
                net = dict(net) if isinstance(net, dict) else {"net_id": str(net)}
                net_id = str(net.get("net_id") or net.get("name") or len(nets))
                net.setdefault("pins", [])
                net.setdefault("routed", False)
                nets[net_id] = net
        else:
            for net_id, net in raw_nets.items():
                net = dict(net) if isinstance(net, dict) else {"net_id": net_id}
                net.setdefault("pins", [])
                net.setdefault("routed", False)
                nets[net_id] = net
        board = data.get("board_size") or data.get("board_size_mm") or (100.0, 80.0)
        return cls(components=comps, nets=nets,
                   board_size=(float(board[0]), float(board[1])),
                   layers=int(data.get("layers", 2) or 2),
                   project_id=str(data.get("project_id") or ""))

# ---------------------------------------------------------------------------
# Versioning + SharedMentalModel — instanciation défensive via le contexte
# ---------------------------------------------------------------------------

def ensure_versioning(context: Dict[str, Any]) -> Any:
    """Obtient (et met en cache dans le contexte) le DesignVersioning du projet."""
    if context.get("versioning") is not None:
        return context["versioning"]
    project_id = str(context.get("project_id") or "sans-projet")
    cls = try_import("services.design_core", ["DesignVersioning"]).get("DesignVersioning")
    if cls is None:
        return None
    try:
        try:
            versioning = cls(project_id)
        except TypeError:
            versioning = cls()
    except Exception as exc:
        log.debug("DesignVersioning indisponible: %s", exc)
        return None
    context["versioning"] = versioning
    return versioning


def ensure_smm(context: Dict[str, Any]) -> Any:
    """Obtient (et met en cache) le SharedMentalModel lié au graphe courant."""
    if context.get("smm") is not None:
        return context["smm"]
    graph = context.get("graph")
    if graph is None:
        return None
    cls = try_import("services.design_core", ["SharedMentalModel"]).get("SharedMentalModel")
    if cls is None:
        return None
    try:
        try:
            smm = cls(graph, context.get("intents"))
        except TypeError:
            smm = cls(graph)
    except Exception as exc:
        log.debug("SharedMentalModel indisponible: %s", exc)
        return None
    context["smm"] = smm
    return smm


def record_smm(context: Dict[str, Any], method: str, *argsets: tuple) -> None:
    """Enregistre une décision/trade-off dans le SMM (tolérant aux signatures)."""
    smm = ensure_smm(context)
    if smm is None:
        return
    call_probe(smm, method, *argsets)

# ---------------------------------------------------------------------------
# Persistance d'un paquet d'export (utilisé par l'API, MCP et l'agent manufacturing)
# ---------------------------------------------------------------------------

def _to_bytes(content: Any) -> bytes:
    if isinstance(content, bytes):
        return content
    if isinstance(content, str):
        return content.encode("utf-8")
    try:
        return json.dumps(content, indent=2, default=str).encode("utf-8")
    except Exception:
        return str(content).encode("utf-8")


def persist_export(export_id: str, tenant: str, project: str, result: Dict[str, Any],
                   fmt: str = "gerber", factory: str = "jlcpcb") -> Dict[str, Any]:
    """Écrit les fichiers d'un résultat d'export sur disque + zip. -> {files, dir, zip}."""
    base = data_root() / (tenant or "default") / (project or "sans-projet") / "exports" / export_id
    base.mkdir(parents=True, exist_ok=True)
    files: Dict[str, bytes] = {}
    files_field = result.get("files") if isinstance(result, dict) else None
    if isinstance(files_field, dict):
        for name, content in files_field.items():
            files[str(name)] = _to_bytes(content)
    elif isinstance(files_field, list):
        for item in files_field:
            if isinstance(item, dict):
                name = str(item.get("name") or item.get("filename") or new_id("file"))
                files[name] = _to_bytes(item.get("content") or item.get("data") or "")
    if not files and isinstance(result, dict) and result.get("path"):
        path = Path(str(result["path"]))
        if path.is_file():
            files[path.name] = path.read_bytes()
    if not files:
        files["result.json"] = _to_bytes(result)
    safe_files: Dict[str, bytes] = {}
    for name, content in files.items():
        safe = name.replace("/", "_").replace("\\", "_").replace("..", "_")
        safe_files[safe] = content
        (base / safe).write_bytes(content)
    (base / "manifest.json").write_text(json.dumps({
        "export_id": export_id, "format": fmt, "factory": factory,
        "files": list(safe_files.keys()), "ts": time.time(),
    }, indent=2), encoding="utf-8")
    zip_path = base / f"{export_id}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in safe_files.items():
            archive.writestr(name, content)
    return {"files": list(safe_files.keys()), "dir": str(base), "zip": str(zip_path)}
