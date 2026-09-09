"""Restauration de session — persistance atomique JSON des projets.

Chemin : {base_dir}/{tenant_id}/{user_id}/{project_id}/session.json
Contenu : graphe sérialisé (design_core.to_dict) + état du versioning.
"""
from __future__ import annotations

import contextlib
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

from shared.utilities import get_logger, new_id

from services.pcb_plugin._compat import (
    graph_from_dict,
    graph_to_dict,
    versioning_from_dict,
    versioning_to_dict,
)

log = get_logger(__name__)


class SessionRestorer:
    """Sauvegarde/restaure les sessions design (JSON atomique tmp→rename)."""

    def __init__(self, base_dir: str = "data/projects") -> None:
        self.base_dir = Path(base_dir)

    # -- chemins ---------------------------------------------------------------
    def _session_dir(self, tenant_id: str, user_id: str, project_id: str) -> Path:
        return self.base_dir / tenant_id / user_id / project_id

    def _session_file(self, tenant_id: str, user_id: str, project_id: str) -> Path:
        return self._session_dir(tenant_id, user_id, project_id) / "session.json"

    # -- écriture ---------------------------------------------------------------
    def save_session(self, tenant_id: str, user_id: str, project_id: str,
                     graph: Any, versioning: Any = None) -> Path:
        """Écrit la session en JSON de façon atomique (tmp puis os.replace)."""
        session_dir = self._session_dir(tenant_id, user_id, project_id)
        payload = {
            "session_id": new_id("sess"),
            "tenant_id": tenant_id,
            "user_id": user_id,
            "project_id": project_id,
            "saved_at": time.time(),
            "graph": graph_to_dict(graph),
            "versioning": self._versioning_meta(versioning, session_dir),
        }
        target = session_dir / "session.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=str(target.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, default=str)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_path, target)  # atomique sur le même filesystem
        except Exception:
            with contextlib.suppress(OSError):
                os.unlink(tmp_path)
            raise
        log.info("session sauvegardée: %s", target)
        return target

    @staticmethod
    def _versioning_meta(versioning: Any, session_dir: Path) -> dict[str, Any]:
        """Persiste le versioning (persist natif) ou le sérialise en dict."""
        if versioning is None:
            return {}
        persist = getattr(versioning, "persist", None)
        if callable(persist):
            try:
                persist(str(session_dir / "versions.json"))
                return {"kind": "persisted", "file": "versions.json"}
            except Exception as exc:
                log.warning("versioning.persist échoué (%s) — fallback dict", exc)
        return {"kind": "dict", "data": versioning_to_dict(versioning)}

    @staticmethod
    def _versioning_from_meta(meta: dict[str, Any], session_dir: Path) -> Any:
        """Restaure le versioning : DesignVersioning.load natif puis fallback dict."""
        if not isinstance(meta, dict) or not meta:
            return None
        if meta.get("kind") == "persisted" and meta.get("file"):
            vfile = session_dir / str(meta["file"])
            if vfile.exists():
                try:
                    from services.design_core import DesignVersioning  # lazy

                    return DesignVersioning.load(str(vfile))
                except Exception as exc:
                    log.warning("DesignVersioning.load échoué: %s", exc)
        return versioning_from_dict(meta.get("data") or {})

    # -- lecture ---------------------------------------------------------------
    def restore_session(self, tenant_id: str, user_id: str,
                        project_id: str) -> tuple[Any, Any] | None:
        """Charge (DesignGraph, DesignVersioning) ou None si absente/corrompue."""
        path = self._session_file(tenant_id, user_id, project_id)
        if not path.exists():
            log.info("session absente: %s", path)
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            graph = graph_from_dict(payload.get("graph") or {})
            versioning = self._versioning_from_meta(
                payload.get("versioning") or {}, path.parent)
            log.info("session restaurée: %s", path)
            return graph, versioning
        except Exception as exc:
            log.error("session corrompue (%s): %s", path, exc)
            return None

    def list_sessions(self, tenant_id: str) -> list[dict[str, Any]]:
        """Liste les sessions d'un tenant [{user_id, project_id, saved_at, path}]."""
        out: list[dict[str, Any]] = []
        tenant_dir = self.base_dir / tenant_id
        if not tenant_dir.is_dir():
            return out
        for session_file in sorted(tenant_dir.glob("*/*/session.json")):
            meta = {"user_id": session_file.parent.parent.name,
                    "project_id": session_file.parent.name,
                    "path": str(session_file), "saved_at": 0.0}
            try:
                payload = json.loads(session_file.read_text(encoding="utf-8"))
                meta["saved_at"] = float(payload.get("saved_at", 0.0))
                meta["name"] = str(payload.get("graph", {}).get("name", ""))
            except Exception:
                pass
            out.append(meta)
        return out
