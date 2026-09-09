"""SelectorAgent — sélection des composants + construction du DesignGraph."""
from __future__ import annotations

import json
import re
from typing import Any

from shared.contracts import AgentRole
from shared.schemas import AgentResultSchema

from orchestrator.agent_pipeline.base import BaseAgent
from orchestrator.common import (
    SimpleDesignGraph,
    call_probe,
    flex_call,
    get_field,
    pad_names,
    set_field,
    try_import,
)

_POWER_ALIASES = {
    "gnd": "GND", "vss": "GND", "agnd": "GND", "pgnd": "GND",
    "vcc": "VCC", "vdd": "VCC", "3v3": "VCC", "3.3v": "VCC", "5v": "VCC", "avdd": "VCC",
}


class SelectorAgent(BaseAgent):
    """Étape `select` : hints → ComponentLibMatcher → graph (composants + nets)."""

    role = AgentRole.SELECTOR
    description = "Sélectionne les composants et construit le DesignGraph initial."

    def __init__(self, orchestrator: Any = None) -> None:
        super().__init__(AgentRole.SELECTOR, "selector", orchestrator)
        self._ref_counters: dict[str, int] = {}

    def supports(self, action: str) -> bool:
        return action in ("select_components", "select", "build_graph", "")

    # ------------------------------------------------------------------ main
    def execute(self, context: dict[str, Any]) -> AgentResultSchema:
        message = str(context.get("message") or "")
        graph = context.get("graph")
        built_with = "existing"

        # 1) Construction via NLToSkidl (chemin nominal des services)
        if message and (graph is None or not self._components_of(graph)):
            skidl_graph = self._graph_from_skidl(message)
            if skidl_graph is not None:
                graph = skidl_graph
                built_with = "nl_to_skidl"

        # 2) Graphe neuf si toujours rien
        if graph is None:
            graph = self._new_graph(context)
            built_with = built_with if built_with != "existing" else self._graph_kind(graph)

        hints = self._hints(context)
        matched, total = 0, 0
        added: list[str] = []

        # 3) Sélection via ComponentLibMatcher pour chaque hint
        if hints:
            matcher = self._matcher()
            for hint in hints:
                total += 1
                selection = self._match(matcher, hint)
                ref = self._next_ref(selection, hint)
                payload = self._payload_from(selection, hint)
                try:
                    flex_call(graph.add_component, ref, payload)
                except Exception:
                    try:
                        graph.add_component(ref)
                        for key, value in payload.items():
                            set_field(_comp(graph, ref), key, value)
                    except Exception as exc:
                        self.log.warning("add_component(%s) impossible: %s", ref, exc)
                        continue
                added.append(ref)
                if selection:
                    matched += 1

        # 4) Nets d'alimentation + connexions basiques
        power_nets = self._ensure_power_nets(graph)
        power_links = self._connect_power(graph, power_nets)

        context["graph"] = graph
        stats = call_probe(graph, "stats") or {}
        output = {
            "built_with": built_with,
            "hints": hints,
            "added": added,
            "matched": matched,
            "total": total,
            "power_nets": power_nets,
            "power_links": power_links,
            "graph_stats": stats,
        }
        confidence = (matched / total) if total else (0.6 if self._components_of(graph) else 0.3)
        rev = self.commit(context, f"selection composants ({len(added or self._components_of(graph))} refs)")
        if rev is not None:
            output["revision"] = rev
        self.record_decision(
            context, "selection",
            f"{len(added or self._components_of(graph))} composants, nets: {power_nets}",
            confidence=confidence)
        self.emit("components.selected", {k: v for k, v in output.items() if k != "graph_stats"}, context)
        return self.succeeded(context, output, confidence=confidence,
                              rationale=f"{matched}/{total} hints matchés via {built_with}")

    # -------------------------------------------------------------- internals
    def _graph_kind(self, graph: Any) -> str:
        return "simple" if isinstance(graph, SimpleDesignGraph) else "design_core"

    def _components_of(self, graph: Any) -> dict[str, Any]:
        return get_field(graph, "components", default={}) or {}

    def _nets_of(self, graph: Any) -> dict[str, Any]:
        return get_field(graph, "nets", default={}) or {}

    def _new_graph(self, context: dict[str, Any]) -> Any:
        cls = try_import("services.design_core", ["DesignGraph"]).get("DesignGraph")
        if cls is not None:
            try:
                return cls()
            except TypeError:
                try:
                    return cls(project_id=str(context.get("project_id") or "new"))
                except Exception:
                    pass
        return SimpleDesignGraph(project_id=str(context.get("project_id") or "new"))

    def _graph_from_skidl(self, message: str) -> Any | None:
        mods = try_import("services.parser", ["NLToSkidl"])
        cls = mods.get("NLToSkidl")
        if cls is None:
            return None
        try:
            tool = cls()
            script = tool.translate(message)
            graph = tool.build_graph(script)
            if graph is not None and self._components_of(graph):
                return graph
        except Exception as exc:
            self.log.debug("NLToSkidl.build_graph indisponible: %s", exc)
        return None

    def _hints(self, context: dict[str, Any]) -> list[str]:
        hints: list[str] = []
        parse_meta = context.get("intent_parse") or {}
        raw = parse_meta.get("component_hints") or []
        intents = context.get("intents")
        if intents is not None:
            raw = raw or get_field(intents, "component_hints", "components", default=[]) or []
        params = context.get("params") or {}
        raw = raw or params.get("component_hints") or []
        for hint in raw:
            text = hint if isinstance(hint, str) else str(
                get_field(hint, "description", "value", "mpn", "type", default=json.dumps(hint, default=str)))
            text = text.strip()
            if text and text not in hints:
                hints.append(text)
        return hints[:20]

    def _matcher(self) -> Any:
        cls = try_import("services.parser", ["ComponentLibMatcher"]).get("ComponentLibMatcher")
        if cls is None:
            return None
        try:
            return cls()
        except TypeError:
            return cls(self.orchestrator)

    def _match(self, matcher: Any, hint: str) -> dict[str, Any]:
        if matcher is None:
            return {}
        raw = (call_probe(matcher, "match", (hint,))
               or call_probe(matcher, "search", (hint,))
               or call_probe(matcher, "find", (hint,))
               or call_probe(matcher, "best_match", (hint,)))
        if raw is None:
            return {}
        if isinstance(raw, list):
            raw = raw[0] if raw else {}
        if isinstance(raw, dict):
            return raw
        mpn = get_field(raw, "mpn", default=None)
        if mpn:
            return {"mpn": str(mpn),
                    "footprint": str(get_field(raw, "footprint", default="")),
                    "description": str(get_field(raw, "description", "value", default=""))}
        return {"description": str(raw)}

    def _next_ref(self, selection: dict[str, Any], hint: str) -> str:
        prefix = "U"
        text = f"{hint} {selection.get('mpn', '')} {selection.get('description', '')}".lower()
        if re.search(r"résistance|resistor|\br[0-9]", text):
            prefix = "R"
        elif re.search(r"condensateur|capacitor|\bc[0-9]", text):
            prefix = "C"
        elif re.search(r"inductance|inductor|self\b|ferrite", text):
            prefix = "L"
        elif re.search(r"connecteur|connector|header|jst|usb", text):
            prefix = "J"
        elif re.search(r"led|diode", text):
            prefix = "D"
        self._ref_counters[prefix] = self._ref_counters.get(prefix, 0) + 1
        return f"{prefix}{self._ref_counters[prefix]}"

    def _payload_from(self, selection: dict[str, Any], hint: str) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "value": str(selection.get("value") or hint)[:60],
            "mpn": str(selection.get("mpn") or ""),
            "footprint": str(selection.get("footprint") or selection.get("package") or ""),
            "description": str(selection.get("description") or "")[:200],
            "price_usd": float(selection.get("price_usd") or selection.get("price") or 0.0),
        }
        pads = selection.get("pads") or []
        if isinstance(pads, list) and pads:
            payload["pads"] = [str(p.get("name") if isinstance(p, dict) else p) for p in pads][:48]
        return payload

    def _ensure_power_nets(self, graph: Any) -> list[str]:
        created: list[str] = []
        nets = self._nets_of(graph)
        for net_id, class_name in (("GND", "power"), ("VCC", "power")):
            if net_id not in nets:
                try:
                    flex_call(graph.add_net, net_id, {"name": net_id, "class_name": class_name})
                    created.append(net_id)
                except Exception:
                    try:
                        graph.add_net(net_id)
                        created.append(net_id)
                    except Exception:
                        pass
        return created

    def _connect_power(self, graph: Any, power_nets: list[str]) -> int:
        """Connecte les pads nommés gnd/vcc/vdd/... aux nets d'alimentation."""
        if not power_nets:
            return 0
        links = 0
        for ref, comp in self._components_of(graph).items():
            for pad in pad_names(comp):
                alias = _POWER_ALIASES.get(pad.lower().strip())
                if alias and alias in power_nets:
                    try:
                        graph.connect(ref, pad, alias)
                        links += 1
                    except Exception:
                        continue
        return links


def _comp(graph: Any, ref: str) -> Any:
    return (get_field(graph, "components", default={}) or {}).get(ref)
