/**
 * ConstraintsPanel — contraintes actives (API si dispo, sinon mock),
 * badges violation OK/KO, bouton « Réévaluer ».
 */
"use client";

import { useCallback, useEffect, useState } from "react";
import { Badge } from "@/components/ui/Badge";
import { Panel } from "@/components/ui/Panel";
import { apiClient } from "@/services/api_client";
import type { ConstraintItem } from "@/types";

export function ConstraintsPanel({ projectId, compact = false }: { projectId: string | null; compact?: boolean }) {
  const [items, setItems] = useState<ConstraintItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [evaluatedAt, setEvaluatedAt] = useState<string>("");

  const load = useCallback(async () => {
    setLoading(true);
    const list = await apiClient.getConstraints(projectId ?? "demo-esp32-4l");
    setItems(list);
    setEvaluatedAt(new Date().toLocaleTimeString("fr-FR", { hour12: false }));
    setLoading(false);
  }, [projectId]);

  useEffect(() => {
    void load();
  }, [load]);

  const violated = items.filter((c) => c.violated).length;

  return (
    <Panel
      title="Contraintes actives"
      subtitle={`${items.length - violated}/${items.length} OK · évalué ${evaluatedAt || "—"}`}
      right={
        <button type="button" className="btn btn-primary px-2.5 py-1 text-xs" onClick={() => void load()} disabled={loading}>
          {loading ? "…" : "Réévaluer"}
        </button>
      }
      bodyClassName="overflow-y-auto"
    >
      <ul className="space-y-1.5">
        {items.map((c) => (
          <li key={c.id} className="flex items-start justify-between gap-2 rounded-lg border border-panel-border bg-panel-soft px-3 py-2">
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-1.5">
                <span className="text-xs font-semibold text-ink">{c.name}</span>
                <Badge tone={c.severity === "error" ? "red" : c.severity === "warning" ? "amber" : "slate"}>{c.severity}</Badge>
              </div>
              <p className="mt-0.5 truncate text-[11px] text-ink-dim" title={`${c.target}${c.detail ? ` — ${c.detail}` : ""}`}>
                {c.target}
                {!compact && c.detail ? ` — ${c.detail}` : ""}
              </p>
            </div>
            <Badge tone={c.violated ? "red" : "green"}>{c.violated ? "KO" : "OK"}</Badge>
          </li>
        ))}
      </ul>
    </Panel>
  );
}
