"""CheckpointManager — sauvegarde versionnée avec rétention (5 derniers)."""
from __future__ import annotations

import json
import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple

from shared.utilities import get_logger, short_id

log = get_logger("ai_engine.training.checkpoints")

_RETENTION = 5
_META_SUFFIX = ".meta.json"


class CheckpointManager:
    """Gère les checkpoints d'entraînement dans un répertoire dédié.

    Chaque checkpoint = <name>_<step>.json (+ meta). Rétention : garde les
    `retention` plus récents par step.
    """

    def __init__(self, directory: str = "data/trained_models/policies",
                 retention: int = _RETENTION) -> None:
        self.directory = directory
        self.retention = max(1, retention)
        os.makedirs(self.directory, exist_ok=True)

    # ----------------------------------------------------------------- save
    def save(self, name: str, obj_dict: Dict[str, Any], step: int) -> str:
        """Sauvegarde un checkpoint (JSON) avec meta (step, ts)."""
        fname = f"{name}_{int(step)}.json"
        path = os.path.join(self.directory, fname)
        payload = {"name": name, "step": int(step), "obj": obj_dict,
                   "ts": time.time()}
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, default=str)
        with open(path + _META_SUFFIX, "w", encoding="utf-8") as f:
            json.dump({"name": name, "step": int(step), "ts": payload["ts"]},
                      f, ensure_ascii=False)
        self._apply_retention(name)
        log.debug("checkpoint sauvegardé: %s", path)
        return path

    # ----------------------------------------------------------------- list
    def list(self, name: Optional[str] = None) -> List[Dict[str, Any]]:
        """Liste les checkpoints [{name, step, path}] triés par step."""
        out: List[Dict[str, Any]] = []
        if not os.path.isdir(self.directory):
            return out
        for fname in sorted(os.listdir(self.directory)):
            if not fname.endswith(".json") or fname.endswith(_META_SUFFIX):
                continue
            m = re.match(r"^(.*)_(\d+)\.json$", fname)
            if not m:
                continue
            if name is not None and m.group(1) != name:
                continue
            out.append({
                "name": m.group(1), "step": int(m.group(2)),
                "path": os.path.join(self.directory, fname),
            })
        return sorted(out, key=lambda c: c["step"])

    # ----------------------------------------------------------------- load
    def load_latest(self, name: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Charge le checkpoint le plus récent (par step) — None si vide."""
        entries = self.list(name)
        if not entries:
            return None
        latest = entries[-1]
        try:
            with open(latest["path"], "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError) as exc:
            log.warning("chargement checkpoint échoué: %s", exc)
            return None

    # ------------------------------------------------------------ retention
    def _apply_retention(self, name: str) -> None:
        """Ne garde que les `retention` checkpoints les plus récents."""
        entries = self.list(name)
        if len(entries) <= self.retention:
            return
        for entry in entries[:-self.retention]:
            try:
                os.remove(entry["path"])
                meta = entry["path"] + _META_SUFFIX
                if os.path.exists(meta):
                    os.remove(meta)
            except OSError as exc:
                log.warning("suppression checkpoint échouée: %s", exc)
        log.debug("rétention appliquée à %s (%d gardés)", name, self.retention)
