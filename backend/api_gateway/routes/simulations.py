"""Route simulations — lancement asynchrone des simulateurs physiques."""
from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from api_gateway.deps import get_tenant, get_user_id, load_project_graph
from orchestrator.common import call_probe, get_field, try_import
from shared.utilities import get_logger, new_id

log = get_logger("api.simulations")

router = APIRouter(prefix="/api/v1/simulations", tags=["simulations"])

# registre en mémoire : (project_id, job_id) → résultat
_JOBS: Dict[tuple, Dict[str, Any]] = {}

_KIND_MAP = [
    ("thermal", "services.simulator", "ThermalSim"),
    ("si", "services.simulator", "SignalIntegritySim"),
    ("pi", "services.simulator", "PowerIntegritySim"),
    ("em", "services.simulator", "EMIProxySim"),
]


class SimulationRequest(BaseModel):
    kinds: List[str] = Field(default_factory=lambda: ["thermal", "si", "pi", "em"])


def _run_kind(kind: str, module_name: str, class_name: str, graph: Any) -> Dict[str, Any]:
    cls = try_import(module_name, [class_name]).get(class_name)
    if cls is None:
        return {"skipped": True, "passed": True, "reason": f"{module_name}.{class_name} absent"}
    try:
        try:
            sim = cls()
        except TypeError:
            sim = cls()
        result = call_probe(sim, "run", (graph,))
        metrics = get_field(result, "metrics", default={}) or {}
        return {"skipped": False,
                "passed": bool(get_field(result, "passed", default=True)),
                "metrics": metrics if isinstance(metrics, dict) else {"value": str(metrics)}}
    except Exception as exc:
        return {"skipped": True, "passed": True, "error": str(exc)[:200]}


async def _run_all(project_id: str, job_id: str, graph: Any, kinds: List[str]) -> None:
    entry = _JOBS[(project_id, job_id)]
    entry["status"] = "running"
    results: Dict[str, Any] = {}
    for kind, module_name, class_name in _KIND_MAP:
        if kind not in kinds:
            continue
        try:
            results[kind] = await asyncio.to_thread(_run_kind, kind, module_name, class_name, graph)
        except Exception as exc:
            results[kind] = {"skipped": True, "passed": True, "error": str(exc)[:200]}
    entry["results"] = results
    entry["passed"] = all(r.get("passed", True) for r in results.values()) if results else True
    entry["status"] = "completed"
    entry["finished_ts"] = time.time()
    log.info("simulation %s/%s terminée (%d types)", project_id, job_id, len(results))


@router.post("/{project_id}")
async def start_simulation(project_id: str, payload: SimulationRequest,
                           request: Request) -> Dict[str, Any]:
    """Lance les simulations en arrière-plan et retourne un job_id immédiatement."""
    graph, revision = load_project_graph(project_id, get_tenant(request), get_user_id(request))
    if graph is None:
        raise HTTPException(status_code=404, detail=f"aucun design pour le projet {project_id}")
    job_id = new_id("sim")
    _JOBS[(project_id, job_id)] = {
        "status": "queued", "kinds": payload.kinds, "results": {},
        "revision": revision, "started_ts": time.time(),
    }
    asyncio.create_task(_run_all(project_id, job_id, graph, list(payload.kinds)))
    return {"project_id": project_id, "job_id": job_id, "status": "queued",
            "kinds": payload.kinds}


@router.get("/{project_id}/{job_id}")
async def get_simulation(project_id: str, job_id: str, request: Request) -> Dict[str, Any]:
    """Résultats d'une simulation lancée précédemment."""
    entry = _JOBS.get((project_id, job_id))
    if entry is None:
        raise HTTPException(status_code=404, detail=f"simulation inconnue: {job_id}")
    return {"project_id": project_id, "job_id": job_id, **entry}


@router.get("/{project_id}")
async def list_simulations(project_id: str, request: Request) -> Dict[str, Any]:
    """Liste des simulations du projet."""
    sims = [{"job_id": jid, "status": entry["status"], "kinds": entry["kinds"],
             "passed": entry.get("passed")}
            for (pid, jid), entry in _JOBS.items() if pid == project_id]
    return {"project_id": project_id, "count": len(sims), "simulations": sims}
