"""Journal de rollback — révisions valides / invalides, dernière bonne version.

Alimente le mécanisme de reprise du workflow engine :
  mark_valid(rev) après une étape vérifiée, mark_invalid(rev, reason) sur échec,
  last_valid() pour restaurer (versioning.restore).
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from shared.utilities import get_logger

from orchestrator.common import data_root

log = get_logger("state.rollback")


class RollbackState:
    """Suivi des révisions valides/invalides + journal des rollbacks."""

    def __init__(self, path: str | None = None) -> None:
        self.path = Path(path) if path else data_root() / "rollback_state.json"
        self._valid: list[int] = []
        self._invalid: list[dict[str, Any]] = []
        self._load()

    # -- persistance ----------------------------------------------------------
    def _load(self) -> None:
        if not self.path.is_file():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self._valid = [int(r) for r in data.get("valid", [])]
            self._invalid = list(data.get("invalid", []))
        except Exception:
            log.warning("rollback_state.json illisible — départ à vide", exc_info=True)

    def _persist(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps({
                "valid": sorted(set(self._valid)),
                "invalid": self._invalid[-200:],
            }, indent=2), encoding="utf-8")
        except Exception:
            log.debug("persistance rollback_state impossible", exc_info=True)

    # -- opérations ------------------------------------------------------------
    def mark_valid(self, rev: int | None) -> None:
        """Déclare une révision comme point de restauration sûr."""
        if rev is None:
            return
        if rev not in self._valid:
            self._valid.append(int(rev))
        self._persist()

    def mark_invalid(self, rev: int | None, reason: str = "") -> None:
        """Déclare une révision défaillante (la retire des valides)."""
        if rev is None:
            return
        rev = int(rev)
        if rev in self._valid:
            self._valid.remove(rev)
        self._invalid.append({"rev": rev, "reason": reason, "ts": time.time()})
        self._persist()

    def last_valid(self) -> int | None:
        """Dernière révision valide connue (None si aucune)."""
        return max(self._valid) if self._valid else None

    def rollback_log(self) -> list[dict[str, Any]]:
        """Historique des invalidations (audit)."""
        return list(self._invalid)

    def valid_revisions(self) -> list[int]:
        return sorted(self._valid)
