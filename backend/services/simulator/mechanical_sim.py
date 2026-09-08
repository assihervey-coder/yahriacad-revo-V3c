"""Simulation mécanique — première fréquence propre de la plaque et proxy de planéité.

Plaque mince simplement appuyée : f = (π/2)·√(E/(12ρ(1−ν²)))·(1/L²)·k, avec
k = (λ²/π²)·h·support_factor (λ² = 19.74, h = épaisseur, facteur de maintien
par trous de montage). Planéité : proxy par densité locale de composants.
"""
from __future__ import annotations

import math
import time
from typing import Any, Dict, List, Tuple

import numpy as np

from shared.utilities import get_logger

from services.design_core import DesignGraph

from services.simulator.base import BaseSim, SimResult

E_FR4 = 2.2e10           # Pa (module de Young FR4 in-plane)
RHO_FR4 = 1950.0         # kg/m³ (FR4 + cuivre)
NU_FR4 = 0.15            # coefficient de Poisson
LAMBDA2 = 19.74          # λ² mode (1,1) — plaque simplement appuyée
MIN_MODE_HZ = 200.0
CELL_MM = 5.0
MAX_COVERAGE = 0.6       # densité locale max (planéité / contraintes)


class MechanicalSim(BaseSim):
    """Fréquence propre approximative + indice de contrainte de montage."""

    sim_kind = "mechanical"

    def __init__(self, thickness_mm: float = 1.6, min_mode_hz: float = MIN_MODE_HZ,
                 e_pa: float = E_FR4, rho: float = RHO_FR4, nu: float = NU_FR4) -> None:
        self.thickness_mm = thickness_mm
        self.min_mode_hz = min_mode_hz
        self.e_pa = e_pa
        self.rho = rho
        self.nu = nu

    def run(self, graph: DesignGraph) -> SimResult:
        t0 = time.perf_counter()
        notes: List[str] = []
        bw, bh = graph.board_size
        h = self.thickness_mm * 1e-3
        length = max(bw, bh) * 1e-3                      # plus grande dimension (m)

        # trous de montage → rigidification du maintien
        mounts = [c for c in graph.components.values()
                  if c.ref.upper().startswith(("MH", "H")) and len(c.ref) <= 4]
        support_factor = 1.0 + 0.08 * len(mounts)
        k = (LAMBDA2 / math.pi ** 2) * h * support_factor

        base = math.sqrt(self.e_pa / (12.0 * self.rho * (1.0 - self.nu ** 2)))
        first_mode_hz = (math.pi / 2.0) * base * (1.0 / length ** 2) * k

        # proxy planéité : densité locale de composants (grille 5 mm)
        stress_index, worst_cell = self._stress_index(graph, bw, bh)
        flatness_um = 25.0 + 120.0 * stress_index        # déformation estimée (µm)
        mode_ok = first_mode_hz > self.min_mode_hz
        flat_ok = stress_index < MAX_COVERAGE
        passed = mode_ok and flat_ok
        if not mode_ok:
            notes.append(
                f"premier mode {first_mode_hz:.0f} Hz ≤ {self.min_mode_hz:.0f} Hz "
                f"— réduire la plus grande dimension ou ajouter des fixations")
        if not flat_ok:
            notes.append(
                f"densité locale {stress_index:.0%} > {MAX_COVERAGE:.0%} en {worst_cell} "
                f"— répartir les composants (risque de bombement / reflow)")

        metrics: Dict[str, Any] = {
            "first_mode_hz": round(first_mode_hz, 1),
            "limit_hz": self.min_mode_hz,
            "support_factor": round(support_factor, 3),
            "mounting_holes": len(mounts),
            "flatness_proxy_um": round(flatness_um, 1),
            "stress_index": round(stress_index, 3),
            "worst_cell": worst_cell,
        }
        log.info("mécanique : f1=%.0f Hz, contrainte=%.0f%% → %s",
                 first_mode_hz, stress_index * 100, "PASS" if passed else "FAIL")
        return SimResult(sim_kind=self.sim_kind, metrics=metrics, passed=passed,
                         runtime_s=time.perf_counter() - t0, notes=notes)

    def _stress_index(self, graph: DesignGraph, bw: float, bh: float) -> Tuple[float, Tuple[int, int]]:
        """Couverture maximale des composants par cellule 5 mm (0..1)."""
        nx = max(1, int(math.ceil(bw / CELL_MM)))
        ny = max(1, int(math.ceil(bh / CELL_MM)))
        area = np.zeros((nx, ny), dtype=np.float64)
        cell_area = CELL_MM * CELL_MM
        for comp in graph.components.values():
            if not comp.placed:
                continue
            w, h = comp.bbox
            i0 = max(0, int((comp.x - w / 2) / CELL_MM))
            i1 = min(nx - 1, int((comp.x + w / 2) / CELL_MM))
            j0 = max(0, int((comp.y - h / 2) / CELL_MM))
            j1 = min(ny - 1, int((comp.y + h / 2) / CELL_MM))
            for i in range(i0, i1 + 1):
                for j in range(j0, j1 + 1):
                    area[i, j] += min(1.0, (w * h) / cell_area)
        im, jm = np.unravel_index(np.argmax(area), area.shape)
        return float(area[im, jm]), (int(im), int(jm))
