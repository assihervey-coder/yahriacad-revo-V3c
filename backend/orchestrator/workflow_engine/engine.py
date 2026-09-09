"""WorkflowEngine — exécution séquentielle des pipelines d'agents.

Boucle par étape :
  1. AGENT_TASK_ASSIGNED → agent.execute(context)
  2. auto-vérification (agent.verify + SelfVerifier du cerveau IA)
  3. si échec : rollback vers la dernière révision valide (state_manager),
     retry jusqu'à Step.retry, puis ESCALATION_REQUESTED
  4. si succès : checkpoint (graph + SMM), AGENT_TASK_COMPLETED,
     persistance du design courant
"""
from __future__ import annotations

import time
from typing import Any

from shared.events import EventTypes, make_event
from shared.schemas.agent_schemas import AgentStatus
from shared.utilities import get_logger

from orchestrator.common import (
    deserialize_graph,
    ensure_smm,
    ensure_versioning,
    get_field,
    graph_stats,
    publish_event,
    serialize_graph,
    try_import,
)
from orchestrator.state_manager import (
    CheckpointManager,
    DesignStateManager,
    RollbackState,
    get_agent_state_store,
)
from orchestrator.workflow_engine.jobs import Job, JobStore, get_job_store
from orchestrator.workflow_engine.pipelines import Step, get_pipeline
from orchestrator.workflow_engine.tasks import TaskQueue, TaskSpec, get_task_queue

log = get_logger("workflow.engine")

# Étapes pour lesquelles l'échec du SelfVerifier déclenche rollback/retry.
# (pour les autres, l'agent lui-même fait autorité via agent.verify)
SELF_VERIFIED_STEPS = {"place", "route", "optimize", "verify_2"}


