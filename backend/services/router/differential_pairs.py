"""Paires différentielles V3-enrichies — routage couplé, skew, rapport qualité.

Pipeline par paire (P, N) :
  1. Membre P routé par A* (MazeRouter) segment par segment (MST topologique).
  2. Membre N : chemin décalé d'un gap constant (bord-à-bord), puis VALIDATION
     géométrique (clearance vs cuivre ennemi + corps de composants + keepouts).
     Si invalide → repli : A* indépendant sur la topologie de N.
  3. Appariement de longueur intra-paire (serpentin accordéon) pour ramener le
     skew sous la tolérance (0.15 mm par défaut — USB2/HDMI class).
  4. PairQualityReport : longueurs, skew, gap min/moyen, longueur couplée,
     ratio de couplage, stratégie effective.

Best-effort industriel : le rapport permet au corrector agent et au validator
de détecter les paires mal couplées sans bloquer le flux.
"""
from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field

from shared.geometry import Point, RoutePath, Segment
from shared.utilities import get_logger

from services.design_core import DesignGraph, Net
from services.router.geometrical import (
    MazeRouter,
    offset_polyline,
    segment_segment_distance,
)
from services.router.high_speed import add_serpentine, polyline_length
from services.router.topological import (
    build_net_topology,
    is_differential_net,
    net_pad_positions,
)

log = get_logger("router.differential")

_PAIR_SUFFIXES = ("_P", "_N", "_DP", "_DM", "_+", "_-", "+", "-")

# tolérance de skew par défaut (mm) — classe "high-speed serial"
DEFAULT_SKEW_TOL_MM = 0.15
# longueur de fanout avec neck-down près des pads de pas fin (mm)
NECK_LENGTH_MM = 1.2


@dataclass
class PairQualityReport:
    """Qualité de couplage d'une paire différentielle routée."""

    name: str
    net_p: str
    net_n: str
    length_p_mm: float = 0.0
    length_n_mm: float = 0.0
    skew_mm: float = 0.0
    min_gap_mm: float = float("inf")
    mean_gap_mm: float = 0.0
    coupled_mm: float = 0.0
    coupling_ratio: float = 0.0
    skew_matched: bool = False
    strategy: str = "offset"           # offset | astar_fallback
    notes: list[str] = field(default_factory=list)

    @property
    def well_coupled(self) -> bool:
        """Couplage industriel acceptable : ratio ≥ 0.5 et gap maîtrisé."""
        return self.coupling_ratio >= 0.5 and math.isfinite(self.min_gap_mm)

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "net_p": self.net_p,
            "net_n": self.net_n,
            "length_p_mm": round(self.length_p_mm, 2),
            "length_n_mm": round(self.length_n_mm, 2),
            "skew_mm": round(self.skew_mm, 3),
            "min_gap_mm": (round(self.min_gap_mm, 3)
                           if math.isfinite(self.min_gap_mm) else None),
            "mean_gap_mm": round(self.mean_gap_mm, 3),
            "coupled_mm": round(self.coupled_mm, 2),
            "coupling_ratio": round(self.coupling_ratio, 3),
            "skew_matched": self.skew_matched,
            "well_coupled": self.well_coupled,
            "strategy": self.strategy,
            "notes": list(self.notes),
        }


def _pair_base(name: str) -> tuple[str, str] | None:
    """(base, polarity) si le nom se termine par un suffixe de paire, None sinon."""
    n = (name or "").strip()
    upper = n.upper()
    for suf in ("_P", "_DP"):
        if upper.endswith(suf):
            return upper[: -len(suf)], "P"
    for suf in ("_N", "_DM"):
        if upper.endswith(suf):
            return upper[: -len(suf)], "N"
    if upper.endswith("_+"):
        return upper[:-2], "P"
    if upper.endswith("_-"):
        return upper[:-2], "N"
    return None


