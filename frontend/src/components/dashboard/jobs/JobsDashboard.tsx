/**
 * JobsDashboard — jobs du pipeline (fetch /chat/commands/{id}/status + WS) :
 * progression par étape parse→select→place→route→verify→optimize→export.
 */
"use client";

import { useCallback, useEffect, useState } from "react";
import { StatusBadge } from "@/components/ui/Badge";
import { apiClient } from "@/services/api_client";
import { useAgentStore } from "@/stores/agent_store";
import type { Job } from "@/types";

export const JOB_STEPS = ["parse", "select", "place", "route", "verify", "optimize", "export"] as const;

const STEP_LABEL: Record<string, string> = {
  parse: "Parse",
  select: "Sélection",
  place: "Placement",
  route: "Routage",
  verify: "Vérification",
  optimize: "Optimisation",
  export: "Export",
};

export function JobsDashboard({ jobId }: { jobId: string | null }) {
  const [job, setJob] = useState<Job | null>(null);
  const events = useAgentStore((s) => s.events);

  const load = useCallback(async () => {
    if (!jobId) {
      setJob(null);
      return;
    }
    setJob(await apiClient.getJobStatus(jobId));
  }, [jobId]);

  // Chargement initial + rafraîchi quand un agent termine une tâche (WS).
  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (!jobId) return;
    const last = events[0];
    if (last && (last.type.includes("agent.task") || last.type.includes("completed") || last.type.includes("proposed"))) {
      void load();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [events[0]?.id]);

  // Poll léger tant que le job tourne.
  useEffect(() => {
    if (job?.status !== "running" && job?.status !== "queued") return;
    const t = setInterval(() => void load(), 6000);
    return () => clearInterval(t);
  }, [job?.status, load]);

  if (!jobId || !job) {
    return (
      <p className="px-1 py-2 text-xs text-ink-dim">
        Aucun job en cours — lancez une commande pour démarrer le pipeline.
      </p>
    );
  }

  const doneSteps = new Set((job.completed_steps ?? []).map((s) => s.toLowerCase()));
  const currentIdx = job.current_step ? JOB_STEPS.indexOf(job.current_step.toLowerCase() as (typeof JOB_STEPS)[number]) : -1;
  const progress = job.progress ?? Math.round(((doneSteps.size + (currentIdx >= 0 ? 0.5 : 0)) / JOB_STEPS.length) * 100);

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-1.5">
          <StatusBadge status={job.status} />
          <span className="font-mono text-[10px] text-ink-dim">{job.job_id}</span>
        </div>
        <span className="text-xs text-ink-dim">{progress}%</span>
      </div>

      {/* Étapes cochées */}
      <ol className="flex flex-wrap items-center gap-1">
        {JOB_STEPS.map((step, i) => {
          const done = doneSteps.has(step);
          const current = i === currentIdx || (!done && currentIdx < 0 && step === "route");
          return (
            <li key={step} className="flex items-center gap-1">
              <span
                className={`flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] ${
                  done
                    ? "border-emerald-400/40 bg-emerald-400/10 text-emerald-300"
                    : current
                      ? "border-accent-cyan/50 bg-accent-cyan/10 text-accent-cyan animate-pulse"
                      : "border-panel-border bg-panel-soft text-ink-dim"
                }`}
                title={STEP_LABEL[step]}
              >
                {done ? "✓" : current ? "▶" : "○"} {STEP_LABEL[step]}
              </span>
              {i < JOB_STEPS.length - 1 && <span className="text-panel-border">›</span>}
            </li>
          );
        })}
      </ol>

      {/* Barre de progression */}
      <div className="h-1.5 w-full overflow-hidden rounded-full bg-panel-border">
        <div
          className="h-full rounded-full bg-gradient-to-r from-accent-cyan to-accent-violet transition-all"
          style={{ width: `${Math.min(100, Math.max(0, progress))}%` }}
        />
      </div>
    </div>
  );
}
