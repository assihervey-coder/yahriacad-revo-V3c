"""Checkpoints de workflow — snapshot (graph + SMM) après chaque étape.

Chemin : data/projects/checkpoints/{job_id}_{step}_{ts}.json
"""
from __future__ import annotations

import builtins
import json
import time
from pathlib import Path
from typing import Any

from shared.utilities import get_logger

from orchestrator.common import data_root

log = get_logger("state.checkpoints")


class CheckpointManager:
    """Instantanés de reprise : un checkpoint par étape de pipeline réussie."""

    def __init__(self, directory: str | None = None) -> None:
        self.dir = Path(directory) if directory else data_root() / "checkpoints"
        self.dir.mkdir(parents=True, exist_ok=True)

    # -- opérations ----------------------------------------------------------
    def checkpoint(self, job_id: str, step: str, graph_dict: dict[str, Any],
                   smm_snapshot: str = "") -> str:
        """Écrit un checkpoint et retourne son identifiant."""
        ts = time.time()
        checkpoint_id = f"{job_id}_{step}_{int(ts * 1000)}"
        payload = {
            "checkpoint_id": checkpoint_id,
            "job_id": job_id,
            "step": step,
            "ts": ts,
            "graph": graph_dict or {},
            "smm_snapshot": smm_snapshot or "",
        }
        path = self.dir / f"{checkpoint_id}.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        tmp.replace(path)
        log.debug("checkpoint %s", checkpoint_id)
        return checkpoint_id

    def _paths(self, job_id: str) -> builtins.list[Path]:
        return sorted(self.dir.glob(f"{job_id}_*.json"))

    def list(self, job_id: str) -> builtins.list[dict[str, Any]]:
        """Tous les checkpoints d'un job, du plus ancien au plus récent."""
        entries: list[dict[str, Any]] = []
        for path in self._paths(job_id):
            try:
                entries.append(json.loads(path.read_text(encoding="utf-8")))
            except Exception:
                continue
        entries.sort(key=lambda e: float(e.get("ts", 0.0)))
        return entries

    def latest(self, job_id: str) -> dict[str, Any] | None:
        """Dernier checkpoint du job (reprise après crash)."""
        entries = self.list(job_id)
        return entries[-1] if entries else None

    def prune(self, keep: int = 5) -> int:
        """Ne garde que les `keep` checkpoints les plus récents par job."""
        removed = 0
        by_job: dict[str, list[Path]] = {}
        for path in self.dir.glob("*.json"):
            job_id = path.name.split("_")[0]
            by_job.setdefault(job_id, []).append(path)
        for paths in by_job.values():
            paths.sort(key=lambda p: p.stat().st_mtime)
            for path in paths[:-keep] if keep > 0 else paths:
                try:
                    path.unlink()
                    removed += 1
                except OSError:
                    continue
        return removed
