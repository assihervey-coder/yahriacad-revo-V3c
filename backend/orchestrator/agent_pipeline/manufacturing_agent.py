"""ManufacturingAgent — analyse DFM, package de fabrication et exports."""
from __future__ import annotations

import json
from typing import Any

from shared.contracts import AgentRole
from shared.events import EventTypes
from shared.schemas import AgentResultSchema
from shared.utilities import new_id

from orchestrator.agent_pipeline.base import BaseAgent
from orchestrator.common import (
    call_probe,
    flex_call,
    get_field,
    persist_export,
    try_import,
)


class ManufacturingAgent(BaseAgent):
    """Étapes `manufacture` (analyse + package) et `export` (ExportFacade)."""

    role = AgentRole.MANUFACTURING
    description = "Analyse manufacturabilité, prépare le package et exporte les fichiers."

    def __init__(self, orchestrator: Any = None) -> None:
        super().__init__(AgentRole.MANUFACTURING, "manufacturing", orchestrator)

    def supports(self, action: str) -> bool:
        return action in ("analyze_and_package", "manufacture", "export_design", "export", "")

    def execute(self, context: dict[str, Any]) -> AgentResultSchema:
        action = str(context.get("action") or "analyze_and_package")
        if action == "export_design":
            return self._export(context)
        return self._analyze_and_package(context)

    # ------------------------------------------------------------------ DFM
    def _analyze_and_package(self, context: dict[str, Any]) -> AgentResultSchema:
        graph = context.get("graph")
        if graph is None:
            return self.failed(context, "aucun DesignGraph dans le contexte")
        params = context.get("params") or {}
        factory = str(params.get("factory") or "jlcpcb")

        analysis: dict[str, Any] = {}
        mi_mod = try_import("services.manufacturing_intelligence", ["ManufacturingIntelligence"])
        mi_cls = mi_mod.get("ManufacturingIntelligence")
        if mi_cls is not None:
            try:
                try:
                    mi = mi_cls()
                except TypeError:
                    mi = mi_cls(self.orchestrator)
                raw = call_probe(mi, "analyze", (graph, factory), (graph,))
                analysis = raw if isinstance(raw, dict) else {"result": str(raw)}
            except Exception as exc:
                self.log.debug("ManufacturingIntelligence indisponible: %s", exc)
        if not analysis:
            analysis = self._local_analysis(graph, factory)

        package_info: dict[str, Any] = {}
        exp_mod = try_import("services.exporter", ["ManufacturingPackage"])
        pkg_cls = exp_mod.get("ManufacturingPackage")
        if pkg_cls is not None:
            try:
                try:
                    package = pkg_cls()
                except TypeError:
                    package = pkg_cls(factory=factory)
                built = (call_probe(package, "build", (graph,), (graph, factory))
                         or call_probe(package, "create", (graph,)))
                package_info = built if isinstance(built, dict) else {"package": str(built)}
            except Exception as exc:
                self.log.debug("ManufacturingPackage indisponible: %s", exc)
        if not package_info:
            package_info = {"status": "pending_export", "factory": factory}

        output = {"analysis": analysis, "package_info": package_info, "factory": factory}
        context["manufacturing"] = output
        self.record_decision(context, "manufacturing",
                             f"analyse {factory}: {json.dumps(analysis, default=str)[:150]}",
                             confidence=0.8)
        self.emit(EventTypes.MANUFACTURING_READY, {"factory": factory}, context)
        return self.succeeded(context, output, confidence=0.8,
                              rationale=f"analyse DFM {factory} + package")

    # --------------------------------------------------------------- export
    def _export(self, context: dict[str, Any]) -> AgentResultSchema:
        graph = context.get("graph")
        if graph is None:
            return self.failed(context, "aucun DesignGraph dans le contexte")
        params = context.get("params") or {}
        fmt = str(params.get("fmt") or params.get("format") or "gerber")
        factory = str(params.get("factory") or "jlcpcb")

        export_result: dict[str, Any] = {}
        exp_mod = try_import("services.exporter", ["ExportFacade"])
        facade_cls = exp_mod.get("ExportFacade")
        if facade_cls is not None:
            try:
                try:
                    facade = facade_cls()
                except TypeError:
                    facade = facade_cls(factory=factory)
                raw = (call_probe(facade, "export", (graph, fmt), (graph,))
                       or flex_call(facade.export, graph, fmt=fmt, factory=factory))
                export_result = raw if isinstance(raw, dict) else {"result": str(raw)}
            except Exception as exc:
                self.log.debug("ExportFacade indisponible: %s", exc)
        if not export_result:
            from orchestrator.common import serialize_graph

            export_result = {
                "files": {
                    "design.json": json.dumps(serialize_graph(graph), indent=2, default=str),
                },
                "format": fmt,
                "fallback": True,
            }

        export_id = new_id("exp")
        persisted = persist_export(export_id, str(context.get("tenant_id") or "default"),
                                   str(context.get("project_id") or "sans-projet"),
                                   export_result, fmt=fmt, factory=factory)
        output = {"export_id": export_id, "format": fmt, "factory": factory,
                  "files": persisted["files"], "dir": persisted["dir"],
                  "zip": persisted["zip"]}
        context["export_result"] = output
        self.record_decision(context, "export", f"{fmt} via {factory} ({len(persisted['files'])} fichiers)",
                             confidence=0.8)
        self.emit(EventTypes.EXPORT_COMPLETED, {"export_id": export_id,
                                                "format": fmt,
                                                "files": len(persisted["files"])}, context)
        return self.succeeded(context, output, confidence=0.8,
                              rationale=f"export {fmt} ({len(persisted['files'])} fichiers)")

    # --------------------------------------------------------------- repli
    def _local_analysis(self, graph: Any, factory: str) -> dict[str, Any]:
        """Estimation de coût/yield locale si manufacturing_intelligence est absent."""
        comps = get_field(graph, "components", default={}) or {}
        nets = get_field(graph, "nets", default={}) or {}
        component_cost = sum(float(get_field(c, "price_usd", "price", default=0.0) or 0.0)
                             for c in comps.values())
        board = get_field(graph, "board_size", "board_size_mm", default=(100.0, 80.0)) or (100.0, 80.0)
        area = float(board[0]) * float(board[1]) / 100.0  # cm²
        pcb_cost = 5.0 + 0.02 * area
        return {
            "engine": "local_estimate",
            "factory": factory,
            "components": len(comps),
            "nets": len(nets),
            "board_area_cm2": round(area, 2),
            "estimated_cost_usd": round(component_cost + pcb_cost, 2),
            "estimated_yield": 0.95,
        }
