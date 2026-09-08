"""design_graph — source de vérité du projet PCB (composants, nets, couches, keepouts)."""
from services.design_core.design_graph.components import (
    FOOTPRINT_BBOX,
    Component,
    Pad,
    default_bbox_for_footprint,
)
from services.design_core.design_graph.geometry import (
    Keepout,
    bbox_area,
    bbox_gap_mm,
    component_bbox_mm,
    corners_of,
    make_polygon,
)
from services.design_core.design_graph.graph import DesignGraph
from services.design_core.design_graph.layers import Layer, make_default_stackup
from services.design_core.design_graph.nets import Net

__all__ = [
    "DesignGraph", "Component", "Pad", "Net", "Layer", "Keepout",
    "make_default_stackup", "default_bbox_for_footprint", "FOOTPRINT_BBOX",
    "component_bbox_mm", "bbox_gap_mm", "bbox_area", "corners_of", "make_polygon",
]
