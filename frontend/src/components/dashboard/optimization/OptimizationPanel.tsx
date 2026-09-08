/**
 * OptimizationPanel — historique des itérations d'optimisation : sparkline
 * SVG du score par itération + meilleur score. Se met à jour en live sur
 * les événements WS optimization.iteration.
 */
"use client";

import { useCallback, useEffect, useState } from "react";
import { Badge } from "@/components/ui/Badge";
import { Panel } from "@/components/ui/Panel";
import { apiClient } from "@/services/api_client";
import { useAgentStore } from "@/stores/agent_store";
import type { OptimizationIteration } from "@/types";

/** Sparkline SVG (largeur fixe, normalisée min→max). */
function Sparkline({ values, width = 260, height = 48 }: { values: number[]; width?: number; height?: number }) {
  if (values.length < 2) {
    return <p className="text-xs text-ink-dim">Pas assez d&rsquo;itérations pour tracer la convergence.</p>;
  }
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const stepX = width / (values.length - 1);
  const y = (v: number): number => height - 6 - ((v - min) / span) * (height - 12);
  const points = values.map((v, i) => `${i * stepX},${y(v)}`).join(" ");
  const lastX = (values.length - 1) * stepX;
  const lastY = y(values[values.length - 1]);

  return (
    <svg width={width} height={height} className="overflow-visible" role="img" aria-label="Convergence du score">
      <polyline points={points} fill="none" stroke="#22D3EE" strokeWidth={1.8} strokeLinejoin="round" strokeLinecap="round" />
      <circle cx={lastX} cy={lastY} r={2.6} fill="#A78BFA" />
    </svg>
  );
}

export function OptimizationPanel({ projectId }: { projectId: string | null }) {
  const [iterations, setIterations] = useState<OptimizationIteration[]>([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    const list = await apiClient.getOptimizationHistory(projectId ?? "demo-esp32-4l");
    setIterations(list);
    setLoading(false);
  }, [projectId]);

  useEffect(() => {
    void load();
  }, [load]);

  // Live : un événement optimization.iteration ajoute un point.
  const lastEventId = useAgentStore((s) => s.events[0]?.id);
  useEffect(() => {
    const e = useAgentStore.getState().events[0];
    if (!e || e.type !== "optimization.iteration") return;
    const score = typeof e.payload.score === "number" ? e.payload.score : null;
    if (score === null) return;
    setIterations((prev) => [...prev, { iteration: prev.length + 1, score, note: "itération live (WS)" }]);
  }, [lastEventId]);

  const best = iterations.reduce((acc, it) => (it.score > acc.score ? it : acc), { iteration: 0, score: -Infinity } as OptimizationIteration);
  const scores = iterations.map((it) => it.score);

  return (
    <Panel
      title="Optimisation"
      subtitle={`${iterations.length} itérations · meilleur ${Math.round(best.score * 10) / 10}`}
      right={
        <button type="button" className="btn btn-ghost border border-panel-border px-2.5 py-1 text-xs" onClick={() => void load()} disabled={loading}>
          {loading ? "…" : "Rafraîchir"}
        </button>
      }
    >
      <div className="flex flex-wrap items-start gap-4">
        <Sparkline values={scores} />
        <div className="min-w-[140px] space-y-1.5">
          <div className="flex items-center gap-1.5">
            <Badge tone="violet">meilleur score</Badge>
            <span className="font-mono text-lg font-bold text-ink">{Math.round(best.score * 10) / 10}</span>
          </div>
          {best.note && <p className="text-[11px] text-ink-dim">it. {best.iteration} — {best.note}</p>}
        </div>
      </div>

      {/* Détail des dernières itérations */}
      <ul className="mt-3 space-y-1">
        {[...iterations].slice(-4).reverse().map((it) => (
          <li key={`${it.iteration}-${it.score}`} className="flex items-center justify-between rounded-lg border border-panel-border bg-panel-soft px-2.5 py-1.5 text-[11px]">
            <span className="text-ink-dim">
              it. {it.iteration} {it.note ? `· ${it.note}` : ""}
            </span>
            <span className="font-mono text-ink">{it.score}</span>
          </li>
        ))}
      </ul>
    </Panel>
  );
}
