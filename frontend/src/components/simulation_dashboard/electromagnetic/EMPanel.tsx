/** EMPanel — crosstalk, boucle d'antenne, blindage : metrics + badges. */
"use client";

import { Badge } from "@/components/ui/Badge";
import { BarGauge } from "@/components/ui/Gauge";
import { readNum } from "@/services/api_client";
import type { SimResult } from "@/types";

export function EMPanel({ result }: { result: SimResult | null }) {
  if (!result) {
    return <p className="text-sm text-ink-dim">Lancez la simulation électromagnétique pour afficher les metrics.</p>;
  }

  const crosstalk = readNum(result.metrics, "crosstalk_mv", 42.3);
  const crosstalkLimit = readNum(result.metrics, "crosstalk_limit_mv", 50);
  const loop = readNum(result.metrics, "max_loop_area_mm2", 18.6);
  const shield = readNum(result.metrics, "shield_db", 12.5);
  const emissions = readNum(result.metrics, "emissions_dbuv", 38.2);
  const emissionsLimit = readNum(result.metrics, "emissions_limit_dbuv", 42);
  const risk = typeof result.metrics.risk === "string" ? result.metrics.risk : "modéré";

  const ok = crosstalk <= crosstalkLimit && emissions <= emissionsLimit;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-1.5">
        <Badge tone={ok ? "green" : "red"}>{ok ? "PASS" : "FAIL"}</Badge>
        <Badge tone={risk === "faible" ? "green" : risk === "modéré" ? "amber" : "red"}>risque {risk}</Badge>
        <Badge tone={result.source === "api" ? "cyan" : "amber"}>{result.source === "api" ? "API" : "mock"}</Badge>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <div className="panel border-panel-border bg-panel-soft p-4">
          <h3 className="text-sm font-semibold">Crosstalk</h3>
          <p className="mt-1 font-mono text-2xl text-ink">
            {crosstalk} <span className="text-sm text-ink-dim">mV</span>
          </p>
          <div className="mt-2">
            <BarGauge value={crosstalk} max={crosstalkLimit * 1.5} right={`limite ${crosstalkLimit} mV`} color={crosstalk <= crosstalkLimit ? "#34d399" : "#fb7185"} />
          </div>
          <p className="mt-1 text-[11px] text-ink-dim">Couplage maximal entre nets adjacents (sensibilité 3V3/USB).</p>
        </div>

        <div className="panel border-panel-border bg-panel-soft p-4">
          <h3 className="text-sm font-semibold">Boucle de courant max</h3>
          <p className="mt-1 font-mono text-2xl text-ink">
            {loop} <span className="text-sm text-ink-dim">mm²</span>
          </p>
          <div className="mt-2">
            <BarGauge value={loop} max={40} right="cible < 20 mm²" color={loop < 20 ? "#34d399" : "#fbbf24"} />
          </div>
          <p className="mt-1 text-[11px] text-ink-dim">Aire de boucle = rayonnement EMI — réduite par le plan GND.</p>
        </div>

        <div className="panel border-panel-border bg-panel-soft p-4">
          <h3 className="text-sm font-semibold">Efficacité de blindage</h3>
          <p className="mt-1 font-mono text-2xl text-ink">
            {shield} <span className="text-sm text-ink-dim">dB</span>
          </p>
          <div className="mt-2">
            <BarGauge value={shield} max={30} right="cible > 10 dB" />
          </div>
        </div>

        <div className="panel border-panel-border bg-panel-soft p-4">
          <h3 className="text-sm font-semibold">Émissions conduites</h3>
          <p className="mt-1 font-mono text-2xl text-ink">
            {emissions} <span className="text-sm text-ink-dim">dBµV</span>
          </p>
          <div className="mt-2">
            <BarGauge value={emissions} max={emissionsLimit * 1.3} right={`limite CISPR ${emissionsLimit} dBµV`} color={emissions <= emissionsLimit ? "#34d399" : "#fb7185"} />
          </div>
        </div>
      </div>
    </div>
  );
}
