/**
 * AgentActivityFeed — activité temps réel des agents (store agent_store
 * branché sur le WS) : icône de rôle, statut, confidence, timestamp, filtre.
 */
"use client";

import { useMemo, useState } from "react";
import { Badge, mapStatusTone } from "@/components/ui/Badge";
import { Panel } from "@/components/ui/Panel";
import { selectActiveCount, useAgentStore } from "@/stores/agent_store";
import type { AgentEvent } from "@/types";

/** Icône + libellé FR par rôle d'agent. */
const ROLE_META: Record<string, { icon: string; label: string }> = {
  planner: { icon: "🧠", label: "Planificateur" },
  researcher: { icon: "🔎", label: "Chercheur" },
  selector: { icon: "🧩", label: "Sélection" },
  placement: { icon: "📍", label: "Placement" },
  routing: { icon: "🧭", label: "Routage" },
  corrector: { icon: "✅", label: "Correcteur" },
  simulator: { icon: "🔬", label: "Simulateur" },
  optimizer: { icon: "⚡", label: "Optimiseur" },
  exporter: { icon: "📤", label: "Export" },
  constraints: { icon: "📏", label: "Contraintes" },
  design_core: { icon: "🧬", label: "Design Core" },
  system: { icon: "⚙️", label: "Système" },
};

function roleMeta(role: string): { icon: string; label: string } {
  return ROLE_META[role] ?? { icon: "⚙️", label: role };
}

function fmtTime(ts: number): string {
  const d = new Date(ts < 10_000_000_000 ? ts * 1000 : ts);
  return d.toLocaleTimeString("fr-FR", { hour12: false });
}

function eventLabel(e: AgentEvent): string {
  const role = (e.payload.role ?? e.payload.agent) as string | undefined;
  const note = (e.payload.note ?? e.payload.summary ?? e.payload.message) as string | undefined;
  return note ? String(note) : role ? `${role} · ${e.type}` : e.type;
}

export function AgentActivityFeed() {
  const events = useAgentStore((s) => s.events);
  const connected = useAgentStore((s) => s.connected);
  const activeCount = useAgentStore(selectActiveCount);
  const [roleFilter, setRoleFilter] = useState<string>("all");

  const roles = useMemo(() => {
    const set = new Set<string>();
    for (const e of events) {
      const r = (e.payload.role ?? e.payload.agent) as string | undefined;
      set.add(typeof r === "string" && r ? r : roleFromType(e));
    }
    return Array.from(set);
  }, [events]);

  const visible = roleFilter === "all" ? events : events.filter((e) => roleFromType(e) === roleFilter || e.payload.role === roleFilter);

  return (
    <Panel
      title="Activité des agents"
      subtitle={`${activeCount} agent${activeCount > 1 ? "s" : ""} actif${activeCount > 1 ? "s" : ""} · ${events.length} événements`}
      right={
        <Badge tone={connected ? "green" : "amber"}>{connected ? "WS live" : "démo mock"}</Badge>
      }
      bodyClassName="flex flex-col min-h-0"
    >
      {/* Filtre par rôle */}
      <div className="shrink-0 border-b border-panel-border px-3 py-2">
        <select
          className="input py-1.5 text-xs"
          value={roleFilter}
          onChange={(e) => setRoleFilter(e.target.value)}
          aria-label="Filtrer par rôle"
        >
          <option value="all">Tous les rôles</option>
          {roles.map((r) => (
            <option key={r} value={r}>
              {roleMeta(r).label}
            </option>
          ))}
        </select>
      </div>

      {/* Flux */}
      <div className="min-h-0 flex-1 space-y-1.5 overflow-y-auto p-3">
        {visible.length === 0 && (
          <p className="px-1 py-6 text-center text-xs text-ink-dim">
            En attente d&rsquo;événements… lancez une commande (le flux démarre automatiquement).
          </p>
        )}
        {visible.map((e) => {
          const role = ((e.payload.role ?? e.payload.agent) as string | undefined) ?? roleFromType(e);
          const meta = roleMeta(role);
          const conf = typeof e.payload.confidence === "number" ? e.payload.confidence : null;
          return (
            <div key={e.id} className="flex items-start gap-2.5 rounded-lg border border-panel-border bg-panel-soft px-2.5 py-2">
              <span className="mt-0.5 text-base leading-none" aria-hidden>{meta.icon}</span>
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-1.5">
                  <span className="text-xs font-semibold text-ink">{meta.label}</span>
                  <Badge tone={mapStatusTone(e.type)}>{e.type.includes("assigned") || e.type.includes("started") ? "running" : e.type.includes("failed") || e.type.includes("violated") ? "failed" : "done"}</Badge>
                  {conf !== null && <Badge tone={conf >= 0.8 ? "cyan" : conf >= 0.6 ? "amber" : "red"}>{Math.round(conf * 100)}%</Badge>}
                </div>
                <p className="mt-0.5 truncate text-[11px] text-ink-dim" title={eventLabel(e)}>{eventLabel(e)}</p>
              </div>
              <time className="shrink-0 font-mono text-[10px] text-ink-dim">{fmtTime(e.ts)}</time>
            </div>
          );
        })}
      </div>
    </Panel>
  );
}

/** Ré-déduction de rôle locale (évite une dépendance circulaire au store). */
function roleFromType(e: AgentEvent): string {
  if (e.type.startsWith("intent.") || e.type.startsWith("chat.")) return "planner";
  if (e.type.startsWith("components.") || e.type.startsWith("import.")) return "selector";
  if (e.type.startsWith("placement.")) return "placement";
  if (e.type.startsWith("routing.")) return "routing";
  if (e.type.startsWith("verification.") || e.type.startsWith("drc.")) return "corrector";
  if (e.type.startsWith("simulation.")) return "simulator";
  if (e.type.startsWith("optimization.")) return "optimizer";
  if (e.type.startsWith("export.") || e.type.startsWith("manufacturing.")) return "exporter";
  if (e.type.startsWith("constraint.")) return "constraints";
  return "system";
}