class WorkflowEngine:
    """Moteur d'orchestration des 10 agents sur les pipelines prédéfinis."""

    def __init__(self, agents: dict[Any, Any] | None = None,
                 job_store: JobStore | None = None,
                 task_queue: TaskQueue | None = None,
                 checkpoints_dir: str | None = None) -> None:
        if agents is None:
            from orchestrator.agent_pipeline import build_agents  # import lazy (cycle)

            agents = build_agents()
        self._agents = agents
        self.jobs = job_store or get_job_store()
        self.queue = task_queue or get_task_queue()
        self.checkpoints = CheckpointManager(directory=checkpoints_dir)
        self.rollback = RollbackState()
        self._design_state = DesignStateManager()
        self._agent_state = get_agent_state_store()
        self.log = get_logger("workflow.engine")

    # ------------------------------------------------------------ propriétés
    @property
    def agents(self) -> dict[Any, Any]:
        return self._agents

    # ------------------------------------------------------------ exécution
    def run_pipeline(self, task: TaskSpec) -> Job:
        """Exécute le pipeline d'une tâche (bloquant — appeler via un thread)."""
        started = time.time()
        self.queue.update_status(task.task_id, "running")
        job = self.jobs.create(task)
        job.status = "running"
        self.jobs.update(job)
        self._publish(EventTypes.JOB_STARTED, {
            "job_id": job.job_id, "task_id": task.task_id,
            "pipeline": task.pipeline_name, "project_id": task.project_id,
        }, task)
        self.log.info("job %s démarré — pipeline %s (tâche %s)",
                      job.job_id, task.pipeline_name, task.task_id)

        context = self._prepare_context(task, job)
        completed: list[str] = []
        try:
            pipeline = get_pipeline(task.pipeline_name)
        except ValueError as exc:
            job.status = "failed"
            job.state["error"] = str(exc)
            self.queue.update_status(task.task_id, "failed", {"job_id": job.job_id, "error": str(exc)})
            self.jobs.update(job)
            return job

        job.state["pipeline"] = pipeline.name
        job.state["steps"] = [s.name for s in pipeline.steps]
        failed_step: str | None = None
        for step in pipeline.steps:
            outcome = self._run_step(task, job, step, context)
            if outcome["ok"]:
                completed.append(step.name)
                continue
            failed_step = step.name
            job.status = "escalated" if outcome.get("escalated") else "failed"
            job.state["failure"] = {k: v for k, v in outcome.items() if k != "ok"}
            break

        if failed_step is None:
            job.status = "completed"
            self.queue.update_status(task.task_id, "completed", {
                "job_id": job.job_id, "completed_steps": completed})
            self._publish("job.completed", {"job_id": job.job_id, "steps": completed}, task)
        else:
            self.queue.update_status(task.task_id, job.status, {
                "job_id": job.job_id, "failed_step": failed_step,
                "completed_steps": completed})

        job.state["completed_steps"] = completed
        job.state["duration_s"] = round(time.time() - started, 3)
        job.state["graph_stats"] = graph_stats(context.get("graph"))
        job.state["revision"] = context.get("revision")
        self.jobs.update(job)
        self.log.info("job %s terminé: %s (%s) — %d étapes en %.2fs",
                      job.job_id, job.status, failed_step, len(completed),
                      job.state["duration_s"])
        return job

    # ------------------------------------------------------------ étape
    def _run_step(self, task: TaskSpec, job: Job, step: Step, context: dict[str, Any]) -> dict[str, Any]:
        agent = self._agents.get(step.agent_role)
        if agent is None:
            self._publish(EventTypes.ESCALATION_REQUESTED, {
                "job_id": job.job_id, "step": step.name,
                "reason": f"agent absent du registre: {step.agent_role}"}, task)
            return {"ok": False, "escalated": True,
                    "error": f"agent absent: {step.agent_role}"}
        if not agent.supports(step.action):
            self._publish(EventTypes.ESCALATION_REQUESTED, {
                "job_id": job.job_id, "step": step.name,
                "reason": f"agent {agent.name} ne supporte pas l'action {step.action}"}, task)
            return {"ok": False, "escalated": True,
                    "error": f"action {step.action} non supportée par {agent.name}"}

        context["action"] = step.action
        attempts = max(0, int(step.retry)) + 1
        last_error = ""
        for attempt in range(1, attempts + 1):
            job.current_step = step.name
            self.jobs.log_event(job, "step.started",
                                {"step": step.name, "agent_role": step.agent_role.value, "attempt": attempt})
            self._agent_state.set_agent_status(task.task_id, step.agent_role.value, "running")
            self._publish(EventTypes.AGENT_TASK_ASSIGNED, {
                "job_id": job.job_id, "task_id": task.task_id, "step": step.name,
                "agent_role": step.agent_role.value, "action": step.action, "attempt": attempt,
            }, task)

            result = None
            try:
                result = agent.execute(context)
            except Exception as exc:  # un agent qui crashe ne tue pas le job
                self.log.exception("step %s — exception agent", step.name)
                result = _failed_result(task, step, f"exception: {exc}")

            verified = False
            if result is not None and result.status == AgentStatus.SUCCEEDED:
                verified = bool(agent.verify(result, context))
                if verified and step.name in SELF_VERIFIED_STEPS:
                    verified = self._self_verify(context, job, step)

            if verified:
                revision = result.revision_created if result is not None else None
                if revision is not None:
                    self.rollback.mark_valid(revision)
                    context["revision"] = revision
                self._agent_state.set_agent_status(
                    task.task_id, step.agent_role.value, "succeeded",
                    confidence=float(result.confidence) if result is not None else 0.0,
                    output=(result.output if result is not None else {}))
                self._publish(EventTypes.AGENT_TASK_COMPLETED, {
                    "job_id": job.job_id, "step": step.name,
                    "agent_role": step.agent_role.value, "status": "succeeded",
                    "confidence": float(result.confidence) if result is not None else 0.0,
                    "revision": revision, "attempt": attempt,
                }, task)
                self.jobs.log_event(job, "step.completed", {
                    "step": step.name, "attempt": attempt,
                    "confidence": float(result.confidence) if result is not None else 0.0})
                self._checkpoint(job, step, context)
                self._after_step(task, context, result)
                return {"ok": True, "attempt": attempt,
                        "confidence": float(result.confidence) if result is not None else 0.0}

            # échec → rollback + éventuel retry
            last_error = (result.rationale if result is not None and result.rationale
                          else f"vérification échouée ({step.name})")
            self._agent_state.set_agent_status(
                task.task_id, step.agent_role.value, "failed",
                confidence=float(result.confidence) if result is not None else 0.0)
            self.jobs.log_event(job, "step.failed", {"step": step.name, "attempt": attempt,
                                                     "reason": last_error[:300]})
            self._rollback(task, job, step, context, last_error)
            remaining = attempts - attempt
            if remaining > 0:
                self.log.warning("step %s échec (tentative %d/%d) — rollback puis retry",
                                 step.name, attempt, attempts)

        # retries épuisés → escalation humaine
        self._publish(EventTypes.ESCALATION_REQUESTED, {
            "job_id": job.job_id, "step": step.name, "reason": last_error[:300],
            "retries_exhausted": True}, task)
        self.jobs.log_event(job, "escalation", {"step": step.name, "reason": last_error[:300]})
        return {"ok": False, "escalated": True, "error": last_error}

    # ------------------------------------------------------------ vérification
    def _self_verify(self, context: dict[str, Any], job: Job, step: Step) -> bool:
        """Self-verifier du cerveau IA (services.ai_engine.SelfVerifier)."""
        graph = context.get("graph")
        if graph is None:
            return True
        cls = try_import("services.ai_engine", ["SelfVerifier"]).get("SelfVerifier")
        if cls is None:
            return True
        try:
            try:
                verifier = cls()
            except TypeError:
                verifier = cls()
            report = verifier.verify(graph, context)
        except Exception as exc:
            self.log.debug("SelfVerifier indisponible (%s) — étape %s tolérée", exc, step.name)
            return True
        passed = bool(get_field(report, "passed", "ok", default=True))
        if not passed:
            issues = get_field(report, "issues", default=[]) or []
            context["last_self_issues"] = [str(i) for i in issues][:20] if isinstance(issues, list) else [str(issues)]
            self.jobs.log_event(job, "self_verify.failed", {
                "step": step.name, "issues": context["last_self_issues"][:5]})
        return passed

    # ------------------------------------------------------------ rollback
    def _rollback(self, task: TaskSpec, job: Job, step: Step,
                  context: dict[str, Any], reason: str) -> None:
        """Rollback vers la dernière révision valide (state_manager + versioning)."""
        current_rev = context.get("revision")
        if current_rev is not None:
            self.rollback.mark_invalid(current_rev, reason=f"{step.name}: {reason[:120]}")
        target_rev = self.rollback.last_valid()
        restored = False
        agent = self._agents.get(step.agent_role)
        if agent is not None:
            try:
                restored = bool(agent.rollback(context, target_rev))
            except Exception:
                restored = False
        if not restored and target_rev is not None:
            versioning = ensure_versioning(context)
            if versioning is not None:
                try:
                    graph = versioning.restore(int(target_rev))
                    if graph is not None:
                        context["graph"] = graph
                        restored = True
                except Exception:
                    self.log.debug("restore(%s) impossible", target_rev, exc_info=True)
        if restored:
            self._publish(EventTypes.ROLLBACK_EXECUTED, {
                "job_id": job.job_id, "step": step.name,
                "to_rev": target_rev, "reason": reason[:200]}, task)
        self.jobs.log_event(job, "rollback", {
            "step": step.name, "to_rev": target_rev, "restored": restored,
            "reason": reason[:200]})

    # ------------------------------------------------------------ checkpoint
    def _checkpoint(self, job: Job, step: Step, context: dict[str, Any]) -> None:
        """Snapshot (graph + SMM) après une étape réussie."""
        smm = context.get("smm")
        snapshot = ""
        if smm is not None:
            exported = None
            try:
                exported = smm.export_for_llm()
            except Exception:
                exported = None
            if isinstance(exported, str):
                snapshot = exported[:8000]
            elif exported is not None:
                import json

                snapshot = json.dumps(exported, default=str)[:8000]
        checkpoint_id = self.checkpoints.checkpoint(
            job.job_id, step.name, serialize_graph(context.get("graph")), snapshot)
        self.checkpoints.prune(keep=5)
        self.jobs.log_event(job, "checkpoint", {"step": step.name, "checkpoint_id": checkpoint_id})

    # ------------------------------------------------------------ post-étape
    def _after_step(self, task: TaskSpec, context: dict[str, Any], result: Any) -> None:
        """SMM (si un graphe vient d'apparaître) + persistance du design courant."""
        if context.get("graph") is not None:
            ensure_smm(context)
            revision = None
            if result is not None and getattr(result, "revision_created", None) is not None:
                revision = result.revision_created
            revision = revision or context.get("revision")
            if revision is None:
                history = self._design_state.history(
                    task.tenant_id, str(context.get("user_id") or "default"), task.project_id)
                revision = (history[-1] + 1) if history else 0
            try:
                self._design_state.save_design(
                    task.tenant_id, str(context.get("user_id") or "default"),
                    task.project_id, context["graph"], revision)
                context["revision"] = revision
            except Exception:
                self.log.debug("persistance design impossible", exc_info=True)

    # ------------------------------------------------------------ contexte
    def _prepare_context(self, task: TaskSpec, job: Job) -> dict[str, Any]:
        params = dict(task.params or {})
        context: dict[str, Any] = {
            "task_id": task.task_id,
            "task": {"task_id": task.task_id, "pipeline": task.pipeline_name,
                     "correlation_id": task.correlation_id},
            "correlation_id": task.correlation_id,
            "project_id": task.project_id,
            "tenant_id": task.tenant_id,
            "user_id": str(params.get("user_id") or "default"),
            "message": str(params.get("message") or ""),
            "params": params,
            "action": "",
            "graph": None,
            "versioning": None,
            "smm": None,
            "intents": params.get("intents"),
            "revision": None,
        }
        ensure_versioning(context)

        # graphe initial : param explicite > design persisté
        graph = params.get("graph")
        if isinstance(graph, dict):
            graph = deserialize_graph(graph)
        if graph is None and params.get("graph_dict"):
            graph = deserialize_graph(params["graph_dict"])
        if graph is None:
            try:
                loaded = self._design_state.load_design(
                    task.tenant_id, context["user_id"], task.project_id)
                if loaded is not None:
                    graph, revision = loaded
                    context["revision"] = revision
            except Exception:
                self.log.debug("chargement design persisté impossible", exc_info=True)
        context["graph"] = graph
        if graph is not None:
            ensure_smm(context)

        # intents depuis le message (parse anticipé, partagé par les agents)
        if context["message"] and context["intents"] is None:
            self._try_parse_intents(context)
        job.state["initial_stats"] = graph_stats(graph)
        self.jobs.update(job)
        return context

    def _try_parse_intents(self, context: dict[str, Any]) -> None:
        mods = try_import("services.ai_engine", ["IntentParser"])
        parser_cls = mods.get("IntentParser")
        if parser_cls is None:
            return
        try:
            try:
                parser = parser_cls()
            except TypeError:
                parser = parser_cls()
            parsed = parser.parse(context["message"])
            context["intents"] = parser.to_intent_graph(parsed)
            context["intent_parse"] = {
                "project_type": str(get_field(parsed, "project_type", default="") or ""),
                "confidence": float(get_field(parsed, "confidence", default=0.7) or 0.7),
            }
        except Exception as exc:
            self.log.debug("parse d'intention anticipé impossible: %s", exc)

    # ------------------------------------------------------------ events
    def _publish(self, event_type: str, payload: dict[str, Any], task: TaskSpec) -> None:
        publish_event(make_event(
            event_type, payload,
            project_id=task.project_id,
            tenant_id=task.tenant_id,
            source="workflow_engine",
            correlation_id=task.correlation_id,
        ))


def _failed_result(task: TaskSpec, step: Step, rationale: str) -> Any:
    from shared.schemas import AgentResultSchema

    return AgentResultSchema(task_id=task.task_id, role=step.agent_role.value,
                             status=AgentStatus.FAILED, output={}, confidence=0.0,
                             rationale=rationale)
