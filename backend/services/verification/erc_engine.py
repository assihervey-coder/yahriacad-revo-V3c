"""ERC — Electrical Rules Checker : la connectivité doit avoir du sens."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from shared.utilities import get_logger

from services.design_core.design_graph.graph import DesignGraph

log = get_logger(__name__)

POWER_NET_HINTS = ("vcc", "vdd", "3v3", "5v", "12v", "pwr", "+")
GND_NET_HINTS = ("gnd", "vss", "agnd", "dgnd")


@dataclass
class ERCViolation:
    code: str
    message: str
    severity: str = "error"          # error | warning | info
    location: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message,
                "severity": self.severity, "location": self.location}


@dataclass
class ERCReport:
    violations: list[ERCViolation] = field(default_factory=list)
    checked: int = 0

    @property
    def passed(self) -> bool:
        return not any(v.severity == "error" for v in self.violations)

    @property
    def score(self) -> float:
        """0..1 — 1.0 si aucune violation."""
        if self.checked == 0:
            return 1.0
        penalty = sum(1.0 for v in self.violations if v.severity == "error")
        penalty += 0.5 * sum(1.0 for v in self.violations if v.severity == "warning")
        return max(0.0, 1.0 - penalty / max(1.0, self.checked))

    def to_dict(self) -> dict[str, Any]:
        return {"passed": self.passed, "score": self.score, "checked": self.checked,
                "violations": [v.to_dict() for v in self.violations]}


def _is_power(name: str) -> bool:
    n = name.lower()
    return any(h in n for h in POWER_NET_HINTS)


def _is_gnd(name: str) -> bool:
    n = name.lower()
    return any(h in n for h in GND_NET_HINTS)


class ERCEngine:
    """Vérifie la cohérence électrique du DesignGraph."""

    def __init__(self, max_single_pin_nets: int | None = None) -> None:
        self.max_single_pin_nets = max_single_pin_nets

    def run(self, graph: DesignGraph) -> ERCReport:
        report = ERCReport()
        comps = graph.components
        nets = graph.nets

        # 1. Pins référencés par un net mais inexistants
        for net in nets.values():
            for ref, pad in net.pins:
                report.checked += 1
                comp = comps.get(ref)
                if comp is None:
                    report.violations.append(ERCViolation(
                        "ERC_MISSING_COMPONENT",
                        f"Net '{net.name or net.net_id}' référence un composant absent '{ref}'",
                        "error", {"net": net.net_id, "ref": ref}))
                    continue
                pad_names = {p.name for p in comp.pads}
                if pad not in pad_names:
                    report.violations.append(ERCViolation(
                        "ERC_MISSING_PIN",
                        f"Net '{net.name or net.net_id}' référence le pad '{pad}' absent de '{ref}'",
                        "error", {"net": net.net_id, "ref": ref, "pad": pad}))

        # 2. Nets à un seul pin (fantômes) — warning sauf pour les flags
        single_pin = [n for n in nets.values() if len(n.pins) <= 1]
        report.checked += len(single_pin)
        for net in single_pin:
            sev = "info" if (net.name or "").lower().startswith(("flag", "test", "tp")) else "warning"
            report.violations.append(ERCViolation(
                "ERC_SINGLE_PIN",
                f"Net '{net.name or net.net_id}' n'a qu'un seul pin ({len(net.pins)})",
                sev, {"net": net.net_id}))

        # 3. Composants avec des pads flottants (pad sans net) sur les IC (U*)
        for comp in comps.values():
            if not comp.ref.upper().startswith("U"):
                continue
            for pad in comp.pads:
                report.checked += 1
                if pad.net_id is None and not pad.name.lower().startswith(("ep", "nc", "pad")):
                    report.violations.append(ERCViolation(
                        "ERC_FLOATING_PIN",
                        f"Pin '{comp.ref}.{pad.name}' n'est connecté à aucun net",
                        "warning", {"ref": comp.ref, "pad": pad.name}))

        # 4. Composant IC sans alimentation connectée
        for comp in comps.values():
            if not comp.ref.upper().startswith("U"):
                continue
            report.checked += 1
            has_power = False
            for pad in comp.pads:
                if pad.net_id and pad.net_id in nets:
                    name = (nets[pad.net_id].name or "").lower()
                    if _is_power(name) or _is_gnd(name):
                        has_power = True
                        break
            if comp.pads and not has_power:
                report.violations.append(ERCViolation(
                    "ERC_UNPOWERED_IC",
                    f"Le composant '{comp.ref}' n'a ni alimentation ni masse connectée",
                    "error", {"ref": comp.ref}))

        # 5. Un même pad ne peut pas appartenir à deux nets différents
        for comp in comps.values():
            seen: dict[str, str] = {}
            for pad in comp.pads:
                if pad.net_id is None:
                    continue
                report.checked += 1
                if pad.name in seen and seen[pad.name] != pad.net_id:
                    report.violations.append(ERCViolation(
                        "ERC_PAD_SHORT",
                        f"Pad '{comp.ref}.{pad.name}' court-circuité entre "
                        f"'{seen[pad.name]}' et '{pad.net_id}'",
                        "error", {"ref": comp.ref, "pad": pad.name}))
                seen[pad.name] = pad.net_id

        # 6. Nets power/GND confondus dans un même net
        for net in nets.values():
            name = (net.name or "").lower()
            if _is_power(name) and _is_gnd(name):
                report.checked += 1
                report.violations.append(ERCViolation(
                    "ERC_POWER_GND_MERGED",
                    f"Le net '{net.name}' mélange alimentation et masse",
                    "error", {"net": net.net_id}))

        log.info("ERC: %d checks, %d violations, passed=%s",
                 report.checked, len(report.violations), report.passed)
        return report
