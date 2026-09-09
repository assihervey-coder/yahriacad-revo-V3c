"""Route exports — ExportFacade + téléchargement (zip)."""
from __future__ import annotations

import contextlib
import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from shared.utilities import get_logger

from api_gateway.deps import get_tenant, get_user_id, load_project_graph
from orchestrator.common import (
    call_probe,
    data_root,
    flex_call,
    new_id,
    persist_export,
    serialize_graph,
    try_import,
)

log = get_logger("api.exports")

router = APIRouter(prefix="/api/v1/exports", tags=["exports"])

# registre mémoire des exports par projet : project_id → [export_id, ...]
_REGISTRY: dict[str, list[str]] = {}


class ExportRequest(BaseModel):
    fmt: str = Field(default="gerber")
    factory: str = Field(default="jlcpcb")


def create_export(project_id: str, tenant: str, graph: Any,
                  fmt: str = "gerber", factory: str = "jlcpcb") -> dict[str, Any]:
    """Exécute ExportFacade (ou repli JSON) et persiste les fichiers + zip."""
    export_id = new_id("exp")
    result: dict[str, Any] = {}
    facade_cls = try_import("services.exporter", ["ExportFacade"]).get("ExportFacade")
    if facade_cls is not None:
        try:
            try:
                facade = facade_cls()
            except TypeError:
                facade = facade_cls(factory=factory)
            raw = (call_probe(facade, "export", (graph, fmt), (graph,))
                   or flex_call(facade.export, graph, fmt=fmt, factory=factory))
            result = raw if isinstance(raw, dict) else {"result": str(raw)}
        except Exception as exc:
            log.debug("ExportFacade indisponible: %s", exc)
    if not result:
        result = {
            "files": {"design.json": json.dumps(serialize_graph(graph), indent=2, default=str)},
            "format": fmt, "fallback": True,
        }
    persisted = persist_export(export_id, tenant, project_id, result, fmt=fmt, factory=factory)
    _REGISTRY.setdefault(project_id, []).append(export_id)
    return {"export_id": export_id, "format": fmt, "factory": factory,
            "files": persisted["files"], "zip": persisted["zip"]}


def _export_dir(tenant: str, project_id: str, export_id: str) -> Path:
    return data_root() / tenant / project_id / "exports" / export_id


@router.post("/{project_id}")
async def post_export(project_id: str, payload: ExportRequest, request: Request) -> dict[str, Any]:
    """Exporte le design courant (gerber, json, ipc2581...) vers le factory."""
    tenant = get_tenant(request)
    graph, _rev = load_project_graph(project_id, tenant, get_user_id(request))
    if graph is None:
        raise HTTPException(status_code=404, detail=f"aucun design pour le projet {project_id}")
    return create_export(project_id, tenant, graph, fmt=payload.fmt, factory=payload.factory)


@router.get("/{project_id}")
async def list_exports(project_id: str, request: Request) -> dict[str, Any]:
    """Liste les exports du projet (mémoire + disque)."""
    tenant = get_tenant(request)
    known = list(_REGISTRY.get(project_id, []))
    base = data_root() / tenant / project_id / "exports"
    if base.is_dir():
        for child in base.iterdir():
            if child.is_dir() and child.name not in known:
                known.append(child.name)
    entries = []
    for export_id in known:
        manifest = _export_dir(tenant, project_id, export_id) / "manifest.json"
        info: dict[str, Any] = {"export_id": export_id}
        if manifest.is_file():
            with contextlib.suppress(Exception):
                info.update(json.loads(manifest.read_text(encoding="utf-8")))
        entries.append(info)
    return {"project_id": project_id, "count": len(entries), "exports": entries}


@router.get("/{project_id}/{export_id}")
async def download_export(project_id: str, export_id: str, request: Request) -> FileResponse:
    """Télécharge le paquet d'export (zip)."""
    tenant = get_tenant(request)
    directory = _export_dir(tenant, project_id, export_id)
    zip_path = directory / f"{export_id}.zip"
    if not zip_path.is_file():
        if directory.is_dir():
            files = [p for p in directory.iterdir() if p.is_file()]
            if files:
                import zipfile

                with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
                    for file in files:
                        archive.writestr(file.name, file.read_bytes())
        else:
            raise HTTPException(status_code=404, detail=f"export inconnu: {export_id}")
    return FileResponse(path=str(zip_path), media_type="application/zip",
                        filename=f"{export_id}.zip")
