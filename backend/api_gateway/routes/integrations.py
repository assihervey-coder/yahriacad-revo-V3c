"""Route intégrations EDA — ponts KiCad / Altium / sessions (pcb_plugin).

Fonctionnel de bout en bout :
  KiCad    : import netlist s-expr / PCB s-expr / schéma JSON / session PCB,
             export .kicad_pcb + netlist, hôte live push/pull WebSocket ;
  Altium   : import JSON pont, export JSON symétrique, synchronisation
             (détection changements locaux/distants + conflits) ;
  Sessions : sauvegarde atomique, listing, restauration (graphe + versioning).

Un import crée un VRAI projet (ProjectState) + design révision 0 + commit de
versioning : le design importé est immédiatement utilisable dans le designer,
les pipelines et les exports.
"""
from __future__ import annotations

import json
import time
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from shared.utilities import get_logger, new_id

from api_gateway.deps import get_tenant, get_user_id, get_versioning, load_project_graph
from api_gateway.middleware.tenant import safe_path_segment
from orchestrator.common import data_root
from orchestrator.state_manager import DesignStateManager, ProjectState

log = get_logger("api.integrations")

router = APIRouter(prefix="/api/v1/integrations", tags=["integrations"])


# ---------------------------------------------------------------- helpers
def _project_state(project_id: str, tenant: str, user: str) -> ProjectState:
    state = (ProjectState.load(project_id, tenant, user)
             or ProjectState.load(project_id, tenant, "default"))
    if state is None:
        raise HTTPException(status_code=404, detail=f"projet inconnu: {project_id}")
    return state


def _create_project_from_graph(graph: Any, name: str, tenant: str, user: str,
                               source: str) -> dict[str, Any]:
    """Crée un vrai projet + révision 0 + commit versioning depuis un import."""
    state = ProjectState.create(name=name or f"import_{new_id('p')}",
                                tenant_id=tenant, user_id=user)
    DesignStateManager().save_design(state.tenant_id, state.user_id,
                                     state.project_id, graph, 0)
    versioning = get_versioning(state.project_id)
    if versioning is not None:
        try:
            versioning.commit(graph, message=f"import {source}")
        except Exception:
            log.debug("commit versioning post-import impossible", exc_info=True)
    stats = {
        "components": len(getattr(graph, "components", {}) or {}),
        "nets": len(getattr(graph, "nets", {}) or {}),
        "routed": sum(1 for n in (getattr(graph, "nets", {}) or {}).values()
                      if bool(getattr(n, "routed", False))),
        "board_size": list(getattr(graph, "board_size", (50.0, 40.0)))[:2],
    }
    return {
        "project_id": state.project_id, "name": state.name,
        "tenant_id": state.tenant_id, "user_id": state.user_id,
        "source": source, "stats": stats,
    }


def _detect_and_parse(content: str) -> tuple[Any, str]:
    """Détecte le format (netlist KiCad / PCB KiCad / schéma JSON / session PCB)."""
    from services.parser import parse_pcb, parse_schematic
    from services.pcb_plugin.kicad import import_kicad_netlist, import_kicad_pcb

    text = str(content or "").strip()
    if not text:
        raise HTTPException(status_code=422, detail="contenu vide")

    if text.startswith("{") or text.startswith("["):
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=422, detail=f"JSON invalide: {exc}") from exc
        if isinstance(data, dict):
            # session PCB ré-importable (routes/placements) → parse_pcb
            if "routes" in data or "placements" in data or "board_size_mm" in data:
                return parse_pcb(data), "pcb_session"
            # schéma JSON (fils → nets) → parse_schematic
            if "wires" in data or "components" in data:
                return parse_schematic(data), "schematic"
            # pont Altium ? → délégué au endpoint dédié, mais toléré ici
            if "components" in data and "nets" in data:
                from services.pcb_plugin.altium import AltiumBridge

                return AltiumBridge().from_dict(data), "altium_json"
        raise HTTPException(status_code=422,
                            detail="JSON non reconnu (attendu: schéma, session PCB ou pont Altium)")

    # s-expression KiCad
    if text.startswith("(kicad_pcb"):
        return import_kicad_pcb(text), "kicad_pcb"
    if text.startswith("("):
        return import_kicad_netlist(text), "kicad_netlist"
    raise HTTPException(status_code=422,
                        detail="format non reconnu : attendu s-expression KiCad ou JSON")


