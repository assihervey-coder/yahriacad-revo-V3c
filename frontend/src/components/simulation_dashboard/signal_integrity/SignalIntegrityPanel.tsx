/**
 * SignalIntegrityPanel — tableau par net : impédance cible vs calculée,
 * mismatch %, badge pass/fail. Source : metrics.nets de la simulation SI.
 */
"use client";

import { Badge } from "@/components/ui/Badge";
import { readArr } from "@/services/api_client";
import type { SimResult } from "@/types";

interface SiNetRow {
  net: string;
  target_ohm?: number | null;
  computed_ohm?: number | null;
  mismatch_pct?: number | null;
  passed?: boolean;
}

export function SignalIntegrityPanel({ result }: { result: SimResult | null }) {
  if (!result) {
    return <p className="text-sm text-ink-dim">Lancez la simulation SI pour afficher le tableau d&rsquo;impédances.</p>;
  }

  const rows = readArr<SiNetRow>(result.metrics, "nets");
  const eye = typeof result.metrics.worst_eye_margin_pct === "number" ? result.metrics.worst_eye_margin_pct : null;
  const jitter = typeof result.metrics.jitter_ps === "number" ? result.metrics.jitter_ps : null;
  const allPass = rows.length > 0 ? rows.every((r) => r.passed !== false) : result.passed;

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-1.5">
        <Badge tone={allPass ? "green" : "red"}>{allPass ? "PASS" : "FAIL"}</Badge>
        {eye !== null && <Badge tone={eye >= 15 ? "green" : "amber"}>œil ≥ {eye}%</Badge>}
        {jitter !== null && <Badge tone="slate">jitter {jitter} ps</Badge>}
        <Badge tone={result.source === "api" ? "cyan" : "amber"}>{result.source === "api" ? "API" : "mock"}</Badge>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full min-w-[520px] text-left text-sm">
          <thead>
            <tr className="border-b border-panel-border text-[11px] uppercase tracking-wider text-ink-dim">
              <th className="px-3 py-2">Net</th>
              <th className="px-3 py-2">Cible (Ω)</th>
              <th className="px-3 py-2">Calculée (Ω)</th>
              <th className="px-3 py-2">Mismatch</th>
              <th className="px-3 py-2 text-right">Verdict</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => {
              const fail = r.passed === false;
              return (
                <tr key={r.net} className="border-b border-panel-border/60 hover:bg-panel-soft">
                  <td className="px-3 py-2 font-medium text-ink">{r.net}</td>
                  <td className="px-3 py-2 font-mono text-ink-dim">{r.target_ohm != null ? r.target_ohm : "—"}</td>
                  <td className="px-3 py-2 font-mono text-ink">{r.computed_ohm ?? "—"}</td>
                  <td className="px-3 py-2 font-mono">
                    {r.mismatch_pct != null ? (
                      <span className={fail ? "text-rose-300" : "text-emerald-300"}>+{r.mismatch_pct}%</span>
                    ) : (
                      "—"
                    )}
                  </td>
                  <td className="px-3 py-2 text-right">
                    <Badge tone={fail ? "red" : "green"}>{fail ? "FAIL" : "pass"}</Badge>
                  </td>
                </tr>
              );
            })}
            {rows.length === 0 && (
              <tr>
                <td colSpan={5} className="px-3 py-6 text-center text-ink-dim">
                  Aucun net analysé — la simulation SI n&rsquo;a pas retourné de détail.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      <p className="text-[11px] text-ink-dim">
        Tolérance d&rsquo;impédance : ±5 % de la cible. Les nets sans cible sont vérifiés en continuité uniquement.
      </p>
    </div>
  );
}
