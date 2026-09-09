"""Dataset persistant pour les surrogates — collecte (features, valeur) en JSONL.

Chaque ligne : {"features": {...}, "value": float, "meta": {...}, "ts": iso}.
Chemin : {DATA_ROOT}/datasets/surrogates/{kind}.jsonl — DATA_ROOT surchargeable
par la variable d'environnement PCB3_DATA_DIR.
"""
from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from typing import Any

from shared.utilities import get_logger

log = get_logger("simulator.surrogate.dataset")


def _root() -> str:
    base = os.environ.get("PCB3_DATA_DIR", "data")
    return os.path.join(base, "datasets", "surrogates")


class SurrogateDataset:
    """Collecte et relecture des échantillons (features → valeur de simu)."""

    def __init__(self, kind: str, root: str | None = None) -> None:
        self.kind = str(kind)
        self.root = root or _root()

    @property
    def path(self) -> str:
        return os.path.join(self.root, f"{self.kind}.jsonl")

    # ----------------------------------------------------------------- écriture
    def append(self, features: dict[str, float], value: float,
               meta: dict[str, Any] | None = None) -> None:
        """Ajoute un échantillon (crée le dossier si besoin)."""
        os.makedirs(self.root, exist_ok=True)
        row = {
            "features": {k: float(v) for k, v in features.items()},
            "value": float(value),
            "meta": meta or {},
            "ts": datetime.now(UTC).isoformat(timespec="seconds"),
        }
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    # ------------------------------------------------------------------ lecture
    def load(self) -> tuple[list[dict[str, float]], list[float]]:
        """(features[], values[]) — lignes corrompues ignorées avec warning."""
        features: list[dict[str, float]] = []
        values: list[float] = []
        if not os.path.exists(self.path):
            return features, values
        with open(self.path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                    features.append({k: float(v) for k, v in row["features"].items()})
                    values.append(float(row["value"]))
                except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                    log.warning("%s : ligne ignorée (corrompue)", self.path)
        return features, values

    def __len__(self) -> int:
        f, _ = self.load()
        return len(f)

    def clear(self) -> None:
        """Supprime le fichier d'échantillons du kind."""
        if os.path.exists(self.path):
            os.remove(self.path)