def _write_export_file(tenant: str, user: str, project_id: str,
                       subdir: str, filename: str, content: str) -> str:
    """Écrit un artefact d'export sous data/projects/{tenant}/{user}/{project}/exports/."""
    out_dir = data_root() / safe_path_segment(tenant) / safe_path_segment(user) \
        / safe_path_segment(project_id) / "exports" / safe_path_segment(subdir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / filename
    path.write_text(content, encoding="utf-8")
    return str(path)


# ---------------------------------------------------------------- KiCad
class KiCadImportRequest(BaseModel):
    content: str = Field(..., description="netlist/PCB s-expression KiCad, schéma JSON ou session PCB")
    name: str = Field(default="", max_length=120)


@router.post("/kicad/import", status_code=201)
async def kicad_import(payload: KiCadImportRequest, request: Request) -> dict[str, Any]:
    """Import KiCad (netlist, .kicad_pcb, schéma JSON, session PCB) → vrai projet."""
    tenant = safe_path_segment(get_tenant(request))
    user = safe_path_segment(get_user_id(request))
    graph, fmt = _detect_and_parse(payload.content)
    name = payload.name or getattr(graph, "name", "") or f"import_kicad_{fmt}"
    result = _create_project_from_graph(graph, name, tenant, user, f"kicad:{fmt}")
    result["format"] = fmt
    return result


@router.get("/kicad/export/{project_id}")
async def kicad_export(project_id: str, request: Request,
                       fmt: str = "pcb") -> dict[str, Any]:
    """Exporte le design courant : .kicad_pcb (s-expr) et/ou netlist KiCad."""
    tenant, user = get_tenant(request), get_user_id(request)
    state = _project_state(project_id, tenant, user)
    graph, revision = load_project_graph(state.project_id, state.tenant_id, state.user_id)
    if graph is None:
        raise HTTPException(status_code=404, detail=f"aucun design pour {project_id}")

    from services.pcb_plugin.kicad import export_kicad_netlist, export_kicad_pcb

    outputs: dict[str, Any] = {}
    fmt_norm = (fmt or "pcb").lower()
    if fmt_norm in ("pcb", "both", "all"):
        content = export_kicad_pcb(graph)
        path = _write_export_file(state.tenant_id, state.user_id, state.project_id,
                                  "kicad", f"rev{revision}.kicad_pcb", content)
        outputs["pcb"] = {"path": path, "bytes": len(content), "preview": content[:600]}
    if fmt_norm in ("netlist", "both", "all"):
        content = export_kicad_netlist(graph)
        path = _write_export_file(state.tenant_id, state.user_id, state.project_id,
                                  "kicad", f"rev{revision}_netlist.net", content)
        outputs["netlist"] = {"path": path, "bytes": len(content), "preview": content[:400]}
    if not outputs:
        raise HTTPException(status_code=422, detail=f"fmt inconnu: {fmt} (pcb|netlist|both)")
    return {"project_id": state.project_id, "revision": revision,
            "files": outputs, "exported_at": time.time()}


class KiCadLiveRequest(BaseModel):
    project_id: str = ""
    ws_url: str = Field(default="ws://localhost:7999",
                        description="URL WebSocket du pont KiCad (pcbnew IPC)")


@router.post("/kicad/live/push")
async def kicad_live_push(payload: KiCadLiveRequest, request: Request) -> dict[str, Any]:
    """Pousse le design courant vers un KiCad à l'écoute (hôte live WebSocket)."""
    tenant, user = get_tenant(request), get_user_id(request)
    if not payload.project_id:
        raise HTTPException(status_code=422, detail="project_id requis")
    state = _project_state(payload.project_id, tenant, user)
    graph, revision = load_project_graph(state.project_id, state.tenant_id, state.user_id)
    if graph is None:
        raise HTTPException(status_code=404, detail=f"aucun design pour {state.project_id}")

    from services.pcb_plugin.kicad import KiCadLiveHost

    host = KiCadLiveHost(ws_url=payload.ws_url)
    connected = await host.connect()
    if not connected:
        return {"pushed": False, "connected": False,
                "detail": f"KiCad injoignable sur {payload.ws_url} — mode offline",
                "ws_url": payload.ws_url}
    pushed = await host.push_design(graph)
    await host.disconnect()
    return {"pushed": pushed, "connected": True,
            "project_id": state.project_id, "revision": revision,
            "ws_url": payload.ws_url}


@router.post("/kicad/live/pull", status_code=201)
async def kicad_live_pull(payload: KiCadLiveRequest, request: Request) -> dict[str, Any]:
    """Récupère le design depuis un KiCad live et l'importe comme projet."""
    tenant, user = get_tenant(request), get_user_id(request)
    from services.pcb_plugin.kicad import KiCadLiveHost

    host = KiCadLiveHost(ws_url=payload.ws_url)
    connected = await host.connect()
    if not connected:
        raise HTTPException(status_code=503,
                            detail=f"KiCad injoignable sur {payload.ws_url}")
    try:
        graph = await host.pull_design()
    finally:
        await host.disconnect()
    if graph is None:
        raise HTTPException(status_code=502, detail="KiCad n'a pas renvoyé de design")
    name = payload.project_id or getattr(graph, "name", "") or "kicad_live_pull"
    result = _create_project_from_graph(graph, name, tenant, user, "kicad:live_pull")
    result["connected"] = True
    return result


# ---------------------------------------------------------------- Altium
class AltiumImportRequest(BaseModel):
    payload: dict[str, Any] = Field(..., description="JSON du pont Altium {components, nets, ...}")
    name: str = Field(default="", max_length=120)


@router.post("/altium/import", status_code=201)
async def altium_import(payload: AltiumImportRequest, request: Request) -> dict[str, Any]:
    """Bridge Altium : JSON du pont → DesignGraph → vrai projet."""
    tenant = safe_path_segment(get_tenant(request))
    user = safe_path_segment(get_user_id(request))
    from services.pcb_plugin.altium import AltiumBridge

    try:
        graph = AltiumBridge().from_dict(payload.payload or {})
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"pont Altium invalide: {exc}") from exc
    if not (getattr(graph, "components", None) or getattr(graph, "nets", None)):
        raise HTTPException(status_code=422,
                            detail="design Altium vide (aucun composant ni net)")
    name = payload.name or getattr(graph, "name", "") or "altium_import"
    result = _create_project_from_graph(graph, name, tenant, user, "altium:json")
    return result


