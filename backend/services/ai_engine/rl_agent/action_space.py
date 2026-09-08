"""Action space discrétisé pour le placement et le routage."""
from __future__ import annotations

import math
import random
from dataclasses import dataclass
from enum import Enum
from typing import List, Tuple


class PlacementActionKind(Enum):
    """Types d'actions de placement."""

    MOVE = "move"
    ROTATE = "rotate"
    SWAP = "swap"
    NOP = "nop"


class RoutingActionKind(Enum):
    """Types d'actions de routage."""

    EXTEND = "extend"
    TURN = "turn"
    VIA = "via"
    RIPUP = "ripup"
    NOP = "nop"


@dataclass
class PlacementAction:
    """Action de placement sur un composant `ref`."""

    kind: PlacementActionKind
    ref: str = ""
    dx: float = 0.0
    dy: float = 0.0
    rot_delta: int = 0        # degrés (0/90/180/270)

    def to_dict(self) -> dict:
        return {"kind": self.kind.value, "ref": self.ref, "dx": self.dx,
                "dy": self.dy, "rot_delta": self.rot_delta}


@dataclass
class RouteAction:
    """Action de routage sur un net."""

    kind: RoutingActionKind
    net_id: str = ""
    dx: float = 0.0
    dy: float = 0.0
    layer_delta: int = 0

    def to_dict(self) -> dict:
        return {"kind": self.kind.value, "net_id": self.net_id,
                "dx": self.dx, "dy": self.dy, "layer_delta": self.layer_delta}


class ActionSpace:
    """Espace d'actions discrétisé (placement prioritairement).

    `place()` génère : MOVE(dx,dy) pour dx,dy ∈ {-2..2} pas 0.5, ROTATE(90..270),
    SWAP symbolique (vers le prochain ref) et NOP. `encode`/`decode` mappe
    bijectivement vers des indices entiers pour le policy network.
    """

    MOVE_STEPS: Tuple[float, ...] = (-2.0, -1.5, -1.0, -0.5, 0.0,
                                     0.5, 1.0, 1.5, 2.0)
    ROTATIONS: Tuple[int, ...] = (0, 90, 180, 270)

    def __init__(self, refs: List[str] | None = None) -> None:
        self.refs: List[str] = refs or ["U1"]
        self._actions: List[PlacementAction] = []
        self._rebuild()

    # -------------------------------------------------------------- builders
    def _rebuild(self) -> None:
        """Reconstruit la table d'actions pour les refs courants."""
        acts: List[PlacementAction] = []
        for ref in self.refs:
            for dx in self.MOVE_STEPS:
                for dy in self.MOVE_STEPS:
                    if dx == 0.0 and dy == 0.0:
                        continue
                    acts.append(PlacementAction(PlacementActionKind.MOVE,
                                                ref=ref, dx=dx, dy=dy))
            for rot in self.ROTATIONS:
                if rot:
                    acts.append(PlacementAction(PlacementActionKind.ROTATE,
                                                ref=ref, rot_delta=rot))
            acts.append(PlacementAction(PlacementActionKind.SWAP, ref=ref))
        acts.append(PlacementAction(PlacementActionKind.NOP))
        self._actions = acts

    def place(self, max_grid: int = 40) -> "ActionSpace":
        """Espace complet de placement (borné par max_grid refs)."""
        self.refs = self.refs[:max(1, min(max_grid, len(self.refs)))]
        self._rebuild()
        return self

    def set_refs(self, refs: List[str]) -> "ActionSpace":
        """Reparamètre l'espace sur de nouveaux refs."""
        self.refs = list(refs) or ["U1"]
        self._rebuild()
        return self

    # ------------------------------------------------------------- accessors
    def size(self) -> int:
        """Nombre d'actions discrètes."""
        return len(self._actions)

    @property
    def n(self) -> int:
        return len(self._actions)

    def all_actions(self) -> List[PlacementAction]:
        return list(self._actions)

    def sample(self) -> PlacementAction:
        """Action uniforme aléatoire."""
        return random.choice(self._actions)

    # ------------------------------------------------------------- encoding
    def encode(self, action: PlacementAction) -> int:
        """Index entier d'une action (approx. par égalité de contenu)."""
        for i, a in enumerate(self._actions):
            if (a.kind == action.kind and a.ref == action.ref
                    and math.isclose(a.dx, action.dx)
                    and math.isclose(a.dy, action.dy)
                    and a.rot_delta == action.rot_delta):
                return i
        return len(self._actions) - 1  # fallback NOP

    def decode(self, idx: int) -> PlacementAction:
        """Action depuis un index (clampé)."""
        idx = max(0, min(idx, len(self._actions) - 1))
        return self._actions[idx]
