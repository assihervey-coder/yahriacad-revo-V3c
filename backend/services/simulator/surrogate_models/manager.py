"""SurrogateManager — collecte → entraînement → inférence rapide (β).

Boucle de vie complète d'un surrogate :
  1. `record(kind, graph, value)`   : stocke (features du design, résultat de la
     simulation COMPLÈTE) dans un dataset JSONL persistant.
  2. `maybe_train(kind)`            : dès `min_samples`, entraîne un
     NeuralSurrogate avec split train/validation, early stopping léger et
     métriques (MAE, R²) — retourne les métriques ou None.
  3. `predict_fast(kind, graph)`    : inférence en ~µs au lieu du solveur
     complet (~s) — marque β (bêta) + latence mesurée.
  4. `benchmark(graph, solver)`     : chronomètre solveur complet vs surrogate
     → speedup réel, pour prouver la valeur en conditions reproductibles.

Les features sont extraites via FastPredictor.features (ordre stable).
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional

import numpy as np

from shared.utilities import get_logger

from services.simulator.surrogate_models.dataset import SurrogateDataset
from services.simulator.surrogate_models.neural_surrogates import NeuralSurrogate

log = get_logger("simulator.surrogate.manager")

# features canoniques du design (ordre stable) — source de vérité du package
FEATURE_NAMES = ("n_comp", "density", "power_sum", "wire_length")


@dataclass
class SurrogateStatus:
    """État d'un surrogate par kind."""

    kind: str
    n_samples: int = 0
    trained: bool = False
    val_mae: float | None = None
    r2: float | None = None
    last_latency_ms: float | None = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind,
            "n_samples": self.n_samples,
            "trained": self.trained,
            "val_mae": (round(self.val_mae, 4) if self.val_mae is not None else None),
            "r2": (round(self.r2, 4) if self.r2 is not None else None),
            "last_latency_ms": (round(self.last_latency_ms, 4)
                                if self.last_latency_ms is not None else None),
        }


@dataclass
class BenchmarkResult:
    """Résultat de comparaison solveur complet vs surrogate (β)."""

    kind: str
    full_value: float
    surrogate_value: float
    abs_error: float
    full_ms: float
    surrogate_ms: float
    speedup_x: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind,
            "full_value": round(self.full_value, 4),
            "surrogate_value": round(self.surrogate_value, 4),
            "abs_error": round(self.abs_error, 4),
            "full_ms": round(self.full_ms, 2),
            "surrogate_ms": round(self.surrogate_ms, 4),
            "speedup_x": round(self.speedup_x, 1),
        }