@router.get("/altium/export/{project_id}")
async def altium_export(project_id: str, request: Request,
                        save: bool = True) -> dict[str, Any]:
    """DesignGraph → JSON pont Altium (symétrique, ré-importable)."""
    tenant, user = get_tenant(request), get_user_id(request)
    state = _project_state(project_id, tenant, user)
    graph, revision = load_project_graph(state.project_id, state.tenant_id, state.user_id)
    if graph is None:
        raise HTTPException(status_code=404, detail=f"aucun design pour {project_id}")
    from services.pcb_plugin.altium import AltiumBridge

    data = AltiumBridge().export_altium(graph)
    response: dict[str, Any] = {"project_id": state.project_id, "revision": revision,
                                "payload": data}
    if save:
        path = _write_export_file(state.tenant_id, state.user_id, state.project_id,
                                  "altium", f"rev{revision}_altium.json",
                                  json.dumps(data, indent=2, default=str))
        response["file"] = {"path": path}
    return response


class AltiumSyncRequest(BaseModel):
    remote: dict[str, Any] = Field(..., description="état distant Altium (JSON pont)")
    resolution: str = Field(default="local_wins", pattern="^(local_wins|remote_wins)$")


@router.post("/altium/sync/{project_id}")
async def altium_sync(project_id: str, payload: AltiumSyncRequest,
                      request: Request) -> dict[str, Any]:
    """Synchronise le design local avec l'état Altium (conflits détectés)."""
    tenant, user = get_tenant(request), get_user_id(request)
    state = _project_state(project_id, tenant, user)
    graph, revision = load_project_graph(state.project_id, state.tenant_id, state.user_id)
    if graph is None:
        raise HTTPException(status_code=404, detail=f"aucun design pour {project_id}")
    from services.pcb_plugin.altium import AltiumBridge, AltiumSynchronizer

    bridge = AltiumBridge()
    try:
        bridge.remote_graph = bridge.from_dict(payload.remote or {})
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"état distant invalide: {exc}") from exc
    synchronizer = AltiumSynchronizer(bridge, resolution=payload.resolution)
    report = synchronizer.sync(graph)
    data = report.__dict__ if hasattr(report, "__dict__") else {"resolution": "init"}
    return {"project_id": state.project_id, "revision": revision,
            "sync": data}


