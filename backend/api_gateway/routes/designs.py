"""Route designs — graphe courant (DesignSchema), révisions manuelles, restore."""
from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from shared.schemas import (
    ComponentSchema,
    DesignSchema,
    LayerSchema,
    NetSchema,
)
from shared.schemas.design_schemas import LayerType, PadSchema
from shared.utilities import get_logger

from api_gateway.deps import get_tenant, get_user_id, get_versioning, load_project_graph
from orchestrator.common import (
    deserialize_graph,
    extract_rev,
    get_field,
    graph_stats,
    revisions_list,
)
from orchestrator.state_manager import DesignStateManager, ProjectState

log = get_logger("api.designs")

router = APIRouter(prefix="/api/v1/designs", tags=["designs"])


class RevisionCreate(BaseModel):
    message: str = Field(default="commit manuel")
    graph: dict[str, Any] | None = Field(default=None,
                                            description="graphe sérialisé (sinon design courant)")


def graph_to_design_schema(project_id: str, graph: Any, revision: int) -> DesignSchema:
    """Conversion défensive graph → DesignSchema (composants/nets/layers)."""
    components: list[ComponentSchema] = []
    for ref, comp in (get_field(graph, "components", default={}) or {}).items():
        try:
            pads: list[PadSchema] = []
            for pad in (get_field(comp, "pads", default=[]) or []):
                if isinstance(pad, dict):
                    pads.append(PadSchema(
                        name=str(pad.get("name") or pad.get("pad") or ""),
                        x_mm=float(pad.get("x_mm", pad.get("x", 0.0)) or 0.0),
                        y_mm=float(pad.get("y_mm", pad.get("y", 0.0)) or 0.0),
                        width_mm=float(pad.get("width_mm", 0.6) or 0.6),
                        height_mm=float(pad.get("height_mm", 0.6) or 0.6),
                        net_id=pad.get("net_id"),
                        layer=int(pad.get("layer", 0) or 0),
                    ))
                else:
                    pads.append(PadSchema(name=str(pad)))
            bbox = get_field(comp, "bbox_mm", "bbox", default=(1.0, 0.5)) or (1.0, 0.5)
            components.append(ComponentSchema(
                ref=str(ref),
                value=str(get_field(comp, "value", default="") or ""),
                footprint=str(get_field(comp, "footprint", "package", default="") or ""),
                mpn=str(get_field(comp, "mpn", "part_number", default="") or ""),
                x_mm=float(get_field(comp, "x", "x_mm", "pos_x", default=0.0) or 0.0),
                y_mm=float(get_field(comp, "y", "y_mm", "pos_y", default=0.0) or 0.0),
                rotation_deg=float(get_field(comp, "rotation", "rotation_deg", "rot", default=0.0) or 0.0),
                side=str(get_field(comp, "side", default="top") or "top"),
                bbox_mm=(float(bbox[0]), float(bbox[1])),
                pads=pads,
                power_w=float(get_field(comp, "power_w", "power", default=0.0) or 0.0),
                price_usd=float(get_field(comp, "price_usd", "price", default=0.0) or 0.0),
            ))
        except Exception:
            log.debug("conversion composant %s ignorée", ref, exc_info=True)

    nets: list[NetSchema] = []
    for net_id, net in (get_field(graph, "nets", default={}) or {}).items():
        try:
            pins: list[tuple] = []
            for pin in (get_field(net, "pins", default=[]) or []):
                if isinstance(pin, dict):
                    pins.append((str(pin.get("ref", "")), str(pin.get("pad", ""))))
                elif isinstance(pin, (list, tuple)) and len(pin) >= 2:
                    pins.append((str(pin[0]), str(pin[1])))
            impedance = get_field(net, "impedance_target_ohm", "impedance", default=None)
            max_len = get_field(net, "max_length_mm", default=None)
            nets.append(NetSchema(
                net_id=str(net_id),
                name=str(get_field(net, "name", default=net_id) or net_id),
                class_name=str(get_field(net, "class_name", "class", default="default") or "default"),
                pins=pins,
                impedance_target_ohm=float(impedance) if impedance is not None else None,
                max_length_mm=float(max_len) if max_len is not None else None,
                matched_group=get_field(net, "matched_group", default=None),
                routed=bool(get_field(net, "routed", default=False)),
            ))
        except Exception:
            log.debug("conversion net %s ignorée", net_id, exc_info=True)

    board = get_field(graph, "board_size", "board_size_mm", default=(100.0, 80.0)) or (100.0, 80.0)
    if isinstance(board, dict):
        board = (board.get("w", 100.0), board.get("h", 80.0))
    layers_raw = get_field(graph, "layers", default=None)
    if isinstance(layers_raw, list) and layers_raw and not isinstance(layers_raw[0], int):
        layers = [LayerSchema(index=i, name=str(get_field(layer, "name", default=f"L{i}")),
                              type=LayerType(get_field(layer, "type", default="signal")))
                  for i, layer in enumerate(layers_raw)]
    else:
        layers = [
            LayerSchema(index=0, name="F.Cu"),
            LayerSchema(index=1, name="GND", type=LayerType.GROUND),
            LayerSchema(index=2, name="PWR", type=LayerType.POWER),
            LayerSchema(index=3, name="B.Cu"),
        ]
    layers_count = get_field(graph, "layers", default=4)
    if isinstance(layers_count, int) and layers_count != len(layers):
        layers = layers[:max(2, min(layers_count, len(layers)))]

    name = project_id
    try:
        state = ProjectState.load(project_id)
        if state is not None:
            name = state.name
    except Exception:
        pass

    return DesignSchema(
        project_id=project_id,
        name=name,
        revision=int(revision or 0),
        board_size_mm=(float(board[0]), float(board[1])),
        layers=layers,
        components=components,
        nets=nets,
    )


