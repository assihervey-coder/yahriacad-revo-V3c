"""constraint_extractor — extrait des contraintes citées en langage naturel.

Ex. : "4 layers", "impedance 50 ohm", "min trace 0.2mm", "cost under 30",
"JLCPCB/PCBWay", "keep GND plane", "thermal". Retourne des instances
configurées du constraint_engine, ou des ParametricConstraint génériques.
"""
from __future__ import annotations

import re

from shared.utilities import get_logger

from services.design_core.constraint_engine.cost import MaxCostUSD
from services.design_core.constraint_engine.electrical import ImpedanceTarget, MinTraceWidth
from services.design_core.constraint_engine.engine import BaseConstraint, Violation
from services.design_core.constraint_engine.thermal import ThermalHotspot
from services.design_core.design_graph.graph import DesignGraph

log = get_logger("parser.constraint_extractor")


class ParametricConstraint(BaseConstraint):
    """Contrainte générique issue du NL — stocke la phrase source et vérifie sa spec."""

    def __init__(self, name: str, spec: dict, phrase: str = "", severity: str = "warning") -> None:
        super().__init__(
            constraint_id=f"param.{name}",
            category="intent",
            severity=severity,
            description=phrase or f"contrainte paramétrique '{name}'",
        )
        self.name = name
        self.spec = dict(spec)
        self.phrase = phrase

    def check(self, graph: DesignGraph) -> list[Violation]:
        violations: list[Violation] = []
        # nombre de couches demandé
        n_layers = self.spec.get("n_layers")
        if n_layers is not None and len(graph.layers) != int(n_layers):
            violations.append(self.violation(
                f"stackup {len(graph.layers)} couches ≠ {n_layers} demandées",
                location={"layers": len(graph.layers), "required": n_layers},
            ))
        # plan de masse exigé
        if self.spec.get("require_ground_plane") and not any(
            ly.ltype == "ground" for ly in graph.layers
        ):
            violations.append(self.violation(
                "aucune couche de plan de masse (ltype='ground') dans le stackup",
                location={"layers": [ly.name for ly in graph.layers]},
            ))
        return violations

    def __repr__(self) -> str:  # pragma: no cover
        return f"<ParametricConstraint {self.name} {self.spec}>"


_NUM = r"(\d+(?:[.,]\d+)?)"

_PATTERNS: list[tuple] = [
    # (regex, builder(phrase, match) -> contrainte | None)
    (re.compile(rf"(\d+)\s*couches|\b{_NUM}\s*layers?\b", re.I),
     lambda phrase, m: ParametricConstraint(
         "layer_count", {"n_layers": int(m.group(2) or m.group(1))}, phrase, severity="error")),
    (re.compile(rf"imp[ée]dance[^\d{{}}]{{0,25}}{_NUM}\s*(?:ohm|Ω)|{_NUM}\s*(?:ohm|Ω)\s*imp[ée]dance", re.I),
     lambda phrase, m: ImpedanceTarget(required_ohm=float((m.group(1) or m.group(2)).replace(",", ".")))),
    (re.compile(rf"(?:min(?:imum)?\s*)?(?:trace|piste)[^\d{{}}]{{0,20}}(?:width\s*)?{_NUM}\s*mm|"
                rf"(?:min(?:imum)?\s*)?trace\s*width[^\d{{}}]{{0,10}}{_NUM}", re.I),
     lambda phrase, m: _min_trace(m.group(1) or m.group(2), phrase)),
    (re.compile(rf"(?:cost|co[ûu]t|budget)[^\d{{}}]{{0,15}}(?:under|below|max|<|≤)?\s*\$?{_NUM}", re.I),
     lambda phrase, m: MaxCostUSD(max_usd=float(m.group(1).replace(",", ".")))),
    (re.compile(r"\b(jlcpcb|pcbway)\b", re.I),
     lambda phrase, m: _fabricator(m.group(1), phrase)),
    (re.compile(r"(?:keep|garder|conserver)[^\n.]{0,40}(?:gnd|ground|masse)|"
                r"(?:gnd|ground)[^\n.]{0,15}plane|plan\s+de\s+masse", re.I),
     lambda phrase, m: ParametricConstraint(
         "ground_plane", {"require_ground_plane": True}, phrase, severity="warning")),
    (re.compile(r"\bthermal\b|thermique?|chauffe|dissipation", re.I),
     lambda phrase, m: ThermalHotspot()),
]


def _min_trace(value: str | None, phrase: str) -> MinTraceWidth:
    c = MinTraceWidth(min_width_mm=float((value or "0.2").replace(",", ".")))
    c.description = f"largeur de piste minimale extraite de : {phrase!r}"
    return c


def _fabricator(name: str, phrase: str) -> MinTraceWidth:
    """Capabilités process standard du fabricant cité (trace/spacing 0.127 mm)."""
    c = MinTraceWidth(min_width_mm=0.127)
    c.constraint_id = f"mfg.{name.lower()}_capability"
    c.description = (f"capability {name} : largeur de piste min 0.127 mm "
                     f"(extrait de : {phrase!r})")
    return c


def extract(text: str) -> list[BaseConstraint]:
    """Détecte les contraintes citées dans `text` et retourne les instances configurées."""
    constraints: list[BaseConstraint] = []
    if not text or not text.strip():
        return constraints
    for pattern, builder in _PATTERNS:
        match = pattern.search(text)
        if match is None:
            continue
        try:
            constraint = builder(text.strip(), match)
        except Exception:  # jamais bloquant
            log.exception("extraction de contrainte échouée pour %r", match.group(0))
            continue
        if constraint is not None:
            constraints.append(constraint)
    log.info("contraintes extraites : %s", [c.constraint_id for c in constraints])
    return constraints
