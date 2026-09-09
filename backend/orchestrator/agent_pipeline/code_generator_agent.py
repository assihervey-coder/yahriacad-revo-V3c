"""CodeGeneratorAgent — génération du script SKIDL du design."""
from __future__ import annotations

from typing import Any

from shared.contracts import AgentRole
from shared.schemas import AgentResultSchema

from orchestrator.agent_pipeline.base import BaseAgent
from orchestrator.common import get_field, try_import


class CodeGeneratorAgent(BaseAgent):
    """Étape `code` : message utilisateur → SKIDL, ou graphe courant → SKIDL."""

    role = AgentRole.CODE_GENERATOR
    description = "Génère le script SKIDL (netlist programmatique) du design."

    def __init__(self, orchestrator: Any = None) -> None:
        super().__init__(AgentRole.CODE_GENERATOR, "code_generator", orchestrator)

    def supports(self, action: str) -> bool:
        return action in ("generate_skidl", "generate_code", "code", "skidl", "")

    def execute(self, context: dict[str, Any]) -> AgentResultSchema:
        message = str(context.get("message") or "")
        graph = context.get("graph")
        code = ""
        source = "template"

        # 1) Via NLToSkidl si un message est présent
        if message:
            mods = try_import("services.parser", ["NLToSkidl"])
            cls = mods.get("NLToSkidl")
            if cls is not None:
                try:
                    tool = cls()
                    script = tool.translate(message)
                    code = str(get_field(script, "code", "script", default="") or str(script))
                    source = "nl_to_skidl"
                except Exception as exc:
                    self.log.debug("NLToSkidl.translate indisponible: %s", exc)

        # 2) Repli : génération depuis le graphe courant
        if not code and graph is not None:
            code = self._code_from_graph(graph)
            source = "graph_template"

        # 3) Dernier repli : canevas minimal
        if not code:
            code = (
                "from skidl import *\n\n"
                "# Canevas SKIDL généré par PCB_AI_DESIGNER_V3\n"
                "mcu = Part('MCU', 'ESP32-WROOM-32E', footprint='ESP32-WROOM-32E')\n"
                "vcc = Net('VCC')\n"
                "gnd = Net('GND')\n"
                "mcu['VDD'] += vcc\n"
                "mcu['GND'] += gnd\n"
            )
            source = "fallback"

        lines = code.count("\n") + 1
        output = {"skidl": code, "lines": lines, "source": source}
        context["skidl"] = code
        self.record_decision(context, "skidl", f"script généré ({lines} lignes, {source})",
                             confidence=0.7)
        self.emit("skidl.generated", {"lines": lines, "source": source}, context)
        return self.succeeded(context, output, confidence=0.7,
                              rationale=f"SKIDL via {source} ({lines} lignes)")

    def _code_from_graph(self, graph: Any) -> str:
        comps = get_field(graph, "components", default={}) or {}
        nets = get_field(graph, "nets", default={}) or {}
        lines: list[str] = [
            "from skidl import *",
            "",
            f"# Design PCB_AI_DESIGNER_V3 — {len(comps)} composants, {len(nets)} nets",
            "",
        ]
        comp_vars: dict[str, str] = {}
        for ref, comp in comps.items():
            var = ref.lower().replace("-", "_")
            comp_vars[ref] = var
            mpn = str(get_field(comp, "mpn", default=ref) or ref)
            footprint = str(get_field(comp, "footprint", default="") or "")
            lines.append(f"{var} = Part('{mpn or 'Device'}', '{ref}', "
                         f"footprint='{footprint}', value='{get_field(comp, 'value', default=ref)}')")
        lines.append("")
        net_vars: dict[str, str] = {}
        for net_id, net in nets.items():
            var = "net_" + str(net_id).lower().replace("-", "_").replace(" ", "_")
            net_vars[str(net_id)] = var
            class_name = str(get_field(net, "class_name", default="default") or "default")
            lines.append(f"{var} = Net('{net_id}')  # classe: {class_name}")
        lines.append("")
        for net_id, net in nets.items():
            var = net_vars.get(str(net_id))
            if not var:
                continue
            pins = get_field(net, "pins", default=[]) or []
            for pin in pins:
                try:
                    ref, pad = str(pin[0]), str(pin[1])
                except (TypeError, IndexError):
                    continue
                comp_var = comp_vars.get(ref)
                if comp_var:
                    lines.append(f"{var} += {comp_var}['{pad}']")
        return "\n".join(lines) + "\n"
