"""État persistant des projets — state.json par projet.

Chemin : data/projects/{tenant}/{user}/{project}/state.json
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from orchestrator.common import data_root
from shared.utilities import get_logger, new_id

log = get_logger("state.project")


@dataclass
class ProjectState:
    """État métadonné d'un projet (arborescence data/projects)."""

    project_id: str
    tenant_id: str = "default"
    user_id: str = "default"
    name: str = "untitled"
    created_ts: float = field(default_factory=time.time)
    last_rev: int = 0
    status: str = "active"

    # -- chemins ------------------------------------------------------------
    @property
    def dir(self) -> Path:
        return data_root() / self.tenant_id / self.user_id / self.project_id

    @property
    def path(self) -> Path:
        return self.dir / "state.json"

    # -- persistance ---------------------------------------------------------
    def save(self) -> "ProjectState":
        self.dir.mkdir(parents=True, exist_ok=True)
        for sub in ("design", "jobs", "exports", "simulations", "checkpoints"):
            (self.dir / sub).mkdir(exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
        os.replace(tmp, self.path)
        return self

    @classmethod
    def load(cls, project_id: str, tenant_id: str = "default",
             user_id: str = "default") -> Optional["ProjectState"]:
        path = data_root() / tenant_id / user_id / project_id / "state.json"
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return cls(
                project_id=data.get("project_id", project_id),
                tenant_id=data.get("tenant_id", tenant_id),
                user_id=data.get("user_id", user_id),
                name=data.get("name", "untitled"),
                created_ts=float(data.get("created_ts", time.time())),
                last_rev=int(data.get("last_rev", 0)),
                status=data.get("status", "active"),
            )
        except Exception:
            log.warning("state.json illisible: %s", path, exc_info=True)
            return None

    @classmethod
    def create(cls, name: str, tenant_id: str = "default", user_id: str = "default",
               project_id: Optional[str] = None) -> "ProjectState":
        state = cls(
            project_id=project_id or new_id("proj"),
            tenant_id=tenant_id or "default",
            user_id=user_id or "default",
            name=name or "untitled",
        )
        state.save()
        log.info("projet créé: %s (%s/%s)", state.project_id, state.tenant_id, state.name)
        return state

    @classmethod
    def delete(cls, project_id: str, tenant_id: str = "default",
               user_id: str = "default") -> bool:
        import shutil

        directory = data_root() / tenant_id / user_id / project_id
        if directory.exists():
            shutil.rmtree(directory, ignore_errors=True)
            return True
        return False

    @classmethod
    def list_projects(cls, tenant_id: str = "default") -> List["ProjectState"]:
        """Liste les projets d'un tenant (tous users confondus)."""
        base = data_root() / tenant_id
        projects: List[ProjectState] = []
        if not base.is_dir():
            return projects
        for user_dir in sorted(base.iterdir()):
            if not user_dir.is_dir():
                continue
            for project_dir in sorted(user_dir.iterdir()):
                state_file = project_dir / "state.json"
                if not state_file.is_file():
                    continue
                try:
                    data = json.loads(state_file.read_text(encoding="utf-8"))
                    projects.append(cls(
                        project_id=data.get("project_id", project_dir.name),
                        tenant_id=data.get("tenant_id", tenant_id),
                        user_id=data.get("user_id", user_dir.name),
                        name=data.get("name", project_dir.name),
                        created_ts=float(data.get("created_ts", 0.0)),
                        last_rev=int(data.get("last_rev", 0)),
                        status=data.get("status", "active"),
                    ))
                except Exception:
                    continue
        projects.sort(key=lambda p: p.created_ts)
        return projects

    # -- helpers ---------------------------------------------------------
    def to_dict(self) -> Dict[str, object]:
        return asdict(self)
