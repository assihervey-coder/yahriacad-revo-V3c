"""Permissions MCP — scopes requis par outil/ressource.

En dev (JWT absent), l'identité anonyme porte ["*"] → tout est permis.
"""
from __future__ import annotations

from typing import Dict, List, Optional

TOOL_SCOPES: Dict[str, List[str]] = {
    "run_design_command": ["design:write"],
    "query_design": ["design:read"],
    "export_package": ["design:export"],
    "simulate": ["design:simulate"],
}

RESOURCE_SCOPES: Dict[str, List[str]] = {
    "design://": ["design:read"],
    "report://": ["design:read"],
    "export://": ["design:export"],
}


def tool_allowed(scopes: Optional[List[str]], tool: str) -> bool:
    """Vérifie que les scopes couvrent l'outil demandé."""
    scopes = scopes or []
    if "*" in scopes:
        return True
    required = TOOL_SCOPES.get(tool, ["design:read"])
    return any(scope in scopes for scope in required)


def resource_allowed(scopes: Optional[List[str]], uri: str) -> bool:
    """Vérifie que les scopes couvrent la ressource demandée."""
    scopes = scopes or []
    if "*" in scopes:
        return True
    for prefix, required in RESOURCE_SCOPES.items():
        if str(uri).startswith(prefix):
            return any(scope in scopes for scope in required)
    return False


def list_tools() -> List[Dict[str, str]]:
    """Outils exposés avec leurs scopes (pour tools/list)."""
    return [{"tool": tool, "required_scopes": ", ".join(required)}
            for tool, required in TOOL_SCOPES.items()]
