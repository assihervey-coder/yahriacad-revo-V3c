"""Générateur Gerber RS-274X réel — couches cuivre, silkscreen, contour, forage.

Format 4.6 (%FSLAX46Y46*%), unités mm. Coordonnées converties en entiers
(int(round(mm * 1e4))). Fichiers : {name}-F_Cu.gbr, {name}-B_Cu.gbr,
{name}-F_Silkscreen.gbr, {name}-Edge_Cuts.gbr, {name}.drl (Excellon).
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

from shared.geometry import Point
from shared.utilities import get_logger

log = get_logger(__name__)

VIA_SIZE_MM = 0.6
VIA_DRILL_MM = 0.3
SILK_WIDTH_MM = 0.15
EDGE_WIDTH_MM = 0.1

_SCALE = 10_000  # format 4.6 → 6 décimales


def _fmt(v: float) -> str:
    """Nombre Gerber avec décimales utiles (apertures)."""
    s = f"{float(v):.6f}".rstrip("0").rstrip(".")
    return s if s not in ("", "-") else "0"


def _coord(v: float) -> str:
    """mm → entier Gerber 4.6 (ex: 12.3456 mm → 123456)."""
    return str(int(round(float(v) * _SCALE)))


def _sanitize(name: str) -> str:
    keep = []
    for ch in (name or "pcb"):
        keep.append(ch if (ch.isalnum() or ch in "-_.") else "_")
    return "".join(keep).strip("_") or "pcb"


class _ApertureTable:
    """Table d'apertures RS-274X : spec tuple → D-code (à partir de D10).

    Specs : ("C", width) cercle, ("R", w, h) rectangle, ("MR", w, h, rot)
    rectangle tourné via aperture macro (primitive outline 4).
    """

    def __init__(self) -> None:
        self._specs: Dict[tuple, int] = {}
        self._next = 10

    def get(self, spec: tuple) -> int:
        if spec not in self._specs:
            self._specs[spec] = self._next
            self._next += 1
        return self._specs[spec]

    def definitions(self) -> List[str]:
        """Lignes %AM...*% (macros) puis %ADD...*% (apertures)."""
        out: List[str] = []
        for spec in self._specs:
            if spec[0] == "MR":
                out.append(self._macro_line(spec))
        for spec, dcode in self._specs.items():
            out.append(f"%ADD{dcode}{self._define(spec)}*%")
        return out

    def _macro_name(self, spec: tuple) -> str:
        w, h, rot = spec[1], spec[2], spec[3]
        return f"ROTRECT{_fmt(w)}X{_fmt(h)}R{_fmt(rot)}"

    def _macro_line(self, spec: tuple) -> str:
        w, h, rot = spec[1], spec[2], spec[3]
        a = math.radians(rot)
        c, s = math.cos(a), math.sin(a)
        pts = []
        for lx, ly in ((w / 2, h / 2), (-w / 2, h / 2),
                       (-w / 2, -h / 2), (w / 2, -h / 2)):
            pts.append((lx * c - ly * s, lx * s + ly * c))
        body = "4,1,4," + ",".join(f"{_fmt(x)},{_fmt(y)}" for x, y in pts) + ",0"
        return f"%AM{self._macro_name(spec)}*{body}*%"

    def _define(self, spec: tuple) -> str:
        kind = spec[0]
        if kind == "C":                     # ("C", width)
            return f"C,{_fmt(spec[1])}"
        if kind == "R":                     # ("R", w, h)
            return f"R,{_fmt(spec[1])}X{_fmt(spec[2])}"
        if kind == "MR":                    # ("MR", w, h, rot) — rectangle tourné
            return self._macro_name(spec)
        raise ValueError(f"aperture inconnue: {spec}")


class GerberGenerator:
    """Génère l'ensemble des fichiers Gerber/Excellon d'un DesignGraph."""

    def __init__(self, graph: Any, name: Optional[str] = None) -> None:
        self.graph = graph
        self.name = _sanitize(name or getattr(graph, "name", "") or "pcb")

    # -- API -------------------------------------------------------------------
    def generate(self) -> Dict[str, str]:
        """dict[nom_fichier, contenu] — couches cuivre + silk + contour + drills."""
        files: Dict[str, str] = {}
        for index, lname in self._copper_layers():
            tag = lname.replace(".", "_")
            files[f"{self.name}-{tag}.gbr"] = self._copper(index, lname)
        files[f"{self.name}-F_Silkscreen.gbr"] = self._silkscreen()
        files[f"{self.name}-Edge_Cuts.gbr"] = self._outline()
        files[f"{self.name}.drl"] = self._drill()
        log.info("gerbers générés: %d fichiers (%s)", len(files), self.name)
        return files

    # -- helpers -----------------------------------------------------------------
    def _board_size(self) -> Tuple[float, float]:
        bs = getattr(self.graph, "board_size", (50.0, 40.0))
        if isinstance(bs, dict):
            return (float(bs.get("w", 50.0)), float(bs.get("h", 40.0)))
        if isinstance(bs, (tuple, list)) and len(bs) >= 2:
            return (float(bs[0]), float(bs[1]))
        return (50.0, 40.0)

    def _copper_layers(self) -> List[Tuple[int, str]]:
        """Toutes les couches cuivre du stackup design_core (index dense)."""
        out: List[Tuple[int, str]] = []
        for i, layer in enumerate(list(getattr(self.graph, "layers", []) or [])):
            out.append((i, str(getattr(layer, "name", f"L{i}"))))
        return out or [(0, "F.Cu"), (1, "B.Cu")]

    def _header(self, comment: str, apertures: _ApertureTable) -> List[str]:
        lines = [f"G04 {comment} — PCB_AI_DESIGNER_V3*",
                 "%FSLAX46Y46*%", "%MOMM*%", "%LPD*%", "G01*", "G75*"]
        lines.extend(apertures.definitions())
        return lines

    def _pad_rotation(self, comp: Any) -> float:
        return float(getattr(comp, "rotation", 0.0) or 0.0) % 360.0

    def _pad_aperture(self, aps: _ApertureTable, comp: Any, pad: Any) -> int:
        """D-code d'aperture pour un pad (rect, swap 90/270, macro si angle quelconque)."""
        w, h = float(pad.w), float(pad.h)
        rot = self._pad_rotation(comp)
        if abs(rot - 90.0) < 0.01 or abs(rot - 270.0) < 0.01:
            return aps.get(("R", h, w))
        if abs(rot - 180.0) < 0.01 or rot < 0.01:
            return aps.get(("R", w, h))
        return aps.get(("MR", w, h, rot))

    def _pad_abs(self, comp: Any, pad: Any) -> Point:
        """Position ABSOLUE d'un pad (offset local tourné + centre du composant)."""
        rot = self._pad_rotation(comp)
        a = math.radians(rot)
        c, s = math.cos(a), math.sin(a)
        lx, ly = float(pad.x), float(pad.y)
        return Point(float(comp.x) + lx * c - ly * s, float(comp.y) + lx * s + ly * c)

    # -- couches -------------------------------------------------------------------
    def _copper(self, index: int, layer_name: str) -> str:
        aps = _ApertureTable()
        body: List[str] = []
        current: Optional[int] = None

        def select(code: int) -> None:
            nonlocal current
            if current != code:
                body.append(f"D{code}*")
                current = code

        # 1) traces des nets routés sur cette couche
        for net_id in sorted(self.graph.nets):
            path = getattr(self.graph.nets[net_id], "path", None)
            if path is None or int(getattr(path, "layer", 0)) != index:
                continue
            pts = list(getattr(path, "points", []) or [])
            if len(pts) < 2:
                continue
            select(aps.get(("C", float(getattr(path, "width_mm", 0.2)))))
            body.append(f"X{_coord(pts[0].x)}Y{_coord(pts[0].y)}D02*")
            for p in pts[1:]:
                body.append(f"X{_coord(p.x)}Y{_coord(p.y)}D01*")

        # 2) vias touchant cette couche
        via_code: Optional[int] = None
        for net_id in sorted(self.graph.nets):
            path = getattr(self.graph.nets[net_id], "path", None)
            for via in (getattr(path, "vias", []) or []) if path is not None else []:
                f_idx = int(via[1]) if len(via) > 1 else 0
                t_idx = int(via[2]) if len(via) > 2 else 1
                if index not in (f_idx, t_idx):
                    continue
                if via_code is None:
                    via_code = aps.get(("C", VIA_SIZE_MM))
                select(via_code)
                body.append(f"X{_coord(via[0].x)}Y{_coord(via[0].y)}D03*")

        # 3) pads flashés (rect tourné selon la rotation du composant)
        for ref in sorted(self.graph.components):
            comp = self.graph.components[ref]
            for pad in list(getattr(comp, "pads", []) or []):
                if int(getattr(pad, "layer", 0) or 0) != index:
                    continue
                select(self._pad_aperture(aps, comp, pad))
                pos = self._pad_abs(comp, pad)
                body.append(f"X{_coord(pos.x)}Y{_coord(pos.y)}D03*")

        lines = self._header(f"{layer_name} copper", aps) + body + ["M02*"]
        return "\n".join(lines) + "\n"

    def _silkscreen(self) -> str:
        aps = _ApertureTable()
        body: List[str] = []
        select_code = aps.get(("C", SILK_WIDTH_MM))
        body.append(f"D{select_code}*")
        for ref in sorted(self.graph.components):
            comp = self.graph.components[ref]
            w, h = getattr(comp, "bbox", (2.0, 2.0))
            rot = self._pad_rotation(comp)
            cx, cy = float(comp.x), float(comp.y)
            a = math.radians(rot)
            c, s = math.cos(a), math.sin(a)
            corners = []
            for lx, ly in ((-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2)):
                corners.append(Point(cx + lx * c - ly * s, cy + lx * s + ly * c))
            corners.append(corners[0])  # ferme le rectangle
            body.append(f"G04 {ref}*")
            body.append(f"X{_coord(corners[0].x)}Y{_coord(corners[0].y)}D02*")
            for p in corners[1:]:
                body.append(f"X{_coord(p.x)}Y{_coord(p.y)}D01*")
        lines = self._header("F.Silkscreen outlines", aps) + body + ["M02*"]
        return "\n".join(lines) + "\n"

    def _outline(self) -> str:
        aps = _ApertureTable()
        w, h = self._board_size()
        code = aps.get(("C", EDGE_WIDTH_MM))
        corners = [(0.0, 0.0), (w, 0.0), (w, h), (0.0, h), (0.0, 0.0)]
        body = [f"D{code}*", f"X{_coord(corners[0][0])}Y{_coord(corners[0][1])}D02*"]
        for x, y in corners[1:]:
            body.append(f"X{_coord(x)}Y{_coord(y)}D01*")
        lines = self._header("Edge.Cuts outline", aps) + body + ["M02*"]
        return "\n".join(lines) + "\n"

    def _drill(self) -> str:
        hits: List[Tuple[float, float]] = []
        for net in self.graph.nets.values():
            path = getattr(net, "path", None)
            for via in (getattr(path, "vias", []) or []) if path is not None else []:
                hits.append((float(via[0].x), float(via[0].y)))
        lines = [
            f"; {self.name}.drl — PCB_AI_DESIGNER_V3",
            "; drill: vias (Excellon, METRIC)",
            "M48",
            "METRIC,TZ",
            f"T1 C{_fmt(VIA_DRILL_MM)}",
            "%",
            "G90",
            "G05",
            "T1",
        ]
        for x, y in hits:
            lines.append(f"X{x:.3f}Y{y:.3f}")
        lines.append("M30")
        return "\n".join(lines) + "\n"