def find_differential_pairs(graph: DesignGraph) -> list[tuple[Net, Net]]:
    """Détecte les paires (P, N) : classe differential groupée par matched_group,
    sinon appariement par suffixe _P/_N (ou _DP/_DM) des noms de nets.

    La détection par suffixe s'applique aussi aux nets SANS classe déclarée
    (convention USB_DP/USB_DM, CAN_P/CAN_N…) — une paire n'est formée que si
    les deux membres existent, ce qui rend les faux positifs quasi impossibles.
    """
    pairs: list[tuple[Net, Net]] = []
    used: set[str] = set()

    diff_nets = [n for n in graph.nets.values()
                 if is_differential_net(n) or _pair_base(n.name) is not None]

    # 1) par matched_group : 2 nets (ou plus) → on apparie P puis N
    by_group: dict[str, list[Net]] = {}
    for net in diff_nets:
        if net.matched_group:
            by_group.setdefault(net.matched_group, []).append(net)
    for group, nets in sorted(by_group.items()):
        p = next((n for n in nets if _pair_base(n.name) and _pair_base(n.name)[1] == "P"), None)
        n_net = next((n for n in nets if n is not p and
                      (_pair_base(n.name) is None or _pair_base(n.name)[1] == "N")), None)
        if p is not None and n_net is not None:
            pairs.append((p, n_net))
            used.update((p.net_id, n_net.net_id))
        else:
            log.warning("groupe différentiel '%s' non appariable (%d nets)", group, len(nets))

    # 2) par suffixe de nom sur les nets différentiels restants
    remaining = [n for n in diff_nets if n.net_id not in used]
    by_base: dict[str, dict[str, Net]] = {}
    for net in remaining:
        base = _pair_base(net.name)
        if base is None:
            continue
        by_base.setdefault(base[0], {})[base[1]] = net
    for _base, pol in sorted(by_base.items()):
        if "P" in pol and "N" in pol:
            pairs.append((pol["P"], pol["N"]))
    return pairs


# --------------------------------------------------------------------- géométrie
def _segments_of(points: Sequence[Point]) -> list[Segment]:
    return [Segment(points[i], points[i + 1]) for i in range(len(points) - 1)]


def _parallel_overlap(a: Segment, b: Segment) -> tuple[float, float]:
    """(recouvrement le long de l'axe commun, distance perpendiculaire) si les
    deux segments sont parallèles (orthogonaux), sinon (0, inf)."""
    dax, day = a.end.x - a.start.x, a.end.y - a.start.y
    dbx, dby = b.end.x - b.start.x, b.end.y - b.start.y
    cross = dax * dby - day * dbx
    len_a = math.hypot(dax, day)
    len_b = math.hypot(dbx, dby)
    if len_a < 1e-9 or len_b < 1e-9 or abs(cross) > 1e-6 * len_a * len_b:
        return 0.0, float("inf")
    # perpendiculaire = distance d'une extrémité de b à la ligne a
    perp = abs((b.start.x - a.start.x) * day - (b.start.y - a.start.y) * dax) / len_a
    # axe commun (unitaire) de a
    ux, uy = dax / len_a, day / len_a
    pa0, pa1 = 0.0, len_a
    pb0 = (b.start.x - a.start.x) * ux + (b.start.y - a.start.y) * uy
    pb1 = pb0 + (len_b if (dbx * ux + dby * uy) >= 0 else -len_b)
    lo, hi = sorted((pb0, pb1))
    overlap = max(0.0, min(pa1, hi) - max(pa0, lo))
    return overlap, perp


def _path_gap_stats(points_p: Sequence[Point], points_n: Sequence[Point],
                    max_gap_mm: float = 3.0) -> tuple[float, float, float]:
    """(gap min, gap moyen, longueur couplée) entre deux polylignes proches.

    Un segment compte comme couplé si un segment parallèle du membre opposé
    est à ≤ max_gap_mm ; la longueur couplée est le recouvrement le long de
    l'axe commun (approximation de couplage par proximité latérale).
    """
    segs_p = _segments_of(points_p)
    segs_n = _segments_of(points_n)
    if not segs_p or not segs_n:
        return float("inf"), 0.0, 0.0
    gaps: list[float] = []
    coupled = 0.0
    for sa in segs_p:
        best = float("inf")
        for sb in segs_n:
            d = segment_segment_distance(sa, sb)
            if d < best:
                best = d
            if d <= max_gap_mm:
                overlap, _perp = _parallel_overlap(sa, sb)
                if overlap > 0.0:
                    coupled += overlap
        if math.isfinite(best):
            gaps.append(best)
    if not gaps:
        return float("inf"), 0.0, coupled
    return min(gaps), sum(gaps) / len(gaps), coupled


