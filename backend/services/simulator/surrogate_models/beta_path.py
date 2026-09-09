"""Voie β (bêta) — inférence rapide à la place du solveur complet.

`run_sim_smart()` est LE point de branchement unique entre les simulateurs
complets (thermique, SI, PI, CEM…) et les surrogates neuronaux :

  1. surrogate entraîné dispo  → SimResult β en ~µs (solveur contourné),
     métrique phare prédite, notes marquées « β » + latence mesurée ;
  2. sinon                     → solveur complet exécuté, l'échantillon
     (features du design, valeur mesurée) est ENREGISTRÉ dans le dataset
     persistant du surrogate → apprentissage continu, puis `maybe_train`
     déclenché automatiquement tous les `AUTOTRAIN_EVERY` échantillons.

Utilisé par MultiPhysicsCoupling.run(), run_loop() et SimulationAgent —
toute la plateforme passe donc par la même voie β transparente.
"""
from __future__ import annotations

import math
import time
from typing import Any

from shared.utilities import get_logger

from services.simulator.base import BaseSim, SimResult
from services.simulator.surrogate_models.manager import SurrogateManager

log = get_logger("simulator.beta_path")

# déclenchement de l'entraînement automatique (tous les N échantillons pleins)
AUTOTRAIN_EVERY = 10

# métrique phare prédite par surrogate, par kind de simulation
VALUE_KEYS = {
    "thermal": "max_temp_c",
    "si": "worst_gamma",
    "pi": "worst_ir_drop_mv",
    "emi": "estimated_loop_area_mm2",
    "em": "estimated_loop_area_mm2",
    "mechanical": "max_stress_mpa",
}

# seuils de passage (attributs réels des simulateurs, replis = constantes)
_LIMIT_ATTRS = {
    "thermal": ("max_temp_c", 85.0),
    "si": ("gamma_limit", 0.2),
    "pi": ("ir_drop_limit_mv", 50.0),
    "emi": ("loop_area_limit_mm2", 1500.0),
    "em": ("loop_area_limit_mm2", 1500.0),
}


def headline_value(kind: str, metrics: dict) -> float | None:
    """Valeur scalaire cible du surrogate dans un SimResult du solveur complet."""
    key = VALUE_KEYS.get(kind)
    if not key or not isinstance(metrics, dict):
        return None
    raw = metrics.get(key)
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _beta_limit(kind: str, sim: BaseSim) -> float:
    """Limite de passage lue sur l'instance du simulateur (repli constant)."""
    attr, default = _LIMIT_ATTRS.get(kind, ("", 0.0))
    if not attr:
        return default
    try:
        return float(getattr(sim, attr, default))
    except (TypeError, ValueError):
        return default


def _beta_passed(kind: str, value: float, sim: BaseSim) -> bool:
    """Verdict β : métrique phare sous sa limite (crosstalk CEM non évalué)."""
    return value < _beta_limit(kind, sim)


def _beta_result(kind: str, value: float, latency_ms: float,
                 sim: BaseSim) -> SimResult:
    """SimResult β — métrique phare prédite, solveur complet contourné."""
    notes: list[str] = [
        "β substitut neuronal — inférence rapide, solveur complet contourné",
        "métriques détaillées indisponibles en mode β (métrique phare seule)",
    ]
    if kind in ("emi", "em"):
        notes.append("crosstalk CEM non évalué en mode β")
    return SimResult(
        sim_kind=kind if kind != "em" else "emi",
        metrics={
            VALUE_KEYS[kind]: round(value, 4),
            "beta": True,
            "source": "surrogate",
            "latency_ms": round(latency_ms, 4),
        },
        passed=_beta_passed(kind, value, sim),
        runtime_s=latency_ms / 1000.0,
        notes=notes,
    )


def _record_and_autotrain(manager: SurrogateManager, kind: str,
                          features: dict, value: float) -> None:
    """Enregistre l'échantillon solveur-complet puis entraîne si seuil atteint."""
    try:
        n = manager.record(kind, features, value, meta={"source": "full_solver"})
        if n >= manager.min_samples and n % AUTOTRAIN_EVERY == 0:
            st = manager.maybe_train(kind)
            if st is not None:
                log.info("surrogate[%s] auto-entraîné (n=%d, R²=%s)",
                         kind, n, None if st.r2 is None else round(st.r2, 3))
    except Exception as exc:  # l'apprentissage ne doit jamais casser la simu
        log.debug("surrogate record/train[%s] impossible: %s", kind, exc)


def run_sim_smart(sim: BaseSim, graph: Any,
                  manager: SurrogateManager | None = None) -> tuple[SimResult, bool]:
    """Exécute `sim` avec priorité à la voie β si un surrogate est entraîné.

    Retourne (SimResult, beta_used). Sans manager, équivalent strict à
    sim.run(graph) (aucun overhead). Avec manager :
      - trained  → SimResult β (~µs) ;
      - sinon    → solveur complet + enregistrement + auto-train périodique.
    """
    if manager is None:
        return sim.run(graph), False

    # extraction des features (échec → solveur complet direct)
    try:
        from services.simulator.surrogate_models.fast_prediction import FastPredictor

        features = FastPredictor(manager=manager).features(graph)
    except Exception as exc:
        log.debug("features indisponibles (%s) — solveur complet", exc)
        return sim.run(graph), False

    # ---- voie β : surrogate entraîné ?
    try:
        fast = manager.predict_fast(sim.sim_kind, features)
    except Exception as exc:
        log.debug("predict_fast[%s] échoué: %s", sim.sim_kind, exc)
        fast = {"trained": False}
    if fast.get("trained") and fast.get("value") is not None:
        kind = sim.sim_kind if sim.sim_kind in VALUE_KEYS else "emi"
        result = _beta_result(kind, float(fast["value"]),
                              float(fast.get("latency_ms") or 0.0), sim)
        log.info("voie β [%s] : %.4f en %.3f ms (solveur contourné)",
                 sim.sim_kind, float(fast["value"]),
                 float(fast.get("latency_ms") or 0.0))
        return result, True

    # ---- solveur complet + boucle d'apprentissage continu
    t0 = time.perf_counter()
    result = sim.run(graph)
    runtime_ms = (time.perf_counter() - t0) * 1000.0
    value = headline_value(sim.sim_kind,
                           result.metrics if result is not None else {})
    if result is not None and value is not None:
        _record_and_autotrain(manager, sim.sim_kind, features, value)
        notes = list(result.notes or [])
        notes.append(f"échantillon surrogate n+1 enregistré (solveur {runtime_ms:.1f} ms)")
        result.notes = notes
    return result, False
