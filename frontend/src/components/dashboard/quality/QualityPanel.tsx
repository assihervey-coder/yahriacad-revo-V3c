/**
 * QualityPanel — score qualité global (jauge circulaire SVG) + breakdown
 * ERC/DRC/DFM/routage/thermique/SI/coût en barres horizontales.
 */
"use client";

import { useCallback, useEffect, useState } from "react";
import { Badge } from "@/components/ui/Badge";
import { BarGauge, Gauge } from "@/components/ui/Gauge";
import { Panel } from "@/components/ui/Panel";
import { apiClient } from "@/services/api_client";
import type { QualityScore } from "@/types";

const AXES: { key: keyof Omit<QualityScore, "overall">; label: string }[] = [
  { key: "drc", label: "DRC" },
  { key: "erc", label: "ERC" },
  { key: "dfm", label: "DFM" },
  { key: "routing", label: "Routage" },
  { key: "thermal", label: "Thermique" },
  { key: "si", label: "Signal Int." },
  { key: "cost", label: "Coût" },
];

export function QualityPanel({ projectId }: { projectId: string | null }) {
  const [score, setScore] = useState<QualityScore | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    setScore(await apiClient.getQuality(projectId ?? "demo-esp32-4l"));
    setLoading(false);
  }, [projectId]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <Panel
      title="Qualité de conception"
      subtitle="DRC · ERC · DFM · routage · thermique · SI · coût"
      right={
        <button type="button" className="btn btn-ghost border border-panel-border px-2.5 py-1 text-xs" onClick={() => void load()} disabled={loading}>
          {loading ? "…" : "Réévaluer"}
        </button>
      }
    >
      {score && (
        <div className="flex flex-wrap items-center gap-6">
          <Gauge value={score.overall} label="score global" size={128} />
          <div className="min-w-[220px] flex-1 space-y-2">
            {AXES.map((a) => (
              <BarGauge key={a.key} label={a.label} value={score[a.key]} right={`${score[a.key]}/100`} />
            ))}
          </div>
          <Badge tone={score.overall >= 85 ? "green" : score.overall >= 70 ? "amber" : "red"}>
            {score.overall >= 85 ? "VALID" : score.overall >= 70 ? "MARGINAL" : "À REVOIR"}
          </Badge>
        </div>
      )}
    </Panel>
  );
}
