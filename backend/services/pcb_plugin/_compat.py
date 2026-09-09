"""Pont de compatibilité vers services.design_core (développé en parallèle).

design_core est la source de vérité : DesignGraph, Component, Net, Pad, Layer.
Ce module reconstruit ces objets depuis des dictionnaires en essayant les API
officielles (`from_dict`, pydantic, dataclass) avant une construction filtrée
par signature. Aucune recréation du modèle : on s'adapte à l'interface publiée.
"""
from __future__ import annotations

import dataclasses
import importlib
import inspect
from typing import Any

from shared.geometry import Point, RoutePath
from shared.utilities import get_logger

log = get_logger(__name__)

_CORE_NAMES = ("DesignGraph", "Component", "Net", "Pad", "Layer", "DesignVersioning")
_cache: dict[str, Any] = {}


def _core_module():
    """Importe design_core (réessaie à chaque appel tant que 2-a n'a pas fini)."""
    return importlib.import_module("services.design_core")


def core_classes() -> tuple[Any, ...]:
    """(DesignGraph, Component, Net, Pad, Layer, DesignVersioning) — None si absent."""
    module = _core_module()
    out: list[Any] = []
    for name in _CORE_NAMES:
        if name not in _cache:
            _cache[name] = getattr(module, name, None)
        out.append(_cache[name])
    return tuple(out)


def _build(obj_cls: Any, data: Any) -> Any:
    """Construit `obj_cls` depuis un dict : pydantic > from_dict > dataclass > signature."""
    if obj_cls is None:
        raise TypeError("classe design_core indisponible")
    if not isinstance(data, dict):
        return data
    for meth in ("model_validate", "parse_obj", "from_dict"):
        fn = getattr(obj_cls, meth, None)
        if callable(fn):
            try:
                return fn(data)
            except Exception:  # on tente les stratégies suivantes
                continue
    if dataclasses.is_dataclass(obj_cls) and isinstance(obj_cls, type):
        names = {f.name for f in dataclasses.fields(obj_cls)}
        return obj_cls(**{k: v for k, v in data.items() if k in names})
    try:
        target = obj_cls.__init__ if isinstance(obj_cls, type) else obj_cls
        params = {p for p in inspect.signature(target).parameters if p != "self"}
        return obj_cls(**{k: v for k, v in data.items() if k in params})
    except Exception as exc:
        raise ValueError(f"construction {obj_cls!r} impossible depuis {data!r}") from exc


def _point(v: Any) -> Point:
    if isinstance(v, Point):
        return v
    if isinstance(v, dict):
        return Point(float(v["x"]), float(v["y"]))
    return Point.from_tuple(v)


def route_from_dict(data: dict[str, Any], net_id: str = "") -> RoutePath:
    """Reconstruit un RoutePath (shared.geometry) depuis un dict sérialisé."""
    points = [_point(p) for p in (data.get("points") or [])]
    vias: list[tuple[Point, int, int]] = []
    for v in data.get("vias") or []:
        if isinstance(v, dict):
            vias.append((_point(v.get("pos", v)), int(v.get("from_layer", 0)), int(v.get("to_layer", 1))))
        elif isinstance(v, (list, tuple)) and len(v) >= 2:
            vias.append((_point(v[0]), int(v[1]), int(v[2]) if len(v) > 2 else 1))
    return RoutePath(
        net_id=str(data.get("net_id", net_id)),
        points=points,
        layer=int(data.get("layer", 0)),
        width_mm=float(data.get("width_mm", 0.2)),
        vias=vias,
    )


def graph_to_dict(graph: Any) -> dict[str, Any]:
    """Sérialise un DesignGraph (to_dict officiel, fallback dataclass)."""
    to_dict = getattr(graph, "to_dict", None)
    if callable(to_dict):
        return to_dict()
    if dataclasses.is_dataclass(graph):
        return dataclasses.asdict(graph)
    raise TypeError("graph non sérialisable (ni to_dict ni dataclass)")


def _board_size(v: Any) -> tuple[float, float]:
    if isinstance(v, dict):
        return (float(v.get("w", v.get("width", 0.0))), float(v.get("h", v.get("height", 0.0))))
    if isinstance(v, (list, tuple)) and len(v) >= 2:
        return (float(v[0]), float(v[1]))
    return (50.0, 40.0)


