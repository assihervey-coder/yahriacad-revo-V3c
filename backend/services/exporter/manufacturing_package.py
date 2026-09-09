"""Package manufacturier complet — gerbers + drill + BOM + POS + IPC-2581 + README.

Écrit les fichiers dans data/projects/{project_id}/exports/{ts}/ (ou un
output_dir fourni), retourne dict[nom, bytes] et émet EXPORT_COMPLETED.
"""
from __future__ import annotations

import io
import time
import zipfile
from pathlib import Path
from typing import Any

from shared.events import EventTypes, make_event
from shared.utilities import get_logger

from services.exporter.bom_generator import BOMGenerator
from services.exporter.gerber_generator import GerberGenerator
from services.exporter.ipc2581_generator import IPC2581Generator
from services.exporter.pickplace_generator import PickPlaceGenerator
from services.integration_utils import publish_event_now
from services.manufacturing_intelligence.cost_estimator import CostEstimator
from services.manufacturing_intelligence.factory_profiles import get_profile
from services.manufacturing_intelligence.yield_predictor import YieldPredictor

log = get_logger(__name__)


class ManufacturingPackage:
    """Assemble le dossier complet à envoyer à l'usine."""

    def __init__(self, graph: Any, factory: str = "jlcpcb") -> None:
        self.graph = graph
        self.factory = factory

    # -- contenu -----------------------------------------------------------------
    def build(self, output_dir: str | None = None) -> dict[str, bytes]:
        """Génère tous les fichiers, les écrit sur disque et les retourne en bytes."""
        gerbers = GerberGenerator(self.graph).generate()
        files: dict[str, bytes] = {}
        for fname, content in gerbers.items():
            files[fname] = content.encode("utf-8")
        files["ipc2581.xml"] = IPC2581Generator(
            self.graph, supplier=self.factory).generate().encode("utf-8")
        files["bom.csv"] = BOMGenerator(self.graph).generate_csv().encode("utf-8")
        files["bom.json"] = BOMGenerator(self.graph).generate_json().encode("utf-8")
        files["pickplace-top.csv"] = PickPlaceGenerator(
            self.graph).generate_csv("top").encode("utf-8")
        files["pickplace-bottom.csv"] = PickPlaceGenerator(
            self.graph).generate_csv("bottom").encode("utf-8")
        files["readme.txt"] = self._readme().encode("utf-8")

        target = Path(output_dir) if output_dir else self._default_dir()
        target.mkdir(parents=True, exist_ok=True)
        for fname, data in files.items():
            (target / fname).write_bytes(data)
        log.info("package manufacturier écrit dans %s (%d fichiers)", target, len(files))

        publish_event_now(make_event(
            EventTypes.EXPORT_COMPLETED,
            {"project_id": getattr(self.graph, "project_id", ""),
             "factory": self.factory,
             "files": sorted(files),
             "output_dir": str(target)},
            project_id=str(getattr(self.graph, "project_id", "")),
            source="exporter",
        ))
        return files

    def make_zip(self, output_path: str | None = None) -> bytes:
        """Archive zip du package complet (en mémoire)."""
        files = self.build()
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for fname, data in sorted(files.items()):
                zf.writestr(fname, data)
        payload = buf.getvalue()
        if output_path:
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            Path(output_path).write_bytes(payload)
        return payload

    # -- internes -----------------------------------------------------------------
    def _default_dir(self) -> Path:
        ts = time.strftime("%Y%m%d_%H%M%S")
        project = str(getattr(self.graph, "project_id", "") or "default")
        return Path("data") / "projects" / project / "exports" / ts

    def _readme(self) -> str:
        profile = get_profile(self.factory)
        cost = CostEstimator(profile).estimate(self.graph)
        yield_pred = YieldPredictor().predict(self.graph, profile)
        w, h = self.graph.board_size if isinstance(self.graph.board_size, (tuple, list)) \
            else (50.0, 40.0)
        n_layers = len(list(getattr(self.graph, "layers", []) or []))
        lines = [
            "PACKAGE MANUFACTURIER — PCB_AI_DESIGNER_V3",
            "==========================================",
            f"Projet           : {getattr(self.graph, 'name', '')} "
            f"({getattr(self.graph, 'project_id', '')})",
            f"Usine cible      : {profile.name}",
            f"Taille carte     : {w} x {h} mm ({n_layers} couches)",
            f"Composants       : {len(self.graph.components)}",
            f"Nets routés      : {sum(1 for n in self.graph.nets.values() if n.routed)}"
            f" / {len(self.graph.nets)}",
            "",
            "COÛTS ESTIMÉS (qté 1)",
            f"  carte          : {cost.board_usd:.2f} $",
            f"  assemblage     : {cost.assembly_usd:.2f} $",
            f"  composants     : {cost.components_usd:.2f} $",
            f"  TOTAL          : {cost.total_usd:.2f} $",
            "",
            f"RENDEMENT ATTENDU : {100 * yield_pred.expected_yield:.1f}%",
        ]
        for risk in yield_pred.risk_factors:
            lines.append(f"  - risque: {risk}")
        lines += [
            "",
            "CONTENU DU PACKAGE",
            "  *-F_Cu.gbr, *-B_Cu.gbr   : couches cuivre (Gerber RS-274X, mm)",
            "  *-F_Silkscreen.gbr       : sérigraphie (contours composants)",
            "  *-Edge_Cuts.gbr          : contour de la carte",
            "  *.drl                    : forage Excellon (vias)",
            "  bom.csv / bom.json       : nomenclature groupée par MPN",
            "  pickplace-*.csv          : placement machines SMT (top/bottom)",
            "  ipc2581.xml              : échange IPC-2581",
            "",
            "CONTRAINTES USINE",
            f"  trace min {profile.min_trace_mm} mm · clearance min "
            f"{profile.min_clearance_mm} mm · trou min {profile.min_hole_mm} mm · "
            f"{profile.max_layers} couches max",
        ]
        return "\n".join(lines) + "\n"