# ---------------------------------------------------------------- Sessions
@router.post("/sessions/save/{project_id}")
async def session_save(project_id: str, request: Request) -> dict[str, Any]:
    """Sauvegarde atomique de la session (graphe + versioning) du projet."""
    tenant, user = get_tenant(request), get_user_id(request)
    state = _project_state(project_id, tenant, user)
    graph, revision = load_project_graph(state.project_id, state.tenant_id, state.user_id)
    if graph is None:
        raise HTTPException(status_code=404, detail=f"aucun design pour {project_id}")
    from services.pcb_plugin.session_restorer import SessionRestorer

    restorer = SessionRestorer(base_dir=str(data_root()))
    path = restorer.save_session(state.tenant_id, state.user_id, state.project_id,
                                 graph, versioning=get_versioning(state.project_id))
    return {"project_id": state.project_id, "saved": True, "path": str(path),
            "revision": revision}


@router.get("/sessions")
async def session_list(request: Request) -> dict[str, Any]:
    """Liste les sessions sauvegardées du tenant."""
    tenant = safe_path_segment(get_tenant(request))
    from services.pcb_plugin.session_restorer import SessionRestorer

    sessions = SessionRestorer(base_dir=str(data_root())).list_sessions(tenant)
    return {"tenant_id": tenant, "count": len(sessions), "sessions": sessions}


@router.get("/sessions/{project_id}/restore")
async def session_restore(project_id: str, request: Request,
                          apply: bool = False) -> dict[str, Any]:
    """Restaure la session d'un projet ; `apply=True` crée une révision courante."""
    tenant, user = get_tenant(request), get_user_id(request)
    state = _project_state(project_id, tenant, user)
    from services.pcb_plugin.session_restorer import SessionRestorer

    restored = SessionRestorer(base_dir=str(data_root())).restore_session(
        state.tenant_id, state.user_id, state.project_id)
    if restored is None:
        raise HTTPException(status_code=404,
                            detail=f"aucune session sauvegardée pour {project_id}")
    graph, versioning = restored
    response: dict[str, Any] = {
        "project_id": state.project_id,
        "restored": True,
        "stats": {"components": len(graph.components), "nets": len(graph.nets),
                  "routed": sum(1 for n in graph.nets.values() if bool(getattr(n, "routed", False))),
                  "board_size": list(graph.board_size)[:2]},
        "versioning_kind": type(versioning).__name__ if versioning is not None else None,
    }
    if apply:
        history = DesignStateManager().history(state.tenant_id, state.user_id,
                                               state.project_id)
        next_rev = (history[-1] + 1) if history else 0
        DesignStateManager().save_design(state.tenant_id, state.user_id,
                                         state.project_id, graph, next_rev)
        response["applied_revision"] = next_rev
    return response


# ---------------------------------------------------------------- Statut
@router.get("/status")
async def integrations_status() -> dict[str, Any]:
    """Capacités des ponts EDA (pour le dashboard Intégrations)."""
    return {
        "kicad": {
            "import": ["kicad_netlist", "kicad_pcb", "schematic", "pcb_session"],
            "export": ["kicad_pcb", "kicad_netlist"],
            "live": {"transport": "websocket", "default_url": "ws://localhost:7999",
                     "actions": ["push", "pull"]},
        },
        "altium": {
            "bridge": "json", "actions": ["import", "export", "sync"],
            "resolution": ["local_wins", "remote_wins"],
        },
        "sessions": {"actions": ["save", "list", "restore"],
                     "layout": "data/projects/{tenant}/{user}/{project}/session.json"},
    }
