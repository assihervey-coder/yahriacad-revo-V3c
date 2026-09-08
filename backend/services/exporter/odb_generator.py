"""Générateur ODB++ simplifié — matrix, steps/pcb/layers, features, netlist.

Structure texte ODB++ (units mm, coordonnées 0.1 µm), empaquetée en tar.gz
en mémoire via tarfile.
"""
from __future__ import annotations

import io
import json
import math
import tarfile
from typing import Any, Dict, List, Tuple

from shared.utilities import get_logger

log = get_logger(__name__)

_ODB_SCALE = 10_000  # 0.1 µm par unité (simplification assumée)


def _c(v: float) -> int:
    return int(round(float(v) * _ODB_SCALE))


def _sanitize(name: str) -> str:
    return "".join(ch if (ch.isalnum() or ch in "-_") else "_" for ch in (name or "pcb"))


class ODBGenerator:
    """Produit une archive ODB++ (tar.gz) depuis un DesignGraph."""

    def __init__(self, graph: Any) -> None:
        self.graph = graph
        self.name = _sanitize(getattr(graph, "name", "") or "pcb")

    # -- fichiers texte ---------------------------------------------------------
    def generate_files(self) -> Dict[str, str]:
        """dict[chemin interne, contenu texte] de la structure ODB++."""
        files: Dict[str, str] = {}
        layers = self._copper_layers()

        # matrix
        matrix = ["UNITS=MM"]
        for i, (_idx, lname) in enumerate(layers, start=1):
            side = "TOP" if i == 1 else ("BOTTOM" if i == len(layers) else f"INNER{i}")
            matrix.append(f"L{{{self._tag(lname)}|{side}|{i}}}")
        files["matrix/matrix"] = "\n".join(matrix) + "\n"

        # step header
        w, h = self._board_size()
        files["steps/pcb/stephdr"] = "\n".join([
            "UNITS=MM",
            "X_ORIGIN=0",
            "Y_ORIGIN=0",
            f"SIZE_X={_c(w)}",
            f"SIZE_Y={_c(h)}",
            f"NAME=pcb",
            "",
        ])

        # features par couche
        for index, lname in layers:
            files[f"steps/pcb/layers/{self._tag(lname)}/features"] = self._features(index)

        # netlist
        files["steps/pcb/netlist"] = self._netlist()

        # info
        files["misc/info"] = json.dumps({
            "generator": "pcb_ai_designer_v3",
            "format": "ODB++ (simplified)",
            "project": getattr(self.graph, "project_id", ""),
            "name": self.name,
            "components": len(self.graph.components),
            "nets": len(self.graph.nets),
        }, indent=2) + "\n"
        return files

    def generate(self) -> Dict[str, bytes]:
        """Archive tar.gz en mémoire → {f"{name}.odb.tgz": bytes}."""
        payload = io.BytesIO()
        with tarfile.open(fileobj=payload, mode="w:gz") as tar:
            for path, text in self.generate_files().items():
                data = text.encode("utf-8")
                info = tarfile.TarInfo(name=f"{self.name}/{path}")
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
        log.info("ODB++ empaqueté: %s (%d fichiers internes)", self.name,
                 len(self.generate_files()))
        return {f"{self.name}.odb.tgz": payload.getvalue()}

    # -- internes -----------------------------------------------------------------
    def _board_size(self) -> Tuple[float, float]:
        bs = getattr(self.graph, "board_size", (50.0, 40.0))
        if isinstance(bs, (tuple, list)) and len(bs) >= 2:
            return (float(bs[0]), float(bs[1]))
        return (50.0, 40.0)

    def _copper_layers(self) -> List[Tuple[int, str]]:
        """Toutes les couches cuivre du stackup (index dense)."""
        return [(i, str(getattr(l, "name", f"L{i}")))
                for i, l in enumerate(list(getattr(self.graph, "layers", []) or []))] or \
            [(0, "F.Cu"), (1, "B.Cu")]

    @staticmethod
    def _pad_abs(comp: Any, pad: Any) -> Tuple[float, float]:
        """Position absolue d'un pad (offset local tourné + centre composant)."""
        rot = math.radians(float(getattr(comp, "rotation", 0.0) or 0.0))
        c, s = math.cos(rot), math.sin(rot)
        lx, ly = float(pad.x), float(pad.y)
        return (float(comp.x) + lx * c - ly * s, float(comp.y) + lx * s + ly * c)

    def _tag(self, lname: str) -> str:
        return _sanitize(lname.replace(".", "_").lower())

    def _features(self, index: int) -> str:
        """Fichier features : L (traces) et P (pads), polarité p, units mm."""
        lines = ["UNITS=MM", "#", f"# layer index {index}"]
        for net_id in sorted(self.graph.nets):
            path = getattr(self.graph.nets[net_id], "path", None)
            if path is None:
                continue
            if int(getattr(path, "layer", 0)) == index:
                pts = list(getattr(path, "points", []) or [])
                width = _c(float(getattr(path, "width_mm", 0.2)))
                for i in range(len(pts) - 1):
                    lines.append(
                        f"L {_c(pts[i].x)} {_c(pts[i].y)} {_c(pts[i+1].x)} {_c(pts[i+1].y)} "
                        f"r{width} p 0 ; net={net_id}")
            for via in (getattr(path, "vias", []) or []):
                f_idx = int(via[1]) if len(via) > 1 else 0
                t_idx = int(via[2]) if len(via) > 2 else 1
                if index in (f_idx, t_idx):
                    lines.append(f"P {_c(via[0].x)} {_c(via[0].y)} r6000 p 0 ; via net={net_id}")
        for ref in sorted(self.graph.components):
            comp = self.graph.components[ref]
            for pad in list(getattr(comp, "pads", []) or []):
                if int(getattr(pad, "layer", 0) or 0) != index:
                    continue
                ax, ay = self._pad_abs(comp, pad)
                lines.append(
                    f"P {_c(ax)} {_c(ay)} r{_c(max(float(pad.w), float(pad.h)) / 2)} "
                    f"p 0 ; pad={ref}.{getattr(pad, 'name', '')}")
        return "\n".join(lines) + "\n"

    def _netlist(self) -> str:
        lines = ["UNIT MM", "#"]
        for net_id in sorted(self.graph.nets):
            net = self.graph.nets[net_id]
            pins = " ".join(f"{ref}-{pad}" for ref, pad in
                            (getattr(net, "pins", []) or []))
            lines.append(f"NET {net_id}")
            if pins:
                lines.append(f" S {pins}")
        return "\n".join(lines) + "\n"