@router.get("/{project_id}", response_model=DesignSchema)
async def get_design(project_id: str, request: Request) -> DesignSchema:
    """DesignSchema du graphe courant du projet."""
    tenant = get_tenant(request)
    graph, revision = load_project_graph(project_id, tenant, get_user_id(request))
    if graph is None:
        raise HTTPException(status_code=404, detail=f"aucun design pour le projet {project_id}")
    return graph_to_design_schema(project_id, graph, revision)


@router.get("/{project_id}/stats")
async def get_design_stats(project_id: str, request: Request) -> dict[str, Any]:
    """Statistiques compactes du design courant."""
    graph, revision = load_project_graph(project_id, get_tenant(request), get_user_id(request))
    if graph is None:
        raise HTTPException(status_code=404, detail=f"aucun design pour le projet {project_id}")
    return {"project_id": project_id, "revision": revision, "stats": graph_stats(graph)}


@router.post("/{project_id}/revisions")
async def commit_revision(project_id: str, payload: RevisionCreate,
                          request: Request) -> dict[str, Any]:
    """Commit manuel : le graphe fourni (ou courant) devient une nouvelle révision."""
    tenant = get_tenant(request)
    user = get_user_id(request)
    state = ProjectState.load(project_id, tenant, user) or ProjectState.load(project_id, tenant, "default")
    if state is None:
        raise HTTPException(status_code=404, detail=f"projet inconnu: {project_id}")

    manager = DesignStateManager()
    history = manager.history(state.tenant_id, state.user_id, state.project_id)
    next_rev = (history[-1] + 1) if history else 0

    graph = None
    if payload.graph:
        graph = deserialize_graph(payload.graph)
    if graph is None:
        graph, _rev = load_project_graph(project_id, state.tenant_id, state.user_id)
    if graph is None:
        raise HTTPException(status_code=422, detail="aucun graphe à committer")

    revision_committed: int | None = None
    versioning = get_versioning(project_id)
    if versioning is not None:
        try:
            revision_committed = extract_rev(
                versioning.commit(graph, payload.message, author=f"user:{user}"))
        except Exception as exc:
            log.debug("commit versioning impossible: %s", exc)
    manager.save_design(state.tenant_id, state.user_id, state.project_id, graph,
                        revision_committed if revision_committed is not None else next_rev)
    try:
        state.last_rev = revision_committed if revision_committed is not None else next_rev
        state.save()
    except Exception:
        pass
    return {"project_id": project_id,
            "revision": revision_committed if revision_committed is not None else next_rev,
            "message": payload.message, "ts": time.time()}


@router.get("/{project_id}/revisions")
async def list_revisions(project_id: str, request: Request) -> dict[str, Any]:
    """Liste des révisions (versioning si dispo, sinon état persisté)."""
    tenant = get_tenant(request)
    user = get_user_id(request)
    state = ProjectState.load(project_id, tenant, user) or ProjectState.load(project_id, tenant, "default")
    if state is None:
        raise HTTPException(status_code=404, detail=f"projet inconnu: {project_id}")
    revisions: list[dict[str, Any]] = []
    versioning = get_versioning(project_id)
    if versioning is not None:
        revisions = revisions_list(versioning)
    if not revisions:
        manager = DesignStateManager()
        revisions = [{"rev": rev, "message": "", "author": "", "ts": None}
                     for rev in manager.history(state.tenant_id, state.user_id, state.project_id)]
    return {"project_id": project_id, "count": len(revisions), "revisions": revisions}


@router.post("/{project_id}/revisions/{rev}/restore")
async def restore_revision(project_id: str, rev: int, request: Request) -> dict[str, Any]:
    """Restaure une révision comme design courant."""
    tenant = get_tenant(request)
    user = get_user_id(request)
    state = ProjectState.load(project_id, tenant, user) or ProjectState.load(project_id, tenant, "default")
    if state is None:
        raise HTTPException(status_code=404, detail=f"projet inconnu: {project_id}")

    graph = None
    versioning = get_versioning(project_id)
    if versioning is not None:
        try:
            graph = versioning.restore(int(rev))
        except Exception as exc:
            log.debug("restore versioning(%s) impossible: %s", rev, exc)
    if graph is None:
        loaded = DesignStateManager().load_revision(state.tenant_id, state.user_id,
                                                    state.project_id, int(rev))
        if loaded is not None:
            graph = loaded[0]
    if graph is None:
        raise HTTPException(status_code=404, detail=f"révision {rev} introuvable")
    DesignStateManager().save_design(state.tenant_id, state.user_id, state.project_id, graph, int(rev))
    return {"project_id": project_id, "restored": int(rev), "stats": graph_stats(graph)}
