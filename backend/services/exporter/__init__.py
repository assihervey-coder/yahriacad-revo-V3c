"""exporter — Gerber RS-274X, ODB++, IPC-2581, BOM, Pick&Place, package usine."""
from typing import Any

from shared.utilities import get_logger

from services.exporter.bom_generator import BOMGenerator
from services.exporter.gerber_generator import GerberGenerator
from services.exporter.ipc2581_generator import IPC2581Generator
from services.exporter.manufacturing_package import ManufacturingPackage
from services.exporter.odb_generator import ODBGenerator
from services.exporter.pickplace_generator import PickPlaceGenerator

__all__ = [
    "BOMGenerator",
    "ExportFacade",
    "GerberGenerator",
    "IPC2581Generator",
    "ManufacturingPackage",
    "ODBGenerator",
    "PickPlaceGenerator",
    "export",
]

log = get_logger(__name__)

_VALID_FORMATS = {"gerber", "odb", "ipc2581", "bom", "pickplace", "package"}


class ExportFacade:
    """Façade unique d'export : un DesignGraph → dict[fichier, contenu]."""

    def export(self, graph: Any, fmt: str) -> dict[str, Any]:
        """Exporte selon fmt ∈ {gerber, odb, ipc2581, bom, pickplace, package}."""
        key = (fmt or "").strip().lower()
        if key == "gerber":
            return dict(GerberGenerator(graph).generate())
        if key == "odb":
            return dict(ODBGenerator(graph).generate())
        if key == "ipc2581":
            return {"ipc2581.xml": IPC2581Generator(graph).generate()}
        if key == "bom":
            gen = BOMGenerator(graph)
            return {"bom.csv": gen.generate_csv(), "bom.json": gen.generate_json()}
        if key == "pickplace":
            gen = PickPlaceGenerator(graph)
            return {"pickplace-top.csv": gen.generate_csv("top"),
                    "pickplace-bottom.csv": gen.generate_csv("bottom")}
        if key == "package":
            return dict(ManufacturingPackage(graph).build())
        raise ValueError(f"format d'export inconnu: {fmt!r} — attendu parmi {sorted(_VALID_FORMATS)}")


def export(graph: Any, fmt: str) -> dict[str, Any]:
    """Raccourci module-level : ExportFacade().export(graph, fmt)."""
    return ExportFacade().export(graph, fmt)
