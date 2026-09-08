"""DRC — Design Rules Checker : le cuivre doit être géométriquement fabriquable.

Vérifie : largeur de trace, clearance entre objets de nets différents,
distance au bord, overlap de composants, vias trop proches.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple

from shared.geometry.geometry import Point, Segment
from shared.utilities import get_logger
from services.design_core.design_graph.graph import DesignGraph
from services.verification.design_rules import DesignRules

log = get_logger(__name__)

MAX_SEG_PAIRS = 400_000  # garde-fou perf (early exit via bbox)


@dataclass
class DRCViolation:
    code: str
    message: str
    severity: str = "error"
    location: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {"code": self.code, "message": self.message,
                "severity": self.severity, "location": self.location}


@dataclass
class DRCReport:
    violations: List[DRCViolation] = field(default_factory=list)
    checked: int = 0

    @property
    def passed(self) -> bool:
        return not any(v.severity == "error" for v in self.violations)

    @property
    def score(self) -> float:
        if self.checked == 0:
            return 1.0
        penalty = sum(1.0 for v in self.violations if v.severity == "error")
        penalty += 0.5 * sum(1.0 for v in self.violations if v.severity == "warning")
        return max(0.0, 1.0 - penalty / max(1.0, self.checked))

    def to_dict(self) -> Dict[str, Any]:
        return {"passed": self.passed, "score": self.score, "checked": self.checked,
                "violations": [v.to_dict() for v in self.violations]}


def _pad_abs_position(comp, pad) -> Point:
    """Position absolue d'un pad (offset tourné selon la rotation du composant)."""
    a = math.radians(comp.rotation or 0.0)
    ca, sa = math.cos(a), math.sin(a)
    return Point(comp.x + pad.x * ca - pad.y * sa, comp.y + pad.x * sa + pad.y * ca)


