"""Routeur géométrique — A* (Lee/maze) sur grille 0.25 mm, heapq complet.

Obstacles : corps de composants gonflés de la clearance, keepouts, segments
déjà routés (même couche). Coût = distance + pénalité densité (+ pénalité via
quand la couche demandée diffère de la couche de pads).
"""
from __future__ import annotations

import heapq
import itertools
import math
import time
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

from shared.geometry import Point, RoutePath, Segment
from shared.utilities import get_logger

from services.design_core import DesignGraph, Net

from services.router.topological import keepout_rects, net_pad_positions, pad_position

log = get_logger("router.geometrical")


def segment_segment_distance(a: Segment, b: Segment) -> float:
    """Distance exacte entre deux segments 2D (0.0 s'ils s'intersectent).

    Non-intersectants : le minimum est atteint à une extrémité → 4 tests
    point-segment via `Segment.distance_point_to_segment`.
    """
    if _segments_intersect(a, b):
        return 0.0
    return min(
        a.distance_point_to_segment(b.start),
        a.distance_point_to_segment(b.end),
        b.distance_point_to_segment(a.start),
        b.distance_point_to_segment(a.end),
    )


def _orient(p: Point, q: Point, r: Point) -> float:
    """Produit vectoriel (q-p)×(r-p) : signe de l'orientation."""
    return (q.x - p.x) * (r.y - p.y) - (q.y - p.y) * (r.x - p.x)


def _on_segment(p: Point, q: Point, r: Point) -> bool:
    """q colinéaire à p-r et dans sa boîte englobante."""
    return (min(p.x, r.x) <= q.x <= max(p.x, r.x)
            and min(p.y, r.y) <= q.y <= max(p.y, r.y))


def _segments_intersect(a: Segment, b: Segment) -> bool:
    """Test d'intersection par orientations (algorithme classique CLRS)."""
    o1 = _orient(a.start, a.end, b.start)
    o2 = _orient(a.start, a.end, b.end)
    o3 = _orient(b.start, b.end, a.start)
    o4 = _orient(b.start, b.end, a.end)
    if o1 * o2 < 0 and o3 * o4 < 0:
        return True
    if abs(o1) < 1e-12 and _on_segment(a.start, b.start, a.end):
        return True
    if abs(o2) < 1e-12 and _on_segment(a.start, b.end, a.end):
        return True
    if abs(o3) < 1e-12 and _on_segment(b.start, a.start, b.end):
        return True
    if abs(o4) < 1e-12 and _on_segment(b.start, a.end, b.end):
        return True
    return False


@dataclass
class _Grid:
    """Fenêtre d'analyse : grille régulière limitée au bbox des 2 points + marge."""

    x0: float
    y0: float
    step: float
    nx: int
    ny: int

    def index_of(self, p: Point) -> Tuple[int, int]:
        ix = int(round((p.x - self.x0) / self.step))
        iy = int(round((p.y - self.y0) / self.step))
        return max(0, min(self.nx - 1, ix)), max(0, min(self.ny - 1, iy))

    def point_at(self, ix: int, iy: int) -> Point:
        return Point(self.x0 + ix * self.step, self.y0 + iy * self.step)


