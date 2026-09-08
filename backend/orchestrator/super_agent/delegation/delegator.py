"""Delegator — exécution d'une délégation par l'agent spécialisé approprié."""
from __future__ import annotations

import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError
from typing import Any, Dict, Optional

from orchestrator.common import publish_event
from shared.contracts import AgentRole, Delegation
from shared.events import EventTypes, make_event
from shared.schemas import AgentResultSchema
from shared.schemas.agent_schemas import AgentStatus
from shared.utilities import get_logger

log = get_logger("super_agent.delegator")


class Delegator:
    """Dispatch d'une Delegation vers le bon agent, avec capability + timeout."""

    def __init__(self, timeout_s: float = 120.0) -> None:
        self.timeout_s = float(timeout_s)

    # ------------------------------------------------------------ synchrone
    def dispatch(self, delegation: Delegation,
                 agents: Dict[AgentRole, Any]) -> AgentResultSchema:
        """Trouve l'agent, vérifie la capabilité, exécute avec timeout."""
        agent = agents.get(delegation.role)
        if agent is None:
            return self._failure(delegation, f"agent introuvable pour le rôle {delegation.role.value}")
        supports = getattr(agent, "supports", None)
        if callable(supports) and not supports(delegation.objective):
            return self._failure(delegation,
                                 f"{getattr(agent, 'name', agent)} ne supporte pas: {delegation.objective}")

        context = dict(delegation.context or {})
        context.setdefault("action", delegation.objective.split(":")[0][:40])
        context.setdefault("objective", delegation.objective)
        context.setdefault("max_iterations", delegation.max_iterations)

        correlation_id = str(context.get("correlation_id") or "")
        self._publish(EventTypes.AGENT_TASK_ASSIGNED, {
            "delegation_id": delegation.delegation_id,
            "role": delegation.role.value,
            "objective": delegation.objective,
        }, context, correlation_id)

        started = time.time()
        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix=f"del-{delegation.role.value}")
        try:
            future = executor.submit(agent.execute, context)
            result = future.result(timeout=self.timeout_s)
        except FuturesTimeoutError:
            result = self._failure(delegation, f"timeout après {self.timeout_s:.0f}s")
        except Exception as exc:
            result = self._failure(delegation, f"exception: {exc}")
        finally:
            executor.shutdown(wait=False)

        duration_ms = round((time.time() - started) * 1000, 1)
        status = result.status.value if result is not None else "failed"
        self._publish(EventTypes.AGENT_TASK_COMPLETED, {
            "delegation_id": delegation.delegation_id,
            "role": delegation.role.value,
            "status": status,
            "confidence": float(result.confidence) if result is not None else 0.0,
            "duration_ms": duration_ms,
        }, context, correlation_id)
        log.info("délégation %s → %s [%s] %.0fms",
                 delegation.delegation_id, delegation.role.value, status, duration_ms)
        return result if result is not None else self._failure(delegation, "aucun résultat")

    # -------------------------------------------------------------- asynchrone
    async def dispatch_async(self, delegation: Delegation,
                             agents: Dict[AgentRole, Any]) -> AgentResultSchema:
        """Version asyncio (attendue par les intégrations API/WebSocket)."""
        return await asyncio.wait_for(
            asyncio.to_thread(self.dispatch, delegation, agents),
            timeout=self.timeout_s + 5.0,
        )

    # -------------------------------------------------------------- internals
    def _failure(self, delegation: Delegation, reason: str) -> AgentResultSchema:
        log.warning("délégation %s échouée: %s", delegation.delegation_id, reason)
        return AgentResultSchema(task_id=delegation.delegation_id,
                                 role=delegation.role.value,
                                 status=AgentStatus.FAILED,
                                 output={}, confidence=0.0, rationale=reason)

    def _publish(self, event_type: str, payload: Dict[str, Any],
                 context: Dict[str, Any], correlation_id: str) -> None:
        publish_event(make_event(
            event_type, payload,
            project_id=str(context.get("project_id") or ""),
            tenant_id=str(context.get("tenant_id") or "default"),
            source="super_agent.delegator",
            correlation_id=correlation_id,
        ))
