/** PowerIntegrityPanel — IR drop par rail d'alimentation, barres + verdict. */
"use client";

import { Badge } from "@/components/ui/Badge";
import { BarGauge } from "@/components/ui/Gauge";
import { readArr, readNum } from "@/services/api_client";
import type { SimResult } from "@/types";

interface RailRow {
  net: string;
  v_nom_v?: number;
  ir_drop_mv?: number;
}

export function PowerIntegrityPanel({ result }: { result: SimResult | null }) {
  if (!result) {
    return <p className="text-sm text-ink-dim">Lancez la simulation PI pour afficher les rails d&rsquo;alimentation.</p>;
  }

  const rails = readArr<RailRow>(result.metrics, "rails");
  const maxDrop = readNum(result.metrics, "max_ir_drop_mv", 21.7);
  const limit = readNum(result.metrics, "limit_mv", 50);
  const pass = maxDrop <= limit;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-1.5">
        <Badge tone={pass ? "green" : "red"}>{pass ? "PASS" : "FAIL"}</Badge>
        <span className="font-mono text-sm text-ink">
          max {maxDrop} mV <span className="text-ink-dim">/ limite {limit} mV</span>
        </span>
        <Badge tone={result.source === "api" ? "cyan" : "amber"}>{result.source === "api" ? "API" : "mock"}</Badge>
      </div>

      <div className="space-y-3">
        {rails.map((r) => {
          const drop = r.ir_drop_mv ?? 0;
          const ok = drop <= limit;
          return (
            <div key={r.net} className="panel border-panel-border bg-panel-soft p-3">
              <div className="mb-1.5 flex items-center justify-between">
                <span className="text-sm font-semibold text-ink">
                  {r.net} <span className="text-xs font-normal text-ink-dim">· {r.v_nom_v ?? 0} V</span>
                </span>
                <span className={`font-mono text-sm ${ok ? "text-emerald-300" : "text-rose-300"}`}>{drop} mV</span>
              </div>
              <BarGauge value={drop} max={limit} right={`${Math.round((drop / Math.max(1, limit)) * 100)} % de la limite`} color={ok ? "#34d399" : "#fb7185"} />
            </div>
          );
        })}
        {rails.length === 0 && <p className="text-sm text-ink-dim">Aucun rail retourné par la simulation.</p>}
      </div>

      <p className="text-[11px] text-ink-dim">
        IR drop mesuré du VRM au pad le plus éloigné (PDN : VRM ∥ céramiques). Cible industrielle : &lt; 2 % de la tension nominale.
      </p>
    </div>
  );
}