class MazeRouter:
    """A* orthogonal sur grille fine pour relier deux pads d'un net.

    Parameters
    ----------
    grid_step   : pas de grille (mm), 0.25 par défaut.
    clearance   : garde électrique autour des obstacles (mm).
    margin      : marge d'analyse autour du bbox a-b (mm).
    via_penalty : coût équivalent (mm) d'une paire de vias (décision de couche).
    density_weight : poids de la pénalité de densité locale (µ-cells 2 mm).
    """

    def __init__(
        self,
        board_size: Tuple[float, float] = (100.0, 80.0),
        grid_step: float = 0.25,
        clearance: float = 0.2,
        margin: float = 5.0,
        via_penalty: float = 3.0,
        density_weight: float = 0.6,
        density_cell: float = 2.0,
        max_cells: int = 1_500_000,
    ) -> None:
        self.board_size = board_size
        self.grid_step = float(grid_step)
        self.clearance = float(clearance)
        self.margin = float(margin)
        self.via_penalty = float(via_penalty)
        self.density_weight = float(density_weight)
        self.density_cell = float(density_cell)
        self.max_cells = int(max_cells)
        # grille de densité grossière (nb de traces par cellule 2 mm)
        self._dens = np.zeros((
            max(1, int(math.ceil(board_size[0] / density_cell)) + 1),
            max(1, int(math.ceil(board_size[1] / density_cell)) + 1),
        ), dtype=np.float32)
        self._stats = {"calls": 0, "success": 0, "cells_explored": 0}

    # ------------------------------------------------------------------ densité
    def observe_path(self, path: RoutePath) -> None:
        """Incrémente la densité locale le long d'un chemin routé (pour coûts futurs)."""
        for seg in path.segments():
            self._raster_coarse(seg)

    def _raster_coarse(self, seg: Segment) -> None:
        d = self.density_cell
        i0 = max(0, int(min(seg.start.x, seg.end.x) / d))
        i1 = min(self._dens.shape[0] - 1, int(max(seg.start.x, seg.end.x) / d))
        j0 = max(0, int(min(seg.start.y, seg.end.y) / d))
        j1 = min(self._dens.shape[1] - 1, int(max(seg.start.y, seg.end.y) / d))
        if i1 >= i0 and j1 >= j0:
            self._dens[i0:i1 + 1, j0:j1 + 1] += 1.0

    def _density_cost(self, gx: float, gy: float) -> float:
        i = min(self._dens.shape[0] - 1, max(0, int(gx / self.density_cell)))
        j = min(self._dens.shape[1] - 1, max(0, int(gy / self.density_cell)))
        d = float(self._dens[i, j])
        return self.density_weight * min(d, 8.0) / 8.0

    # ----------------------------------------------------------------- obstacles
    def _build_blocked(self, graph: DesignGraph, net: Net, grid: _Grid,
                       layer: int, width_mm: float) -> Tuple[np.ndarray, np.ndarray]:
        """Retourne (blocked, hard) : blocked = tous obstacles ; hard = cuivre
        ennemi (traces) — inviolable même pour le force-unblock départ/arrivée."""
        nx, ny, step = grid.nx, grid.ny, grid.step
        blocked = np.zeros((nx, ny), dtype=bool)
        hard = np.zeros((nx, ny), dtype=bool)

        def mark_rect(minx: float, miny: float, maxx: float, maxy: float) -> None:
            i0 = max(0, int(math.floor((minx - grid.x0) / step)))
            i1 = min(nx - 1, int(math.ceil((maxx - grid.x0) / step)))
            j0 = max(0, int(math.floor((miny - grid.y0) / step)))
            j1 = min(ny - 1, int(math.ceil((maxy - grid.y0) / step)))
            if i1 >= i0 and j1 >= j0:
                blocked[i0:i1 + 1, j0:j1 + 1] = True

        def unmark_rect(minx: float, miny: float, maxx: float, maxy: float) -> None:
            i0 = max(0, int(math.floor((minx - grid.x0) / step)))
            i1 = min(nx - 1, int(math.ceil((maxx - grid.x0) / step)))
            j0 = max(0, int(math.floor((miny - grid.y0) / step)))
            j1 = min(ny - 1, int(math.ceil((maxy - grid.y0) / step)))
            if i1 >= i0 and j1 >= j0:
                blocked[i0:i1 + 1, j0:j1 + 1] = False

        def mark_segment(seg: Segment, radius: float, target: np.ndarray | None = None) -> None:
            tgt = blocked if target is None else target
            minx = min(seg.start.x, seg.end.x) - radius
            maxx = max(seg.start.x, seg.end.x) + radius
            miny = min(seg.start.y, seg.end.y) - radius
            maxy = max(seg.start.y, seg.end.y) + radius
            i0 = max(0, int(math.floor((minx - grid.x0) / step)))
            i1 = min(nx - 1, int(math.ceil((maxx - grid.x0) / step)))
            j0 = max(0, int(math.floor((miny - grid.y0) / step)))
            j1 = min(ny - 1, int(math.ceil((maxy - grid.y0) / step)))
            r2 = radius * radius
            ax, ay, bx, by = seg.start.x, seg.start.y, seg.end.x, seg.end.y
            dx, dy = bx - ax, by - ay
            len2 = dx * dx + dy * dy
            for ix in range(i0, i1 + 1):
                px = grid.x0 + ix * step
                for iy in range(j0, j1 + 1):
                    py = grid.y0 + iy * step
                    if len2 > 0.0:
                        t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / len2))
                        ddx, ddy = px - (ax + t * dx), py - (ay + t * dy)
                    else:
                        ddx, ddy = px - ax, py - ay
                    if ddx * ddx + ddy * ddy <= r2:
                        tgt[ix, iy] = True

        # 1) corps de composants (couches signal : on ne route pas sous un boîtier)
        #    Exception : les composants propriétaires des pads du net courant —
        #    leurs traces doivent pouvoir atteindre leurs propres pads à travers
        #    la bbox (sinon le couloir pad → extérieur est infranchissable).
        own_refs = {ref for (ref, _pad) in net.pins}
        for comp in graph.components.values():
            if not comp.placed or comp.ref in own_refs:
                continue
            w, h = comp.bbox
            c = self.clearance
            mark_rect(comp.x - w / 2 - c, comp.y - h / 2 - c,
                      comp.x + w / 2 + c, comp.y + h / 2 + c)

        # 2) keepouts (bbox conservatrice des polygones)
        for (kx0, ky0, kx1, ky1) in keepout_rects(graph):
            mark_rect(kx0 - self.clearance, ky0 - self.clearance,
                      kx1 + self.clearance, ky1 + self.clearance)

        # 3) libère les pads du net courant — AVANT le marquage du cuivre
        #    ennemi : la libération ne doit JAMAIS percer une trace/pad d'un
        #    autre net (sinon A* traverserait du cuivre ennemi de plein fouet).
        release = width_mm / 2.0 + 0.08
        for (ref, pad_name), pos in net_pad_positions(graph, net):
            comp = graph.get(ref)
            pad = next((p for p in comp.pads if p.name == pad_name), None)
            r = (max(pad.w, pad.h) / 2.0 if pad is not None else 0.3) + release
            unmark_rect(pos.x - r, pos.y - r, pos.x + r, pos.y + r)

        # 4) pads des AUTRES nets = cuivre ennemi (interdit de passer dessus).
        #    Marquage à la taille RÉELLE du pad + clearance (un 0.45 fixe
        #    bloquerait l'évasion des pas fins type USB-C 0.5 mm).
        for other in graph.nets.values():
            if other.net_id == net.net_id:
                continue
            for (ref, pad_name), pos in net_pad_positions(graph, other):
                comp = graph.get(ref)
                pad = next((p for p in comp.pads if p.name == pad_name), None)
                r = (max(pad.w, pad.h) / 2.0 if pad is not None else 0.3) \
                    + self.clearance
                mark_rect(pos.x - r, pos.y - r, pos.x + r, pos.y + r)

        # 5) canaux d'évasion verticaux depuis les pads du net courant
        #    (neck-down) : un pas fin (0.5 mm USB-C, BGA...) ne peut pas
        #    s'échapper latéralement ; les vrais routeurs étranglent la trace
        #    et sortent perpendiculairement. Le canal perce le marquage des
        #    PADS ennemis mais JAMAIS celui des TRACES ennemies (étape 6).
        channel_hw = min(width_mm / 2.0, 0.15)
        escape_len = 2.0
        for (_ref, _pad), pos in net_pad_positions(graph, net):
            unmark_rect(pos.x - channel_hw, pos.y - escape_len,
                        pos.x + channel_hw, pos.y + escape_len)

        # 6) traces déjà routées des AUTRES nets (même couche seulement) —
        #    marquées EN DERNIER : une trace ennemie gagne toujours sur un
        #    canal d'évasion (sinon chevauchement de cuivre).
        for other in graph.nets.values():
            if other.net_id == net.net_id or other.path is None:
                continue
            for seg in other.path.segments():
                if seg.layer != layer:
                    continue
                r = seg.width_mm / 2.0 + self.clearance + step * 0.71
                mark_segment(seg, r)
                mark_segment(seg, r, target=hard)
        return blocked, hard

    # -------------------------------------------------------------------- A*
    def route_pair(self, graph: DesignGraph, net: Net, a: Point, b: Point,
                   layer: int, width_mm: float = 0.2) -> Optional[List[Point]]:
        """Chemin A* orthogonal de `a` vers `b` sur `layer` (None si inaccessible).

        La grille est bornée au bbox des deux points + `margin` ; les cellules de
        départ/arrivée et les pads du net sont forcément libres.
        """
        self._stats["calls"] += 1
        t0_all = time.perf_counter()
        step = self.grid_step
        # adapte le pas si la fenêtre dépasse le budget mémoire
        span_x = abs(b.x - a.x) + 2 * self.margin
        span_y = abs(b.y - a.y) + 2 * self.margin
        while step < 2.0 and (span_x / step) * (span_y / step) > self.max_cells:
            step = min(2.0, step * 2.0)
        x0 = min(a.x, b.x) - self.margin
        y0 = min(a.y, b.y) - self.margin
        nx = int(math.ceil(span_x / step)) + 1
        ny = int(math.ceil(span_y / step)) + 1
        grid = _Grid(x0=x0, y0=y0, step=step, nx=nx, ny=ny)

        blocked, hard = self._build_blocked(graph, net, grid, layer, width_mm)
        t_build = time.perf_counter()
        (sx, sy), (gx, gy) = grid.index_of(a), grid.index_of(b)
        # force-unblock départ/arrivée + voisins — JAMAIS sur du cuivre ennemi
        for (ux, uy) in ((sx, sy), (gx, gy)):
            if not hard[ux, uy]:
                blocked[ux, uy] = False
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                vx, vy = ux + dx, uy + dy
                if 0 <= vx < nx and 0 <= vy < ny and not hard[vx, vy]:
                    blocked[vx, vy] = False
        if (sx, sy) == (gx, gy):
            self._stats["success"] += 1
            return [Point(a.x, a.y), Point(b.x, b.y)]

        # A* 4-connexe — g, parents, heap
        g_cost = np.full((nx, ny), np.inf, dtype=np.float64)
        parent = np.full((nx, ny), -1, dtype=np.int64)
        closed = np.zeros((nx, ny), dtype=bool)
        g_cost[sx, sy] = 0.0
        counter = itertools.count()
        h0 = (abs(gx - sx) + abs(gy - sy)) * step
        heap: list[tuple[float, int, int, int]] = [(h0, next(counter), sx, sy)]
        explored = 0
        found = False
        while heap:
            f, _, cx_, cy_ = heapq.heappop(heap)
            if (cx_, cy_) == (gx, gy):
                found = True
                break
            if closed[cx_, cy_]:
                continue                      # déjà optimal (A* cohérent)
            g_here = float(g_cost[cx_, cy_])
            # entrée périmée (déjà replanifiée moins chère)
            if f > g_here + (abs(gx - cx_) + abs(gy - cy_)) * step + 1e-6:
                continue
            closed[cx_, cy_] = True
            explored += 1
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                nx_, ny_ = cx_ + dx, cy_ + dy
                if not (0 <= nx_ < nx and 0 <= ny_ < ny) or blocked[nx_, ny_]:
                    continue
                if closed[nx_, ny_]:
                    continue
                wx = grid.x0 + nx_ * step
                wy = grid.y0 + ny_ * step
                ng = g_here + step * (1.0 + self._density_cost(wx, wy))
                if ng < float(g_cost[nx_, ny_]) - 1e-9:
                    g_cost[nx_, ny_] = ng
                    parent[nx_, ny_] = cx_ * ny + cy_
                    heapq.heappush(heap, (ng + (abs(gx - nx_) + abs(gy - ny_)) * step,
                                          next(counter), nx_, ny_))
        self._stats["cells_explored"] += explored
        _dur = time.perf_counter() - t0_all
        if _dur > 1.0:
            log.warning(
                "A* lent : %s (%.1f,%.1f)->(%.1f,%.1f) L%d — grille %dx%d, "
                "exploré %d, build %.2fs, total %.2fs",
                net.net_id, a.x, a.y, b.x, b.y, layer, nx, ny, explored,
                t_build - t0_all, _dur)
        if not found:
            return None

        # reconstruction
        cells: List[Tuple[int, int]] = []
        cx_, cy_ = gx, gy
        guard = 0
        while (cx_, cy_) != (sx, sy):
            cells.append((cx_, cy_))
            p = int(parent[cx_, cy_])
            if p < 0 or guard > nx * ny:  # parent manquant (ne doit pas arriver)
                return None
            cx_, cy_ = divmod(p, ny)
            guard += 1
        cells.append((sx, sy))
        cells.reverse()
        pts = [grid.point_at(ix, iy) for ix, iy in cells]
        pts[0] = Point(a.x, a.y)
        pts[-1] = Point(b.x, b.y)
        path = _simplify_collinear(pts)
        self._stats["success"] += 1
        if layer != 0:
            log.debug("route_pair %s: couche %d (pénalité via %.1fmm incluse au coût global)",
                      net.net_id, layer, self.via_penalty)
        return path

    @property
    def stats(self) -> Dict[str, int]:
        """Compteurs d'exécution (appels, succès, cellules explorées)."""
        return dict(self._stats)


