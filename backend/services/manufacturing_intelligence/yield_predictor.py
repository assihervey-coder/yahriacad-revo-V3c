"""Prédiction de rendement de fabrication — heuristique + modèle sklearn (lazy)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, List, Optional

from shared.utilities import get_logger

from services.manufacturing_intelligence.factory_profiles import FactoryProfile

log = get_logger(__name__)

_MODEL_PATH = os.path.join("data", "trained_models", "yield_model.joblib")
_model_cache: Optional[Any] = None


@dataclass
class YieldPrediction:
    """Rendement attendu (0..1) et facteurs de risque identifiés."""

    expected_yield: float
    risk_factors: List[str] = field(default_factory=list)
    model: str = "heuristic"  # heuristic | sklearn


class YieldPredictor:
    """Prédit le rendement usine : heuristique par pénalités, modèle ML si dispo."""

    def predict(self, graph: Any, profile: FactoryProfile) -> YieldPrediction:
        """Rendement attendu pour ce design sur cette usine."""
        features = self._features(graph, profile)

        model = self._load_model()
        if model is not None:
            try:
                raw = float(model.predict([features])[0])
                return YieldPrediction(expected_yield=min(max(raw, 0.5), 0.999),
                                       risk_factors=[], model="sklearn")
            except Exception as exc:
                log.warning("modèle yield inutilisable (%s) — fallback heuristique", exc)

        risks: List[str] = []
        score = 0.99

        n_layers = len(list(getattr(graph, "layers", []) or [])) or 2
        if n_layers > profile.max_layers:
            score -= 0.30
            risks.append(f"{n_layers} couches > max usine ({profile.max_layers})")
        elif n_layers >= profile.max_layers - 2:
            score -= 0.02
            risks.append(f"stackup proche de la limite usine ({n_layers} couches)")

        # largeurs de trace trop fines pour l'usine
        narrow = 0
        for net in graph.nets.values():
            path = getattr(net, "path", None)
            if path is not None and path.points and \
                    float(getattr(path, "width_mm", 0.2)) < profile.min_trace_mm:
                narrow += 1
        if narrow:
            score -= min(0.15, 0.03 * narrow)
            risks.append(f"{narrow} net(s) sous la largeur min ({profile.min_trace_mm} mm)")

        # vias trop petits
        small_vias = 0
        for net in graph.nets.values():
            path = getattr(net, "path", None)
            for via in (getattr(path, "vias", []) or []) if path is not None else []:
                # taille via par défaut 0.6 / drill 0.3 (constantes exporter)
                if 0.6 - 0.3 < 2 * profile.min_annular_ring_mm or 0.3 < profile.min_hole_mm:
                    small_vias += 1
        if small_vias:
            score -= min(0.10, 0.01 * small_vias)
            risks.append(f"{small_vias} via(s) sous l'anneau min "
                         f"({profile.min_annular_ring_mm} mm)")

        # densité d'occupation
        try:
            w, h = graph.board_size
            board_area = float(w) * float(h)
        except Exception:
            board_area = 0.0
        used_area = sum(float(getattr(c, "bbox", (0, 0))[0]) *
                        float(getattr(c, "bbox", (0, 0))[1])
                        for c in graph.components.values())
        density = used_area / board_area if board_area else 0.0
        if density > 0.7:
            score -= 0.05 * min(1.0, (density - 0.7) / 0.2)
            risks.append(f"densité {100 * density:.0f}% > 70%")

        if len(graph.components) > 300:
            score -= 0.02
            risks.append(f"{len(graph.components)} composants (assemblage dense)")

        yield_ = round(min(max(score, 0.5), 0.999), 4)
        if not risks:
            risks.append("aucun risque DFM majeur détecté")
        return YieldPrediction(expected_yield=yield_, risk_factors=risks)

    # -- internes ---------------------------------------------------------------
    @staticmethod
    def _features(graph: Any, profile: FactoryProfile) -> List[float]:
        """Vecteur de features [densité, ratio_trace, couches, n_comp, n_vias, largeur_moy]."""
        try:
            w, h = graph.board_size
            board_area = float(w) * float(h)
        except Exception:
            board_area = 0.0
        used = sum(float(getattr(c, "bbox", (0, 0))[0]) * float(getattr(c, "bbox", (0, 0))[1])
                   for c in graph.components.values())
        widths = [float(getattr(getattr(n, "path", None), "width_mm", 0.2) or 0.2)
                  for n in graph.nets.values()
                  if getattr(n, "path", None) is not None and getattr(n.path, "points", [])]
        n_vias = sum(len(getattr(n.path, "vias", []) or [])
                     for n in graph.nets.values() if getattr(n, "path", None) is not None)
        avg_width = sum(widths) / len(widths) if widths else 0.2
        return [
            used / board_area if board_area else 0.0,
            min(widths) / profile.min_trace_mm if widths else 1.5,
            len(list(getattr(graph, "layers", []) or [])),
            len(graph.components),
            n_vias,
            avg_width,
        ]

    @staticmethod
    def _load_model() -> Optional[Any]:
        """Charge le modèle sklearn sauvé (lazy, jamais bloquant)."""
        global _model_cache
        if _model_cache is not None:
            return _model_cache or None
        if not os.path.exists(_MODEL_PATH):
            return None
        try:
            import joblib  # lazy

            _model_cache = joblib.load(_MODEL_PATH)
            log.info("modèle yield chargé: %s", _MODEL_PATH)
            return _model_cache
        except Exception as exc:
            log.warning("chargement modèle yield échoué: %s", exc)
            _model_cache = False  # évite de retenter à chaque appel
            return None
