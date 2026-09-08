/**
 * ChatPanel — interface d'intention : messages user/assistant, envoi
 * POST /api/v1/chat/commands, affichage de la réponse (intent, job_id, plan).
 */
"use client";

import { useEffect, useRef, useState } from "react";
import { Badge } from "@/components/ui/Badge";
import { apiClient } from "@/services/api_client";
import { useAgentStore } from "@/stores/agent_store";
import { useDesignStore } from "@/stores/design_store";
import { useProjectStore } from "@/stores/project_store";
import type { ChatMessage } from "@/types";

const EXAMPLES: string[] = [
  "Conçois une carte ESP32 4 couches avec BME680 sur USB-C, JLCPCB",
  "Route tous les nets haute vitesse en 90 Ω différentiel",
  "Optimise le placement pour la thermique puis réévalue",
  "Exporte le paquet de fabrication Gerber pour PCBWay",
];

let seq = 0;
function newMsgId(): string {
  seq += 1;
  return `m-${Date.now().toString(36)}-${seq}`;
}

export function ChatPanel() {
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: newMsgId(),
      role: "assistant",
      text: "Bonjour 👋 Décrivez la carte à concevoir — je planifie le pipeline d'agents (sélection, placement, routage, vérification, export).",
      ts: Date.now() / 1000,
    },
  ]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const listRef = useRef<HTMLDivElement>(null);
  const projectId = useDesignStore((s) => s.projectId) ?? useProjectStore((s) => s.current?.project_id) ?? "demo-esp32-4l";

  // Auto-scroll vers le dernier message.
  useEffect(() => {
    const el = listRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages]);

  const send = async (raw: string) => {
    const text = raw.trim();
    if (!text || busy) return;
    setBusy(true);
    setInput("");
    const pendingId = newMsgId();
    setMessages((m) => [
      ...m,
      { id: newMsgId(), role: "user", text, ts: Date.now() / 1000 },
      { id: pendingId, role: "assistant", text: "…", ts: Date.now() / 1000, pending: true },
    ]);

    const res = await apiClient.runChatCommand(text, projectId ?? "");

    // Trace l'événement dans le flux d'activité des agents.
    useAgentStore.getState().appendEvent({
      id: newMsgId(),
      type: "chat.command",
      payload: { message: text, intent: res.intent, job_id: res.job_id },
      ts: Date.now() / 1000,
    });

    setMessages((m) =>
      m.map((msg) =>
        msg.id === pendingId
          ? {
              ...msg,
              pending: false,
              text: res.reply || (res.accepted ? "Commande acceptée." : "Commande refusée."),
              intent: res.intent || undefined,
              jobId: res.job_id || undefined,
              plan: res.plan_summary || undefined,
            }
          : msg,
      ),
    );
    setBusy(false);
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {/* Historique */}
      <div ref={listRef} className="min-h-0 flex-1 space-y-3 overflow-y-auto px-4 py-3">
        {messages.map((m) => (
          <div key={m.id} className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}>
            <div
              className={`max-w-[92%] rounded-xl px-3 py-2 text-sm leading-relaxed ${
                m.role === "user"
                  ? "bg-accent-cyan/15 text-ink"
                  : "border border-panel-border bg-panel-soft text-ink"
              } ${m.pending ? "animate-pulse text-ink-dim" : ""}`}
            >
              {m.pending ? "réflexion…" : m.text}
              {!m.pending && m.role === "assistant" && (m.intent || m.jobId) && (
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {m.intent && <Badge tone="violet">intent · {m.intent}</Badge>}
                  {m.jobId && <Badge tone="cyan">job · {m.jobId}</Badge>}
                </div>
              )}
              {!m.pending && m.plan && <p className="mt-1.5 text-[11px] text-ink-dim">plan : {m.plan}</p>}
            </div>
          </div>
        ))}
      </div>

      {/* Exemples cliquables */}
      <div className="shrink-0 border-t border-panel-border px-4 pt-2">
        <div className="flex flex-wrap gap-1.5">
          {EXAMPLES.map((ex) => (
            <button
              key={ex}
              type="button"
              onClick={() => void send(ex)}
              disabled={busy}
              className="rounded-full border border-panel-border bg-panel-soft px-2.5 py-1 text-[11px] text-ink-dim transition-colors hover:border-accent-cyan/40 hover:text-accent-cyan disabled:opacity-50"
              title={ex}
            >
              {ex.length > 44 ? `${ex.slice(0, 44)}…` : ex}
            </button>
          ))}
        </div>
      </div>

      {/* Input */}
      <form
        className="shrink-0 p-4"
        onSubmit={(e) => {
          e.preventDefault();
          void send(input);
        }}
      >
        <div className="flex gap-2">
          <input
            className="input"
            placeholder="Ex : carte STM32 2 couches, capteur I2C, budget 15 $…"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            disabled={busy}
          />
          <button type="submit" className="btn btn-primary shrink-0" disabled={busy || input.trim() === ""}>
            {busy ? "…" : "Envoyer"}
          </button>
        </div>
        <p className="mt-2 text-[11px] text-ink-dim">
          Projet : <span className="font-mono text-ink">{projectId}</span> — la commande lance le pipeline full_design en tâche de fond.
        </p>
      </form>
    </div>
  );
}
