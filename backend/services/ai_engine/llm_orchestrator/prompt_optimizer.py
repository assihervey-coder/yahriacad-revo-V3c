"""Optimiseur de prompts — A/B variants + Thompson sampling, persistance JSON."""
from __future__ import annotations

import json
import os
import random
from collections import defaultdict
from typing import Dict, List, Tuple

from shared.utilities import get_logger

log = get_logger("ai_engine.llm.prompt_optimizer")


class PromptOptimizer:
    """Sélection de la meilleure variante de prompt par tâche (bandit manche).

    - `variants(task)` : 2 variantes A/B prédéfinies par type de tâche ;
    - `record(task, variant, score)` : accumule les scores observés ;
    - `best(task)` : Thompson sampling simple sur le score moyen
      (échantillon normal ~ N(mean, sigma/sqrt(n)) par variante).
    """

    def __init__(self, persist_path: str | None = None) -> None:
        self._scores: Dict[str, Dict[str, List[float]]] = defaultdict(
            lambda: defaultdict(list)
        )
        self.persist_path = persist_path or os.getenv("PROMPT_OPTIMIZER_PATH", "")
        if self.persist_path and os.path.exists(self.persist_path):
            self._load()

    # ------------------------------------------------------------- variants
    _TEMPLATE_VARIANTS: Dict[str, Tuple[str, str]] = {
        "placement": (
            "Optimise le placement en minimisant la longueur totale des fils. "
            "Suggère des déplacements précis (dx, dy) par composant.",
            "Pense comme un ingénieur layout senior : groupes fonctionnels, "
            "découplage proche des VDD, séparation analogique/numérique. "
            "Propose des déplacements par composant.",
        ),
        "intent": (
            "Extrais les paramètres du besoin (JSON strict): type, couches, "
            "dimensions, contraintes.",
            "Analyse la demande pas à pas puis renvoie un JSON strict avec : "
            "type, couches, dimensions, contraintes, objectifs.",
        ),
        "correction": (
            "Corrige chaque violation par le correctif minimal sûr, liste JSON.",
            "Pour chaque violation, propose un correctif minimal, réversible "
            "et justifié (JSON).",
        ),
        "default": (
            "Réponds de façon concise et technique.",
            "Raisonne étape par étape puis conclut de façon concise.",
        ),
    }

    def variants(self, task: str) -> List[str]:
        """Retourne les 2 variantes A/B pour une tâche donnée."""
        key = task if task in self._TEMPLATE_VARIANTS else "default"
        a, b = self._TEMPLATE_VARIANTS[key]
        return [a, b]

    # --------------------------------------------------------------- record
    def record(self, task: str, variant: str, score: float) -> None:
        """Enregistre le score (0..1 conseillé) obtenu par une variante."""
        self._scores[task][variant].append(float(score))
        if self.persist_path:
            try:
                self._save()
            except OSError as exc:
                log.warning("persistance prompt_optimizer impossible: %s", exc)

    def best(self, task: str) -> str:
        """Choisit la variante (Thompson sampling) — déterministe si peu de data."""
        a, b = self._TEMPLATE_VARIANTS[task if task in self._TEMPLATE_VARIANTS
                                       else "default"]
        names = [a, b]
        samples: List[float] = []
        for name in names:
            scores = self._scores[task].get(name, [])
            if not scores:
                samples.append(random.uniform(0.45, 0.55))  # exploration neutre
                continue
            mean = sum(scores) / len(scores)
            var = (sum((s - mean) ** 2 for s in scores) / len(scores)) if len(scores) > 1 else 0.01
            std = (max(var, 1e-6) / len(scores)) ** 0.5
            samples.append(random.gauss(mean, std))
        best_idx = max(range(len(names)), key=lambda i: samples[i])
        return names[best_idx]

    def stats(self, task: str) -> Dict[str, Dict[str, float]]:
        """Statistiques moyennes par variante (observabilité)."""
        out: Dict[str, Dict[str, float]] = {}
        for name, scores in self._scores.get(task, {}).items():
            if scores:
                out[name] = {"mean": sum(scores) / len(scores), "n": float(len(scores))}
        return out

    # --------------------------------------------------------- persistance
    def _save(self) -> None:
        os.makedirs(os.path.dirname(self.persist_path) or ".", exist_ok=True)
        with open(self.persist_path, "w", encoding="utf-8") as f:
            json.dump({t: dict(v) for t, v in self._scores.items()}, f, ensure_ascii=False)

    def _load(self) -> None:
        try:
            with open(self.persist_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for task, variants in data.items():
                for name, scores in variants.items():
                    self._scores[task][name] = [float(s) for s in scores]
        except (OSError, ValueError) as exc:
            log.warning("chargement prompt_optimizer échoué: %s", exc)
