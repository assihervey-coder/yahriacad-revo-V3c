/**
 * CreditDashboard — crédits restants (GET /api/v1/billing/credits/{tenant}),
 * jauge circulaire + estimation de coût par action (chat 1, sim 2, export 5).
 */
"use client";

import { useEffect, useState } from "react";
import { Badge } from "@/components/ui/Badge";
import { Gauge } from "@/components/ui/Gauge";
import { Panel } from "@/components/ui/Panel";
import { apiClient } from "@/services/api_client";
import type { Credits } from "@/types";

/** Coût unitaire estimé par action (aligné sur billing). */
const ACTION_COSTS: { action: string; icon: string; cost: number }[] = [
  { action: "Commande chat", icon: "💬", cost: 1 },
  { action: "Simulation complète", icon: "🔬", cost: 2 },
  { action: "Optimisation", icon: "⚡", cost: 3 },
  { action: "Export Gerber", icon: "📤", cost: 5 },
];

export function CreditDashboard({ compact = false }: { compact?: boolean }) {
  const [credits, setCredits] = useState<Credits | null>(null);

  useEffect(() => {
    let alive = true;
    void (async () => {
      const c = await apiClient.getCredits();
      if (alive) setCredits(c);
    })();
    return () => {
      alive = false;
    };
  }, []);

  return (
    <Panel
      title="Crédits"
      subtitle={credits ? `tenant ${credits.tenant} · ${credits.source === "mock" ? "mock (API injoignable)" : "API"}` : "chargement…"}
      right={credits && <Badge tone={credits.source === "mock" ? "amber" : "cyan"}>{credits.source === "mock" ? "mock" : "live"}</Badge>}
    >
      {credits && (
        <div className="flex flex-wrap items-center gap-6">
          <Gauge value={credits.credits} max={credits.free_tier} label="crédits restants" size={120} />
          <div className="min-w-[220px] flex-1">
            <ul className="space-y-1.5">
              {ACTION_COSTS.map((a) => (
                <li key={a.action} className="flex items-center justify-between rounded-lg border border-panel-border bg-panel-soft px-3 py-1.5 text-xs">
                  <span className="text-ink-dim">
                    <span className="mr-1.5" aria-hidden>{a.icon}</span>
                    {a.action}
                  </span>
                  <span className="font-mono text-ink">
                    {a.cost} crédit{a.cost > 1 ? "s" : ""}
                  </span>
                </li>
              ))}
            </ul>
            {!compact && (
              <p className="mt-3 text-[11px] text-ink-dim">
                Chaque commande chat débite 1 crédit, un cycle de simulations complet 2, un export de fabrication 5
                (débité côté API via POST /billing/consume).
              </p>
            )}
          </div>
        </div>
      )}
    </Panel>
  );
}