def _simplify_collinear(points: List[Point], eps: float = 1e-9) -> List[Point]:
    """Supprime les points intermédiaires alignés (réduit le poids des RoutePath)."""
    if len(points) <= 2:
        return list(points)
    out = [points[0]]
    for i in range(1, len(points) - 1):
        p0, p1, p2 = out[-1], points[i], points[i + 1]
        cross = (p1.x - p0.x) * (p2.y - p0.y) - (p1.y - p0.y) * (p2.x - p0.x)
        dot = (p1.x - p0.x) * (p2.x - p1.x) + (p1.y - p0.y) * (p2.y - p1.y)
        if abs(cross) > eps or dot < 0:  # coude ou demi-tour → on garde
            out.append(p1)
    out.append(points[-1])
    return out


def offset_polyline(points: List[Point], offset: float) -> List[Point]:
    """Décale un polygone ouvert de `offset` mm perpendiculairement (jointures mitrées).

    Utilisé pour le second membre d'une paire différentielle : le chemin garde
    un espacement constant vis-à-vis du premier membre.
    """
    if len(points) < 2 or offset == 0.0:
        return list(points)
    normals: List[Tuple[float, float]] = []
    for i in range(len(points) - 1):
        dx = points[i + 1].x - points[i].x
        dy = points[i + 1].y - points[i].y
        ln = math.hypot(dx, dy)
        if ln < 1e-12:
            normals.append((0.0, 0.0))
        else:
            normals.append((-dy / ln, dx / ln))
    out: List[Point] = []
    for i, p in enumerate(points):
        if i == 0:
            nx_, ny_ = normals[0]
        elif i == len(points) - 1:
            nx_, ny_ = normals[-1]
        else:
            ax, ay = normals[i - 1]
            bx, by = normals[i]
            nx_, ny_ = ax + bx, ay + by
            ln = math.hypot(nx_, ny_)
            if ln < 1e-9:  # demi-tour : normal du segment suivant
                nx_, ny_ = normals[i]
            else:
                nx_, ny_ = nx_ / ln, ny_ / ln
        out.append(Point(p.x + nx_ * offset, p.y + ny_ * offset))
    return out
