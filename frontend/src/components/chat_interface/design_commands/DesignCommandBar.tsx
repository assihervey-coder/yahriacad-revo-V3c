/**
 * DesignCommandBar — commandes rapides pré-écrites qui postent sur
 * /api/v1/chat/commands (Place, Route, Simulate, Optimize, Export Gerber).
 */
"use client";

import { useState } from "react";
import { Badge } from "@/components/ui/Badge";
import { apiClient } from "@/services/api_client";
import { useAgentStore } from "@/stores/agent_store";
import { useDesignStore } from "@/stores/design_store";
import type { ChatCommandResponse } from "@/types";

interface QuickCommand {
  id: string;
  label: string;
  icon: string;
  message: string;
  tone: "cyan" | "violet" | "green" | "amber";
}

const COMMANDS: QuickCommand[] = [
  { id: "place", label: "Place", icon: "📍", tone: "cyan", message: "Place les composants sur la carte et optimise le placement (contraintes thermiques et keepouts incluses)." },
  { id: "route", label: "Route", icon: "🧭", tone: "cyan", message: "Route tous les nets avec A* multicouche, respecte les impédances cibles et minimise les vias." },
  { id: "simulate", label: "Simulate", icon: "🔬", tone: "green", message: "Lance les simulations thermique, électromagnétique, signal integrity et power integrity." },
  { id: "optimize", label: "Optimize", icon: "⚡", tone: "violet", message: "Optimise le placement et le routage en mode balanced, maximum 20 itérations, puis réévalue la qualité." },
  { id: "export", label: "Export Gerber", icon: "📤", tone: "amber", message: "Exporte le paquet de fabrication Gerber RS-274X + Excellon + BOM + IPC-2581 pour JLCPCB." },
];

export function DesignCommandBar() {
  const [busyId, setBusyId] = useState<string | null>(null);
  const [last, setLast] = useState<ChatCommandResponse | null>(null);
  const projectId = useDesignStore((s) => s.projectId) ?? "demo-esp32-4l";

  const run = async (cmd: QuickCommand) => {
    if (busyId) return;
    setBusyId(cmd.id);
    const res = await apiClient.runChatCommand(cmd.message, projectId ?? "");
    setLast(res);
    useAgentStore.getState().appendEvent({
      id: `cmd-${Date.now().toString(36)}`,
      type: "chat.command",
      payload: { command: cmd.id, intent: res.intent, job_id: res.job_id },
      ts: Date.now() / 1000,
    });
    setBusyId(null);
  };

  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap gap-1.5">
        {COMMANDS.map((c) => (
          <button
            key={c.id}
            type="button"
            onClick={() => void run(c)}
            disabled={busyId !== null}
            className="btn px-2.5 py-1.5 text-xs"
            style={{ borderColor: "rgba(35,42,56,1)" }}
            title={c.message}
          >
            <span aria-hidden>{c.icon}</span>
            {busyId === c.id ? "…" : c.label}
          </button>
        ))}
      </div>
      {last && (
        <div className="flex flex-wrap items-center gap-1.5 text-[11px] text-ink-dim">
          <Badge tone={last.accepted ? "green" : "red"}>{last.accepted ? "acceptée" : "refusée"}</Badge>
          {last.intent && <Badge tone="violet">{last.intent}</Badge>}
          {last.job_id && <span className="font-mono">job {last.job_id}</span>}
        </div>
      )}
    </div>
  );
}
