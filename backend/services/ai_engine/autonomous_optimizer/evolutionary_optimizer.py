"""EvolutionaryOptimizer — sélection / crossover / mutation sur positions."""
from __future__ import annotations

import random
from collections.abc import Callable

from shared.utilities import get_logger

log = get_logger("ai_engine.opt.evolutionary")

EvalFn = Callable[[object], float]


class EvolutionaryOptimizer:
    """Algorithme évolutionnaire sur les positions des composants.

    - population de DesignGraph (copies mutées du seed) ;
    - step(evaluate_fn) : évalue, sélectionne les élites, crossover 'mean'
      ou 'uniform', mutation gaussienne (mutation_mm), retourne le meilleur.
    """

    def __init__(self, pop_size: int = 8, elite: int = 2,
                 mutation_mm: float = 2.0, crossover: str = "mean",
                 seed: int = 0) -> None:
        self.pop_size = max(2, pop_size)
        self.elite = max(1, min(elite, self.pop_size - 1))
        self.mutation_mm = mutation_mm
        self.crossover = crossover if crossover in ("mean", "uniform") else "mean"
        self.rng = random.Random(seed)
        self.population: list[object] = []
        self._scores: list[float] = []
        self.generation = 0

    # ------------------------------------------------------------------ seed
    def seed(self, graph) -> list[object]:  # noqa: ANN001
        """Initialise la population : copies du graphe avec mutations."""
        self.population = [graph.copy()]
        for _ in range(self.pop_size - 1):
            child = graph.copy()
            self._mutate(child, strength=self.mutation_mm * 2)
            self.population.append(child)
        self._scores = [float("-inf")] * self.pop_size
        self.generation = 0
        log.info("population seedée: %d individus", self.pop_size)
        return self.population

    # ------------------------------------------------------------------ step
    def step(self, evaluate_fn: EvalFn) -> tuple[object, float]:
        """Une génération : évaluation → sélection → crossover → mutation."""
        if not self.population:
            raise RuntimeError("EvolutionaryOptimizer: appelez seed() d'abord")

        self._scores = [float(evaluate_fn(ind)) for ind in self.population]
        ranked = sorted(range(self.pop_size), key=lambda i: self._scores[i],
                        reverse=True)
        elites = [self.population[i] for i in ranked[:self.elite]]

        next_pop: list[object] = [e.copy() for e in elites]
        while len(next_pop) < self.pop_size:
            parent_a = self._tournament()
            parent_b = self._tournament()
            child = self._crossover(parent_a, parent_b)
            self._mutate(child, strength=self.mutation_mm)
            next_pop.append(child)

        self.population = next_pop
        self.generation += 1
        best_idx = ranked[0]
        best_score = self._scores[best_idx]
        log.debug("gen %d: best=%.4f mean=%.4f",
                  self.generation, best_score, sum(self._scores) / len(self._scores))
        return elites[0], best_score

    # ------------------------------------------------------------- operators
    def _positions(self, graph) -> dict[str, tuple[float, float]]:  # noqa: ANN001
        return {ref: (c.x, c.y) for ref, c in graph.components.items()}

    def _set_positions(self, graph, positions: dict[str, tuple[float, float]]) -> None:  # noqa: ANN001
        for ref, (x, y) in positions.items():
            if ref in graph.components:
                graph.place(ref, x, y)

    def _crossover(self, a, b) -> object:  # noqa: ANN001
        child = a.copy()
        pa, pb = self._positions(a), self._positions(b)
        if self.crossover == "mean":
            merged = {ref: ((pa[ref][0] + pb[ref][0]) / 2.0,
                            (pa[ref][1] + pb[ref][1]) / 2.0)
                      for ref in pa if ref in pb}
        else:  # uniform
            merged = {ref: (self.rng.choice([pa[ref], pb[ref]]))
                      for ref in pa if ref in pb}
        self._set_positions(child, merged)
        return child

    def _mutate(self, graph, strength: float) -> None:  # noqa: ANN001
        refs = list(graph.components.keys())
        if not refs:
            return
        ref = self.rng.choice(refs)
        comp = graph.components[ref]
        dx = self.rng.gauss(0.0, strength)
        dy = self.rng.gauss(0.0, strength)
        graph.place(ref, comp.x + dx, comp.y + dy)

    def _tournament(self, k: int = 3) -> object:  # noqa: ANN001
        idxs = self.rng.sample(range(self.pop_size), min(k, self.pop_size))
        best = max(idxs, key=lambda i: self._scores[i])
        return self.population[best]

    # -------------------------------------------------------------- best
    def best(self, evaluate_fn: EvalFn | None = None
             ) -> tuple[object, float]:
        """Meilleur individu courant (ré-évalue si evaluate_fn fourni)."""
        if evaluate_fn is not None:
            self._scores = [float(evaluate_fn(ind)) for ind in self.population]
        i = max(range(len(self.population)),
                key=lambda j: self._scores[j] if j < len(self._scores) else -1e18)
        return self.population[i], (self._scores[i] if i < len(self._scores)
                                    else float("-inf"))
