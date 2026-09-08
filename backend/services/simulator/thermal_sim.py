"""Simulation thermique — diffusion de chaleur en régime permanent (numpy).

Carte discrétisée à 1 mm ; sources = composants (power_w injecté sur leur
empreinte) ; bords isothermes à 25 °C ; équation de Laplace résolue par
itérations de Jacobi vectorisées (tolérance 1e-4, max 5000 itérations),
conductivité effective FR4 (cuivre inclus).
"""
from __future__ import annotations

import math
import time
from typing import Any, Dict, List, Tuple

import numpy as np

from shared.utilities import get_logger

from services.design_core import DesignGraph

from services.simulator.base import BaseSim, SimResult

log = get_logger("simulator.thermal")

AMBIENT_C = 25.0
MAX_TEMP_C = 85.0           # limite de passage (Tg FR4 avec marge)
K_FR4_EFF = 15.0            # W/(m·K) — conductivité effective (pours cuivre)
BOARD_THICKNESS_MM = 1.6
MAX_GRID_DIM = 320          # borne mémoire (augmente la taille de cellule au-delà)


class ThermalSim(BaseSim):
    """Solveur de Laplace stationnaire par différences finies (Jacobi)."""

    sim_kind = "thermal"

    def __init__(self, ambient_c: float = AMBIENT_C, k_eff: float = K_FR4_EFF,
                 thickness_mm: float = BOARD_THICKNESS_MM, tol: float = 1e-4,
                 max_iter: int = 5000, max_temp_c: float = MAX_TEMP_C) -> None:
        self.ambient_c = ambient_c
        self.k_eff = k_eff
        self.thickness_mm = thickness_mm
        self.tol = tol
        self.max_iter = max_iter
        self.max_temp_c = max_temp_c

    # ------------------------------------------------------------------ public
    def run(self, graph: DesignGraph) -> SimResult:
        t0 = time.perf_counter()
        notes: List[str] = []
        bw, bh = graph.board_size

        # grille : cellule 1 mm, bornée pour la mémoire
        cell = 1.0
        while max(bw, bh) / cell > MAX_GRID_DIM:
            cell *= 2.0
        nx = max(4, int(round(bw / cell)) + 1)
        ny = max(4, int(round(bh / cell)) + 1)

        # ---- sources : W injectés par cellule (répartis sur l'empreinte)
        power = np.zeros((nx, ny), dtype=np.float64)
        hot_components: List[Tuple[str, float, float, float]] = []
        total_power = 0.0
        for comp in graph.components.values():
            if not comp.placed or comp.power_w <= 0.0:
                continue
            total_power += comp.power_w
            w, h = comp.bbox
            i0 = max(0, int((comp.x - w / 2) / cell))
            i1 = min(nx - 1, int((comp.x + w / 2) / cell))
            j0 = max(0, int((comp.y - h / 2) / cell))
            j1 = min(ny - 1, int((comp.y + h / 2) / cell))
            n_cells = max(1, (i1 - i0 + 1) * (j1 - j0 + 1))
            cell_area_m2 = (cell * 1e-3) ** 2
            # densité de flux (W/m²) : la puissance du composant est étalée
            flux = comp.power_w / (n_cells * cell_area_m2)
            power[i0:i1 + 1, j0:j1 + 1] += flux
            hot_components.append((comp.ref, comp.power_w, comp.x, comp.y))

        if total_power <= 0.0:
            notes.append("aucune dissipation : carte isotherme à l'ambiant")
            return SimResult(
                sim_kind=self.sim_kind,
                metrics={"max_temp_c": self.ambient_c, "mean_temp_c": self.ambient_c,
                         "hotspot": None, "total_power_w": 0.0, "grid": [nx, ny],
                         "cell_mm": cell, "iterations": 0},
                passed=True, runtime_s=time.perf_counter() - t0, notes=notes,
            )

        # ---- terme source discrétisé : ΔT_stationnaire = p·dx²/(4·k·t) par cellule
        dx = cell * 1e-3                       # m
        k_t = self.k_eff * (self.thickness_mm * 1e-3)   # W/(m·K)·m = W/K par carré
        src = power * dx * dx / (4.0 * k_t)

        # ---- Jacobi : bords isothermes à l'ambiant, intérieur vectorisé
        temp = np.full((nx, ny), self.ambient_c, dtype=np.float64)
        temp[0, :] = temp[-1, :] = self.ambient_c
        temp[:, 0] = temp[:, -1] = self.ambient_c
        iterations = 0
        for iterations in range(1, self.max_iter + 1):
            new = temp.copy()
            core = (temp[:-2, 1:-1] + temp[2:, 1:-1] +
                    temp[1:-1, :-2] + temp[1:-1, 2:]) / 4.0 + src[1:-1, 1:-1]
            new[1:-1, 1:-1] = core
            delta = float(np.max(np.abs(new - temp)))
            temp = new
            if delta < self.tol:
                break

        interior = temp[1:-1, 1:-1]
        max_t = float(np.max(interior))
        mean_t = float(np.mean(interior))
        im, jm = np.unravel_index(np.argmax(interior), interior.shape)
        hotspot = (round((im + 1) * cell, 2), round((jm + 1) * cell, 2))

        # composant responsable du hotspot (le plus proche du point chaud)
        culprit, culprit_dist = None, math.inf
        for ref, pw, cx, cy in hot_components:
            d = math.hypot(cx - hotspot[0], cy - hotspot[1])
            if d < culprit_dist:
                culprit, culprit_dist = ref, d

        passed = max_t < self.max_temp_c
        if not passed:
            notes.append(
                f"hotspot {max_t:.1f} °C > {self.max_temp_c:.0f} °C près de {culprit} "
                f"({culprit_dist:.1f} mm) — éloigner la source ou ajouter du cuivre")
        notes.append(f"convergence Jacobi en {iterations} itérations "
                     f"(grille {nx}×{ny}, cellule {cell:.0f} mm)")

        metrics: Dict[str, Any] = {
            "max_temp_c": round(max_t, 2),
            "mean_temp_c": round(mean_t, 2),
            "hotspot": hotspot,
            "hotspot_component": culprit,
            "total_power_w": round(total_power, 3),
            "grid": [nx, ny],
            "cell_mm": cell,
            "iterations": iterations,
            "ambient_c": self.ambient_c,
            "limit_c": self.max_temp_c,
        }
        log.info("thermique : max %.1f °C @%s (moy %.1f °C, %.1f W, %d it) → %s",
                 max_t, hotspot, mean_t, total_power, iterations,
                 "PASS" if passed else "FAIL")
        return SimResult(sim_kind=self.sim_kind, metrics=metrics, passed=passed,
                         runtime_s=time.perf_counter() - t0, notes=notes)
