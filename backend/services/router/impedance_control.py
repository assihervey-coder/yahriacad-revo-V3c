"""Contrôle d'impédance — largeur de microstrip (formule standard inversée) et
affectation des largeurs de piste par classe de net.
"""
from __future__ import annotations

import math
from typing import Dict

from shared.utilities import get_logger

from services.design_core import DesignGraph

from services.router.topological import is_high_speed_net, is_power_net

log = get_logger("router.impedance")

DEFAULT_HEIGHT_UM = 210.0   # prépreg FR4 typique sous le cuivre externe (JLCPCB 7628)
DEFAULT_ER = 4.3


def effective_er(w_mm: float, er: float, height_um: float) -> float:
    """Permittivité effective du microstrip (approx. de Hammerstad)."""
    h = height_um / 1000.0
    u = max(w_mm, 1e-4) / h
    return (er + 1.0) / 2.0 + (er - 1.0) / 2.0 / math.sqrt(1.0 + 12.0 / u)


def microstrip_z0(w_mm: float, er: float = DEFAULT_ER,
                  height_um: float = DEFAULT_HEIGHT_UM) -> float:
    """Impédance d'une ligne microstrip (formules d'analyse standard, w/h quelconque).

    w/h < 1  : Z0 = 60/√εeff · ln(8h/w + w/4h)
    w/h ≥ 1  : Z0 = 120π/(√εeff · (w/h + 1.393 + 0.667·ln(w/h + 1.444)))
    """
    h = height_um / 1000.0
    u = max(w_mm, 1e-4) / h
    e_eff = effective_er(w_mm, er, height_um)
    if u < 1.0:
        return 60.0 / math.sqrt(e_eff) * math.log(8.0 / u + u / 4.0)
    return 120.0 * math.pi / (
        math.sqrt(e_eff) * (u + 1.393 + 0.667 * math.log(u + 1.444))
    )


def microstrip_width(impedance_ohm: float, er: float = DEFAULT_ER,
                     height_um: float = DEFAULT_HEIGHT_UM,
                     tol: float = 1e-4, max_iter: int = 200) -> float:
    """Largeur (mm) d'une ligne microstrip d'impédance donnée — inversion itérative.

    Z0 décroît monotonalement avec w : la suite w ← w·Z0(w)/Z0_cible converge
    (facteur de contraction ≈ 0.5 près de la solution). Tolérance 0.1 mΩ.
    """
    z_target = float(impedance_ohm)
    if z_target <= 0:
        raise ValueError("impédance cible doit être > 0")
    h = height_um / 1000.0
    w = h                                    # initialisation w = h
    for _ in range(max_iter):
        z = microstrip_z0(w, er, height_um)
        if abs(z - z_target) < tol:
            break
        w *= z / z_target
        w = min(max(w, 1e-3), 50.0 * h)      # bornes de sanité
    return round(w, 4)


def propagation_delay_ns(length_mm: float, er: float = DEFAULT_ER,
                         w_mm: float = 0.35, height_um: float = DEFAULT_HEIGHT_UM) -> float:
    """Délai de propagation (ns) : L / (c/√εeff)."""
    e_eff = effective_er(w_mm, er, height_um)
    speed_m_s = 299_792_458.0 / math.sqrt(e_eff)
    return (length_mm * 1e-3) / speed_m_s * 1e9


def assign_trace_widths(graph: DesignGraph, default_mm: float = 0.2,
                        power_mm: float = 0.5, min_mm: float = 0.2,
                        height_um: float = DEFAULT_HEIGHT_UM) -> Dict[str, float]:
    """Largeur de piste (mm) par net_id : power 0.5, high_speed/differential via
    microstrip_width(impédance cible, er couche 0), default 0.2.

    Toute largeur est clampée à `min_mm` (limite de fabrication, cf. DesignRules).
    """
    er = graph.layers[0].er if graph.layers else DEFAULT_ER
    widths: Dict[str, float] = {}
    for net in graph.nets.values():
        if is_power_net(net):
            w = power_mm
        elif (net.class_name or "").lower() == "differential":
            w = microstrip_width(net.impedance_target_ohm or 100.0, er, height_um)
        elif is_high_speed_net(net):
            w = microstrip_width(net.impedance_target_ohm or 50.0, er, height_um)
        else:
            w = default_mm
        widths[net.net_id] = max(round(w, 3), min_mm)
    log.debug("largeurs affectées : %d nets (50Ω ≈ %.3f mm sur %dµm)",
              len(widths), microstrip_width(50.0, er, height_um), height_um)
    return widths