def _path_is_clear(graph: DesignGraph, points: Sequence[Point], width_mm: float,
                   own_net_ids: set[str], min_gap: float) -> bool:
    """True si la polyligne respecte la clearance vis-à-vis du cuivre ennemi
    (traces routées d'autres nets) et des corps de composants."""
    half = width_mm / 2.0
    need = min_gap + half
    segs = _segments_of(points)
    if not segs:
        return True
    for net in graph.nets.values():
        if net.net_id in own_net_ids or net.path is None:
            continue
        for seg in _segments_of(net.path.points):
            for s in segs:
                if segment_segment_distance(s, seg) < need + net.path.width_mm / 2.0:
                    return False
    for comp in graph.components.values():
        w, h = comp.bbox
        for s in segs:
            # distance segment → rectangle (clamp du point le plus proche)
            cx = min(max(s.start.x, comp.x - w / 2), comp.x + w / 2)
            cy = min(max(s.start.y, comp.y - h / 2), comp.y + h / 2)
            if s.distance_point_to_segment(Point(cx, cy)) < need:
                return False
    return True


class DifferentialPairRouter:
    """Route les deux membres d'une paire en parallèle, égalise le skew
    et produit un rapport de qualité industriel."""

    def __init__(self, maze: MazeRouter | None = None, gap_mm: float = 0.45,
                 skew_tol_mm: float = DEFAULT_SKEW_TOL_MM) -> None:
        self.maze = maze
        self.gap_mm = float(gap_mm)
        self.skew_tol_mm = float(skew_tol_mm)
        self.reports: list[PairQualityReport] = []

    # ------------------------------------------------------------------ public
    def route_pair(self, graph: DesignGraph, net_p: Net, net_n: Net,
                   width_mm: float = 0.2,
                   layers: Sequence[int] | None = None) -> PairQualityReport | None:
        """Route la paire complète. Retourne un PairQualityReport, ou None si
        le membre P n'a pas pu être routé.

        `layers` : couches de signal à essayer en ordre (défaut : couches
        signal/mixed du stackup). La paire reste couplée sur la couche de
        tête ; les couches de repli sont utilisées segment par segment.
        """
        maze = self.maze or MazeRouter(board_size=graph.board_size)
        if layers is None:
            layers = tuple(ly.index for ly in graph.layers
                           if ly.ltype in ("signal", "mixed")) or (0, 1)
        segments = build_net_topology(graph, net_p)
        if not segments:
            return None
        points: list[Point] = []
        for a, b in segments:
            path: list[Point] | None = None
            for lyr in layers:
                path = maze.route_pair(graph, net_p, a, b, lyr, width_mm)
                if path is not None:
                    break
            if path is None:
                return None
            for p in path:
                if not points or points[-1].distance_to(p) > 1e-9:
                    points.append(p)

        report = PairQualityReport(
            name=f"{net_p.name}/{net_n.name}",
            net_p=net_p.net_id, net_n=net_n.net_id,
        )

        # ---- membre N : offset puis validation, repli A* indépendant
        n_pads = [pos for _, pos in net_pad_positions(graph, net_n)]
        n_points = offset_polyline(points, width_mm + self.gap_mm)
        if n_pads:
            n_start = _nearest(n_pads, n_points[0])
            n_end = _nearest(list(reversed(n_pads)), n_points[-1])
            n_points = [n_start] + n_points[1:-1] + [n_end]
        own = {net_p.net_id, net_n.net_id}
        strategy = "offset"
        if not _path_is_clear(graph, n_points, width_mm, own,
                              min_gap=self.gap_mm * 0.6):
            fb = self._route_independent(graph, net_n, maze, width_mm,
                                         layers=layers)
            if fb is None:
                log.warning("paire %s : offset N invalide et A* N en échec",
                            report.name)
                report.notes.append("fallback_astar_failed")
                return None
            n_points = fb
            strategy = "astar_fallback"
            report.notes.append("offset_invalide→A*_indépendant")
        report.strategy = strategy

        # ---- appariement de skew intra-paire (serpentins itératifs)
        len_p = polyline_length(points)
        len_n = polyline_length(n_points)
        extra = abs(len_p - len_n)
        if extra > self.skew_tol_mm:
            short_is_p = len_n > len_p
            base_pts = points if short_is_p else n_points
            other_len = len_n if short_is_p else len_p
            remaining = extra
            for _attempt in range(4):       # distribue sur plusieurs segments
                if remaining <= self.skew_tol_mm:
                    break
                zig = add_serpentine(list(base_pts), remaining)
                if zig is None:
                    break
                base_pts = zig
                remaining = abs(other_len - polyline_length(base_pts))
            if short_is_p:
                points = base_pts
            else:
                n_points = base_pts
            if remaining <= self.skew_tol_mm:
                report.skew_matched = True
                report.notes.append(f"serpentins +{extra - remaining:.2f} mm")
            else:
                report.notes.append(
                    f"skew résiduel {remaining:.2f} mm "
                    f"(serpentins +{extra - remaining:.2f} mm)")

        net_p.path = RoutePath(net_id=net_p.net_id, points=points, layer=0,
                               width_mm=width_mm, vias=[])
        net_n.path = RoutePath(net_id=net_n.net_id, points=n_points, layer=0,
                               width_mm=width_mm, vias=[])
        net_p.routed = True
        net_n.routed = True
        maze.observe_path(net_p.path)
        maze.observe_path(net_n.path)

        # ---- rapport qualité
        report.length_p_mm = net_p.path.length()
        report.length_n_mm = net_n.path.length()
        report.skew_mm = abs(report.length_p_mm - report.length_n_mm)
        min_gap, mean_gap, coupled = _path_gap_stats(points, n_points)
        report.min_gap_mm = min_gap
        report.mean_gap_mm = mean_gap
        report.coupled_mm = coupled
        base_len = max(report.length_p_mm, 1e-9)
        report.coupling_ratio = min(1.0, coupled / base_len)
        self.reports.append(report)
        log.info("paire %s routée (%s, gap %.2f, skew %.2f mm, couplage %.0f%%)",
                 report.name, strategy, report.min_gap_mm, report.skew_mm,
                 report.coupling_ratio * 100.0)
        return report

    def route_all_pairs(self, graph: DesignGraph,
                        widths: dict[str, float] | None = None
                        ) -> list[PairQualityReport]:
        """Route toutes les paires détectées. Rapports cumulés dans self.reports."""
        widths = widths or {}
        reports: list[PairQualityReport] = []
        for p, n in find_differential_pairs(graph):
            if p.routed or n.routed:
                continue
            w = widths.get(p.net_id, widths.get(n.net_id, 0.2))
            rep = self.route_pair(graph, p, n, w)
            if rep is not None:
                reports.append(rep)
        return reports

    # ----------------------------------------------------------------- privé
    def _route_independent(self, graph: DesignGraph, net: Net,
                           maze: MazeRouter, width_mm: float,
                           layers: Sequence[int] = (0, 1)) -> list[Point] | None:
        """Repli : routage A* indépendant du membre N sur sa propre topologie."""
        segments = build_net_topology(graph, net)
        if not segments:
            return None
        pts: list[Point] = []
        for a, b in segments:
            path: list[Point] | None = None
            for lyr in layers:
                path = maze.route_pair(graph, net, a, b, lyr, width_mm)
                if path is not None:
                    break
            if path is None:
                return None
            for p in path:
                if not pts or pts[-1].distance_to(p) > 1e-9:
                    pts.append(p)
        return pts


def _nearest(candidates: list[Point], target: Point) -> Point:
    return min(candidates, key=lambda p: p.distance_to(target))