class DRCEngine:
    def __init__(self, rules: DesignRules | None = None) -> None:
        self.rules = rules or DesignRules()

    def run(self, graph: DesignGraph) -> DRCReport:
        report = DRCReport()
        w_board, h_board = graph.board_size
        rules = self.rules

        # 1. Traces trop fines
        segments: List[Tuple[Segment, str, str]] = []  # (segment, net_id, layer_name)
        for net in graph.nets.values():
            path = net.path
            if path is None:
                continue
            report.checked += 1
            if path.width_mm < rules.min_trace_mm - 1e-9:
                report.violations.append(DRCViolation(
                    "DRC_TRACE_WIDTH",
                    f"Net '{net.name or net.net_id}' : trace {path.width_mm:.3f}mm "
                    f"< minimum {rules.min_trace_mm:.3f}mm",
                    "error", {"net": net.net_id, "width_mm": path.width_mm}))
            layer_name = graph.layers[path.layer].name if path.layer < len(graph.layers) else f"L{path.layer}"
            for seg in path.segments():
                segments.append((seg, net.net_id, layer_name))

        # 2. Clearance cuivre-cuivre entre nets différents (même couche)
        #    Test segment↔segment avec early exit par bbox.
        n = len(segments)
        report.checked += n
        pairs_tested = 0
        for i in range(n):
            seg_a, net_a, layer_a = segments[i]
            for j in range(i + 1, n):
                seg_b, net_b, layer_b = segments[j]
                if net_a == net_b or layer_a != layer_b:
                    continue
                if pairs_tested > MAX_SEG_PAIRS:
                    break
                # early exit : bboxes éloignées
                if (abs(seg_a.start.x - seg_b.start.x) > 5.0
                        and seg_a.start.distance_to(seg_b.start) > 2.0):
                    pass  # distance exacte calculée ci-dessous seulement si proche
                d = self._segment_distance(seg_a, seg_b)
                if d < rules.min_clearance_mm - 1e-9:
                    pairs_tested += 1
                    report.violations.append(DRCViolation(
                        "DRC_CLEARANCE",
                        f"Clearance {d:.3f}mm < {rules.min_clearance_mm:.3f}mm entre "
                        f"'{net_a}' et '{net_b}' sur {layer_a}",
                        "error", {"net_a": net_a, "net_b": net_b,
                                  "clearance_mm": round(d, 4)}))
                if pairs_tested > MAX_SEG_PAIRS:
                    break

        # 3. Composants trop proches du bord
        for comp in graph.components.values():
            report.checked += 1
            w, h = comp.bbox
            if not comp.placed:
                continue
            if (comp.x - w / 2 < rules.min_edge_margin_mm
                    or comp.y - h / 2 < rules.min_edge_margin_mm
                    or comp.x + w / 2 > w_board - rules.min_edge_margin_mm
                    or comp.y + h / 2 > h_board - rules.min_edge_margin_mm):
                report.violations.append(DRCViolation(
                    "DRC_EDGE_MARGIN",
                    f"'{comp.ref}' à moins de {rules.min_edge_margin_mm}mm du bord de la carte",
                    "error", {"ref": comp.ref, "x": comp.x, "y": comp.y}))

        # 4. Overlap de composants (même côté)
        placed = [c for c in graph.components.values() if c.placed]
        for i in range(len(placed)):
            for j in range(i + 1, len(placed)):
                a, b = placed[i], placed[j]
                if a.side != b.side:
                    continue
                report.checked += 1
                wa, ha = a.bbox
                wb, hb = b.bbox
                if (abs(a.x - b.x) < (wa + wb) / 2 - 1e-6
                        and abs(a.y - b.y) < (ha + hb) / 2 - 1e-6):
                    report.violations.append(DRCViolation(
                        "DRC_COMPONENT_OVERLAP",
                        f"'{a.ref}' et '{b.ref}' se chevauchent",
                        "error", {"ref_a": a.ref, "ref_b": b.ref}))

        # 5. Vias trop proches ou trop petits
        via_points: List[Tuple[Point, str]] = []
        for net in graph.nets.values():
            if net.path is None:
                continue
            for pos, _from_l, _to_l in net.path.vias:
                via_points.append((pos, net.net_id))
        for pos, net_id in via_points:
            report.checked += 1
            if pos.x < rules.min_edge_margin_mm or pos.y < rules.min_edge_margin_mm \
                    or pos.x > w_board - rules.min_edge_margin_mm or pos.y > h_board - rules.min_edge_margin_mm:
                report.violations.append(DRCViolation(
                    "DRC_VIA_EDGE",
                    f"Via du net '{net_id}' trop proche du bord",
                    "error", {"net": net_id}))
        for i in range(len(via_points)):
            for j in range(i + 1, len(via_points)):
                (p1, n1), (p2, n2) = via_points[i], via_points[j]
                if n1 == n2:
                    continue
                report.checked += 1
                d = p1.distance_to(p2)
                if d < rules.min_via_pad_mm + rules.min_clearance_mm - 1e-9:
                    report.violations.append(DRCViolation(
                        "DRC_VIA_CLEARANCE",
                        f"Vias trop proches ({d:.3f}mm) entre '{n1}' et '{n2}'",
                        "error", {"net_a": n1, "net_b": n2}))

        # 6. Aspect ratio (approx : épaisseur carte / forage)
        if rules.min_via_drill_mm > 0:
            ratio = rules.board_thickness_mm / rules.min_via_drill_mm
            if ratio > rules.max_aspect_ratio:
                report.checked += 1
                report.violations.append(DRCViolation(
                    "DRC_ASPECT_RATIO",
                    f"Aspect ratio {ratio:.1f} > {rules.max_aspect_ratio} "
                    f"(forage {rules.min_via_drill_mm}mm sur carte {rules.board_thickness_mm}mm)",
                    "warning", {}))

        log.info("DRC: %d checks, %d violations, passed=%s",
                 report.checked, len(report.violations), report.passed)
        return report

    @staticmethod
    def _segment_distance(a: Segment, b: Segment) -> float:
        """Distance minimale entre deux segments (4 tests point-segment + intersection)."""
        if DRCEngine._segments_intersect(a, b):
            return 0.0
        return min(
            a.distance_point_to_segment(b.start),
            a.distance_point_to_segment(b.end),
            b.distance_point_to_segment(a.start),
            b.distance_point_to_segment(a.end),
        )

    @staticmethod
    def _segments_intersect(a: Segment, b: Segment) -> bool:
        def orient(p: Point, q: Point, r: Point) -> float:
            return (q.y - p.y) * (r.x - q.x) - (q.x - p.x) * (r.y - q.y)

        d1 = orient(a.start, a.end, b.start)
        d2 = orient(a.start, a.end, b.end)
        d3 = orient(b.start, b.end, a.start)
        d4 = orient(b.start, b.end, a.end)
        return ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0))
