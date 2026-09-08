"""router — cerveau décisionnel du routage PCB (topologie, A*, différentiel, SI)."""
from services.router.topological import (
    build_net_topology,
    classify_component,
    component_pad_positions,
    hpwl_wire_length,
    is_differential_net,
    is_high_speed_net,
    is_power_net,
    net_centroid,
    net_length_estimate,
    net_pad_positions,
    pad_position,
    voltage_of_net,
)
from services.router.geometrical import MazeRouter, offset_polyline, segment_segment_distance
from services.router.impedance_control import (
    assign_trace_widths,
    effective_er,
    microstrip_width,
    microstrip_z0,
    propagation_delay_ns,
)
from services.router.differential_pairs import DifferentialPairRouter, find_differential_pairs
from services.router.high_speed import add_serpentine, length_match, polyline_length
from services.router.via_placer import ViaPlan, estimate_via_cost_pf, plan_vias
from services.router.via_minimizer import minimize as minimize_vias
from services.router.route_optimizer import rip_up_and_reroute, route_net_segments
from services.router.engine import RouterEngine, RoutingResult

__all__ = [
    # topologie (fondation réutilisable partout)
    "pad_position", "component_pad_positions", "net_pad_positions",
    "build_net_topology", "net_centroid", "net_length_estimate",
    "hpwl_wire_length", "is_power_net", "is_high_speed_net",
    "is_differential_net", "voltage_of_net", "classify_component",
    # géométrie de routage
    "MazeRouter", "offset_polyline", "segment_segment_distance",
    # impédance / largeurs
    "microstrip_width", "microstrip_z0", "effective_er",
    "propagation_delay_ns", "assign_trace_widths",
    # différentiel & hautes vitesses
    "DifferentialPairRouter", "find_differential_pairs",
    "length_match", "add_serpentine", "polyline_length",
    # vias
    "ViaPlan", "estimate_via_cost_pf", "plan_vias", "minimize_vias",
    # optimisation & moteur
    "rip_up_and_reroute", "route_net_segments", "RouterEngine", "RoutingResult",
]