def _iter_components(d: dict[str, Any]):
    """Composants du snapshot : design_core sérialise en LISTE (tolère dict)."""
    comps = d.get("components") or {}
    if isinstance(comps, dict):
        for ref, cdata in comps.items():
            yield ref, cdata
    else:
        for cdata in comps:
            yield str((cdata or {}).get("ref", "")), cdata


def _iter_nets(d: dict[str, Any]):
    """Nets du snapshot : LISTE chez design_core (tolère dict)."""
    nets = d.get("nets") or {}
    if isinstance(nets, dict):
        for nid, ndata in nets.items():
            yield str(nid), ndata
    else:
        for ndata in nets:
            yield str((ndata or {}).get("net_id", "")), ndata


def graph_from_dict(d: dict[str, Any]) -> Any:
    """Reconstruit un DesignGraph depuis son dict (API officielle d'abord)."""
    DG, Comp, Net, Pad, Layer, _ = core_classes()
    if DG is None:
        raise ImportError("services.design_core.DesignGraph indisponible")

    for meth in ("from_dict", "parse_obj", "model_validate"):
        fn = getattr(DG, meth, None)
        if callable(fn):
            try:
                return fn(d)
            except Exception:
                continue

    components: dict[str, Any] = {}
    for ref, cdata in _iter_components(d):
        cdict = dict(cdata or {})
        pads = cdict.pop("pads", None)
        if isinstance(pads, list):
            cdict["pads"] = [_build(Pad, p) if isinstance(p, dict) else p for p in pads]
        comp = _build(Comp, cdict)
        key = getattr(comp, "ref", None) or ref
        components[str(key)] = comp

    nets: dict[str, Any] = {}
    for nid, ndata in _iter_nets(d):
        ndict = dict(ndata or {})
        path = ndict.get("path")
        if isinstance(path, dict):
            ndict["path"] = route_from_dict(path, nid)
        elif path is None:
            ndict["path"] = RoutePath(net_id=nid, points=[], layer=0, width_mm=0.2, vias=[])
        net = _build(Net, ndict)
        key = getattr(net, "net_id", None) or nid
        nets[str(key)] = net

    layers = [_build(Layer, ly) if isinstance(ly, dict) else ly for ly in (d.get("layers") or [])]

    kwargs: dict[str, Any] = {
        "project_id": d.get("project_id", ""),
        "name": d.get("name", ""),
        "board_size": _board_size(d.get("board_size", (50.0, 40.0))),
    }
    if components:
        kwargs["components"] = components
    if nets:
        kwargs["nets"] = nets
    if layers:
        kwargs["layers"] = layers
    return _build(DG, kwargs)


def new_graph(project_id: str, name: str, board_size: tuple[float, float],
              components: dict[str, Any] | None = None,
              nets: dict[str, Any] | None = None,
              layers: list[Any] | None = None) -> Any:
    """Construit un DesignGraph via son constructeur (champs filtrés)."""
    DG = core_classes()[0]
    if DG is None:
        raise ImportError("services.design_core.DesignGraph indisponible")
    kwargs: dict[str, Any] = {
        "project_id": project_id,
        "name": name,
        "board_size": board_size,
    }
    if components is not None:
        kwargs["components"] = components
    if nets is not None:
        kwargs["nets"] = nets
    if layers:
        kwargs["layers"] = layers
    return _build(DG, kwargs)


def versioning_to_dict(versioning: Any) -> dict[str, Any]:
    """Sérialise un DesignVersioning duck-typed (to_dict/snapshot/export)."""
    if versioning is None:
        return {}
    for name in ("to_dict", "snapshot", "export"):
        fn = getattr(versioning, name, None)
        if callable(fn):
            try:
                return fn()
            except Exception:
                continue
    if dataclasses.is_dataclass(versioning):
        return dataclasses.asdict(versioning)
    return {"repr": repr(versioning)}


def versioning_from_dict(data: dict[str, Any] | None) -> Any:
    """Restaure un DesignVersioning (best-effort, jamais bloquant)."""
    if not data:
        return None
    try:
        DV = core_classes()[5]
    except ImportError:
        DV = None
    if DV is None:
        log.warning("DesignVersioning indisponible — versioning non restauré")
        return None
    for meth in ("from_dict", "parse_obj", "model_validate"):
        fn = getattr(DV, meth, None)
        if callable(fn):
            try:
                return fn(data)
            except Exception:
                continue
    try:
        return _build(DV, data)
    except Exception:
        log.warning("DesignVersioning non restaurable — instance neuve")
        try:
            return DV()
        except Exception:
            return None