class SurrogateManager:
    """Gestionnaire des surrogates neuronaux (un par kind de simulation)."""

    def __init__(self, min_samples: int = 25, n_hidden: int = 24,
                 epochs: int = 300, lr: float = 3e-3,
                 data_root: str | None = None) -> None:
        self.min_samples = int(min_samples)
        self.n_hidden = int(n_hidden)
        self.epochs = int(epochs)
        self.lr = float(lr)
        self.surrogates: Dict[str, NeuralSurrogate] = {}
        self.status: Dict[str, SurrogateStatus] = {}
        self._datasets: Dict[str, SurrogateDataset] = {}
        self._roots = data_root
        self._lock = None  # threading introduit seulement si besoin (lectures atomiques)

    # ------------------------------------------------------------------ dataset
    def dataset(self, kind: str) -> SurrogateDataset:
        if kind not in self._datasets:
            self._datasets[kind] = SurrogateDataset(kind, root=self._roots)
        return self._datasets[kind]

    def record(self, kind: str, features: Dict[str, float], value: float,
               meta: Dict[str, Any] | None = None) -> int:
        """Enregistre un échantillon (features → valeur mesurée). Retourne n."""
        self.dataset(kind).append(features, value, meta=meta)
        n = len(self.dataset(kind))
        if kind in self.status:
            self.status[kind].n_samples = n
        log.debug("surrogate[%s] échantillon #%d : %.4f", kind, n, value)
        return n

    # -------------------------------------------------------------- entraînement
    def maybe_train(self, kind: str) -> Optional[SurrogateStatus]:
        """Entraîne si assez d'échantillons. Retourne le statut ou None."""
        ds = self.dataset(kind)
        feats, values = ds.load()
        n = len(values)
        if kind not in self.status:
            self.status[kind] = SurrogateStatus(kind=kind)
        self.status[kind].n_samples = n
        if n < max(self.min_samples, 8):
            log.info("surrogate[%s] : %d/%d échantillons — entraînement reporté",
                     kind, n, self.min_samples)
            return None
        # matrice ordonnée selon FEATURE_NAMES (features inconnues ignorées)
        X = np.array([[f.get(k, 0.0) for k in FEATURE_NAMES] for f in feats],
                     dtype=np.float64)
        y = np.array(values, dtype=np.float64)

        # split train/validation déterministe (toutes les 5 lignes → val)
        idx_all = np.arange(n)
        val_mask = (idx_all % 5 == 0) if n >= 10 else np.zeros(n, dtype=bool)
        train_mask = ~val_mask
        surrogate = NeuralSurrogate(name=f"surrogate_{kind}",
                                    n_inputs=len(FEATURE_NAMES),
                                    n_hidden=self.n_hidden)
        if train_mask.sum() >= 4:
            surrogate.fit(X[train_mask], y[train_mask],
                          epochs=self.epochs, lr=self.lr)
        else:                       # très petit jeu : tout servir à entraîner
            surrogate.fit(X, y, epochs=self.epochs, lr=self.lr)

        self.surrogates[kind] = surrogate
        st = self.status[kind]
        st.trained = True
        if val_mask.sum() >= 2:
            pred = surrogate.predict(X[val_mask])
            truth = y[val_mask]
            mae = float(np.mean(np.abs(pred - truth)))
            denom = float(np.sum((truth - truth.mean()) ** 2))
            st.val_mae = mae
            st.r2 = (1.0 - float(np.sum((pred - truth) ** 2)) / denom
                     if denom > 1e-12 else None)
            log.info("surrogate[%s] entraîné : n=%d, MAE val=%.4f, R²=%.3f",
                     kind, n, mae, st.r2 if st.r2 is not None else float("nan"))
        else:
            train_pred = surrogate.predict(X)
            st.val_mae = float(np.mean(np.abs(train_pred - y)))
            log.info("surrogate[%s] entraîné (sans val) : n=%d, MAE=%.4f",
                     kind, n, st.val_mae)
        return st

    def train_all(self) -> Dict[str, SurrogateStatus]:
        """Tente l'entraînement de tous les kinds ayant assez de données."""
        out: Dict[str, SurrogateStatus] = {}
        for kind in list(self._datasets) or ["thermal", "si", "pi", "emi"]:
            st = self.maybe_train(kind)
            if st is not None:
                out[kind] = st
        return out

    # ---------------------------------------------------------------- inférence
    def predict_fast(self, kind: str, x: Dict[str, float]) -> Dict[str, Any]:
        """Inférence rapide (β) : {"value", "beta", "latency_ms", "trained"}.

        Retourne trained=False si aucun surrogate dispo (l'appelant retombe
        sur l'analytique).
        """
        surrogate = self.surrogates.get(kind)
        if surrogate is None or not surrogate.trained:
            return {"value": None, "beta": True, "trained": False}
        vec = [float(x.get(k, 0.0)) for k in FEATURE_NAMES]
        t0 = time.perf_counter()
        value = float(surrogate.predict(np.array([vec]))[0])
        latency_ms = (time.perf_counter() - t0) * 1000.0
        if kind in self.status:
            self.status[kind].last_latency_ms = latency_ms
        if not math.isfinite(value):
            return {"value": None, "beta": True, "trained": False}
        return {"value": value, "beta": True, "trained": True,
                "latency_ms": latency_ms}

    # --------------------------------------------------------------- benchmark
    def benchmark(self, kind: str, x: Dict[str, float],
                  full_solver: Callable[[], float]) -> Optional[BenchmarkResult]:
        """Chronomètre solveur complet vs surrogate → speedup réel.

        Enregistre AUSSI l'échantillon (features, valeur du solveur complet)
        pour améliorer continuellement le surrogate.
        """
        t0 = time.perf_counter()
        full_value = float(full_solver())
        full_ms = (time.perf_counter() - t0) * 1000.0

        self.record(kind, x, full_value, meta={"source": "benchmark"})

        pred = self.predict_fast(kind, x)
        if not pred.get("trained"):
            return None
        surrogate_ms = float(pred["latency_ms"])
        surrogate_value = float(pred["value"])
        return BenchmarkResult(
            kind=kind,
            full_value=full_value,
            surrogate_value=surrogate_value,
            abs_error=abs(full_value - surrogate_value),
            full_ms=full_ms,
            surrogate_ms=surrogate_ms,
            speedup_x=(full_ms / surrogate_ms if surrogate_ms > 1e-9 else float("inf")),
        )

    # ------------------------------------------------------------------- divers
    def status_all(self) -> Dict[str, Dict[str, Any]]:
        """Statut complet pour l'API (dashboard β)."""
        out: Dict[str, Dict[str, Any]] = {}
        for kind in ("thermal", "si", "pi", "emi"):
            if kind in self.status:
                out[kind] = self.status[kind].to_dict()
            else:
                n = len(self.dataset(kind))
                out[kind] = SurrogateStatus(kind=kind, n_samples=n).to_dict()
        return out

    def save(self, directory: str) -> None:
        """Sauvegarde tous les surrogates entraînés dans un dossier."""
        import os
        os.makedirs(directory, exist_ok=True)
        for kind, surrogate in self.surrogates.items():
            if surrogate.trained:
                surrogate.save(os.path.join(directory, f"{kind}.npz"))

    def load(self, directory: str) -> int:
        """Charge les surrogates présents dans un dossier. Retourne le nombre."""
        import os
        if not os.path.isdir(directory):
            return 0
        loaded = 0
        for fname in os.listdir(directory):
            if not fname.endswith(".npz"):
                continue
            kind = fname[:-4]
            try:
                self.surrogates[kind] = NeuralSurrogate.load(
                    os.path.join(directory, fname))
                self.surrogates[kind].trained = True
                if kind not in self.status:
                    self.status[kind] = SurrogateStatus(kind=kind)
                self.status[kind].trained = True
                loaded += 1
            except (OSError, KeyError, ValueError) as exc:
                log.warning("surrogate %s non chargé : %s", fname, exc)
        return loaded
