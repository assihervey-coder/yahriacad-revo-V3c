/** Page simulations — 4 onglets (Thermique/EM/SI/PI) + qualité & optimisation. */
"use client";

import { useEffect, useState } from "react";
import { QualityPanel } from "@/components/dashboard/quality/QualityPanel";
import { OptimizationPanel } from "@/components/dashboard/optimization/OptimizationPanel";
import { EMPanel } from "@/components/simulation_dashboard/electromagnetic/EMPanel";
import { PowerIntegrityPanel } from "@/components/simulation_dashboard/power_integrity/PowerIntegrityPanel";
import { SignalIntegrityPanel } from "@/components/simulation_dashboard/signal_integrity/SignalIntegrityPanel";
import { ThermalPanel } from "@/components/simulation_dashboard/thermal/ThermalPanel";
import { Badge } from "@/components/ui/Badge";
import { useDesignStore } from "@/stores/design_store";
import { SIM_KINDS, useSimulationStore } from "@/stores/simulation_store";
import type { SimKind } from "@/types";

const TABS: { kind: SimKind; label: string; icon: string }[] = [
  { kind: "thermal", label: "Thermique", icon: "🌡️" },
  { kind: "em", label: "Électromagnétique", icon: "📡" },
  { kind: "si", label: "Signal Integrity", icon: "⚡" },
  { kind: "pi", label: "Power Integrity", icon: "🔌" },
];

export default function SimulationsPage() {
  const results = useSimulationStore((s) => s.results);
  const running = useSimulationStore((s) => s.running);
  const run = useSimulationStore((s) => s.run);
  const projectId = useDesignStore((s) => s.projectId) ?? useDesignStore((s) => s.design?.project_id ?? null);
  const [tab, setTab] = useState<SimKind>("thermal");

  // Lancement automatique au premier rendu (fallback mock si l'API est down).
  useEffect(() => {
    void run(projectId ?? "demo-esp32-4l", SIM_KINDS);
  }, [run, projectId]);

  const busy = running.length > 0;

  return (
    <div className="mx-auto w-full max-w-[1200px] px-4 py-8">
      <header className="mb-5 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold">Simulations</h1>
          <p className="mt-1 text-sm text-ink-dim">
            Cerveau physique — projet <span className="font-mono text-ink">{projectId ?? "demo-esp32-4l"}</span>
          </p>
        </div>
        <button type="button" className="btn btn-primary" onClick={() => void run(projectId ?? "demo-esp32-4l", SIM_KINDS)} disabled={busy}>
          {busy ? "Simulation en cours…" : "▶ Lancer les simulations"}
        </button>
      </header>

      {/* Onglets */}
      <nav className="mb-4 flex flex-wrap gap-1.5">
        {TABS.map((t) => {
          const res = results[t.kind];
          return (
            <button
              key={t.kind}
              type="button"
              onClick={() => setTab(t.kind)}
              className={`btn px-3 py-1.5 text-sm ${tab === t.kind ? "btn-primary" : "btn-ghost border border-panel-border"}`}
            >
              <span aria-hidden>{t.icon}</span> {t.label}
              {res && (
                <Badge tone={res.passed ? "green" : "red"}>{res.passed ? "pass" : "fail"}</Badge>
              )}
              {running.includes(t.kind) && <Badge tone="cyan">…</Badge>}
            </button>
          );
        })}
      </nav>

      {/* Panneau actif */}
      <section className="panel p-5">
        {tab === "thermal" && <ThermalPanel result={results.thermal ?? null} />}
        {tab === "em" && <EMPanel result={results.em ?? null} />}
        {tab === "si" && <SignalIntegrityPanel result={results.si ?? null} />}
        {tab === "pi" && <PowerIntegrityPanel result={results.pi ?? null} />}
      </section>

      {/* Qualité + optimisation */}
      <section className="mt-6 grid gap-3 lg:grid-cols-2">
        <QualityPanel projectId={projectId} />
        <OptimizationPanel projectId={projectId} />
      </section>
    </div>
  );
}
