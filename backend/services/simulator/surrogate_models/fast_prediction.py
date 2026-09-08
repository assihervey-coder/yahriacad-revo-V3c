"""FastPredictor — prédiction instantanée des résultats de simulation.

Utilise les surrogates entraînés quand ils existent, sinon des formules
analytiques simplifiées (fallback déterministe).
"""
from __future__ import annotations

import math
from typing import Any, Dict, Optional

from shared.utilities import get_logger

from services.design_core import DesignGraph

from services.router.topological import hpwl_wire_length
from services.simulator.surrogate_models.neural_surrogates import NeuralSurrogate

log = get_logger("simulator.fast_predict")

FEATURE_NAMES = ("n_comp", "density", "power_sum", "wire_length")


class FastPredictor:
    """Prédicteur hybride : surrogate ML si entraîné, sinon analytique."""

    def __init__(self, surrogates: Optional[Dict[str, NeuralSurrogate]] = None) -> None:
        self.surrogates = surrogates or {}

    def features(self, graph: DesignGraph) -> Dict[str, float]:
        """Vecteur de features du design (nommé, ordre stable)."""
        n_comp = len(graph.components)
        bw, bh = graph.board_size
        density = graph.utilization()
        power_sum = sum(c.power_w for c in graph.components.values())
        wire_length = hpwl_wire_length(graph)
        return dict(zip(FEATURE_NAMES, (float(n_comp), float(density),
                                        float(power_sum), float(wire_length))))

    def predict(self, graph: DesignGraph) -> Dict[str, Dict[str, Any]]:
        """{sim_kind: {"value": ..., "source": "surrogate"|"analytic", "passed": ...}}."""
        feats = self.features(graph)
        x = [feats[k] for k in FEATURE_NAMES]
        out: Dict[str, Dict[str, Any]] = {}

        for sim_kind in ("thermal", "si", "pi", "emi"):
            surrogate = self.surrogates.get(sim_kind)
            if surrogate is not None and surrogate.trained:
                value = float(surrogate.predict(x)[0])
                out[sim_kind] = {"value": round(value, 4), "source": "surrogate"}
            else:
                value, passed = self._analytic(sim_kind, graph, feats)
                out[sim_kind] = {"value": round(value, 4), "source": "analytic",
                                 "passed": passed}
        log.debug("fast_predict : %s", {k: v["value"] for k, v in out.items()})
        return out

    # ----------------------------------------------------------------- private
    @staticmethod
    def _analytic(sim_kind: str, graph: DesignGraph,
                  feats: Dict[str, float]) -> tuple:
        """Formules analytiques simplifiées (fallback sans surrogate)."""
        power_sum = feats["power_sum"]
        if sim_kind == "thermal":
            # montée en T linéaire ~ 8 °C/W sur petite carte FR4 + ambiant 25
            max_temp = 25.0 + 8.0 * power_sum * (1.0 + 0.5 * feats["density"])
            return max_temp, max_temp < 85.0
        if sim_kind == "si":
            # pire |Γ| proxy : désadaptation générique 0.1 + densité
            gamma = 0.05 + 0.15 * feats["density"]
            return gamma, gamma < 0.2
        if sim_kind == "pi":
            # droop proxy : 1 mV par 0.1 W chargés
            droop_mv = 10.0 * power_sum * 0.1
            return droop_mv, droop_mv < 50.0
        # emi : aire de boucle proxy
        bw, bh = graph.board_size
        loop_area = 0.1 * bw * bh * feats["density"] * min(power_sum, 5.0)
        return loop_area, loop_area < 1500.0
