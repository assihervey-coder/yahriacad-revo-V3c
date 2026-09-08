/**
 * Store agents — flux temps réel des événements (WebSocket) + état par rôle.
 *
 * Si le backend n'est pas joignable au moment du connect, une séquence mock
 * d'événements est jouée pour garder l'activité démontrable (graceful fallback).
 */
import { create } from "zustand";
import { liveSocket } from "@/services/websocket_live";
import type { AgentEvent } from "@/types";

/** État synthétique d'un agent (rôle). */
export interface AgentStatus {
  role: string;
  status: "running" | "done" | "failed";
  confidence: number;
  lastTs: number;
  lastEvent: string;
}

export interface AgentState {
  events: AgentEvent[];
  agents: Record<string, AgentStatus>;
  connected: boolean;
  appendEvent: (e: AgentEvent) => void;
  setAgentStatus: (role: string, status: AgentStatus["status"], confidence?: number, lastEvent?: string) => void;
  setConnected: (v: boolean) => void;
  clear: () => void;
  connectLive: (projectId: string) => void;
  disconnectLive: () => void;
}

const MAX_EVENTS = 60;
/** Délai avant de conclure que le WS est indisponible → séquence mock. */
const MOCK_SEED_DELAY_MS = 2000;

let unsubEvents: (() => void) | null = null;
let unsubState: (() => void) | null = null;
let mockTimers: ReturnType<typeof setTimeout>[] = [];

/** WS URL personnalisée depuis les Paramètres (localStorage, côté client). */
function readStoredWsUrl(): string | undefined {
  if (typeof window === "undefined") return undefined;
  try {
    const raw = window.localStorage.getItem("pcb3.settings");
    if (!raw) return undefined;
    const parsed = JSON.parse(raw) as { wsUrl?: string };
    return parsed.wsUrl || undefined;
  } catch {
    return undefined;
  }
}

/** Déduit le rôle d'agent depuis l'événement (payload.role prioritaire). */
export function roleFromEvent(e: AgentEvent): string {
  const p = e.payload;
  const role = p.role ?? p.agent ?? p.agent_role;
  if (typeof role === "string" && role.length > 0) return role;
  if (e.type.startsWith("intent.") || e.type.startsWith("chat.")) return "planner";
  if (e.type.startsWith("components.") || e.type.startsWith("import.") || e.type.startsWith("skidl.")) return "selector";
  if (e.type.startsWith("placement.")) return "placement";
  if (e.type.startsWith("routing.")) return "routing";
  if (e.type.startsWith("verification.") || e.type.startsWith("rollback.") || e.type.startsWith("drc.")) return "corrector";
  if (e.type.startsWith("simulation.")) return "simulator";
  if (e.type.startsWith("optimization.")) return "optimizer";
  if (e.type.startsWith("export.") || e.type.startsWith("manufacturing.")) return "exporter";
  if (e.type.startsWith("constraint.")) return "constraints";
  if (e.type.startsWith("design.")) return "design_core";
  return "system";
}

/** Statut d'agent déduit du type d'événement. */
export function statusFromEvent(e: AgentEvent): AgentStatus["status"] {
  if (e.type.includes("failed") || e.type.includes("violated") || e.type.includes("escalation")) return "failed";
  if (e.type.includes("assigned") || e.type.includes("started")) return "running";
  return "done";
}

function confidenceOf(e: AgentEvent): number | undefined {
  const c = e.payload.confidence;
  return typeof c === "number" ? c : undefined;
}

/** Séquence mock d'activité — joue un pipeline complet en ~9 s. */
function seedMockActivity(set: (partial: Partial<AgentState>) => void): void {
  const push = (delayMs: number, type: string, role: string, status: AgentStatus["status"], confidence: number): void => {
    mockTimers.push(
      setTimeout(() => {
        const event: AgentEvent = {
          id: `mock-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 7)}`,
          type,
          payload: { role, confidence, source: "mock" },
          ts: Date.now() / 1000,
        };
        useAgentStore.getState().appendEvent(event);
        set({});
      }, delayMs),
    );
  };
  push(300, "intent.captured", "planner", "running", 0.5);
  push(1500, "agent.task.completed", "planner", "done", 0.91);
  push(2900, "agent.task.assigned", "researcher", "running", 0.5);
  push(4400, "agent.task.completed", "researcher", "done", 0.84);
  push(5600, "components.selected", "selector", "done", 0.9);
  push(6800, "placement.proposed", "placement", "done", 0.87);
  push(8000, "routing.proposed", "routing", "done", 0.93);
  push(9200, "verification.passed", "corrector", "done", 0.96);
}

export const useAgentStore = create<AgentState>((set) => ({
  events: [],
  agents: {},
  connected: false,

  appendEvent: (e) => {
    const role = roleFromEvent(e);
    set((s) => {
      const agents = { ...s.agents };
      const conf = confidenceOf(e);
      agents[role] = {
        role,
        status: statusFromEvent(e),
        confidence: conf ?? agents[role]?.confidence ?? 0.5,
        lastTs: e.ts,
        lastEvent: e.type,
      };
      return { events: [e, ...s.events].slice(0, MAX_EVENTS), agents };
    });
  },

  setAgentStatus: (role, status, confidence, lastEvent) =>
    set((s) => ({
      agents: {
        ...s.agents,
        [role]: {
          role,
          status,
          confidence: confidence ?? s.agents[role]?.confidence ?? 0.5,
          lastTs: Date.now() / 1000,
          lastEvent: lastEvent ?? s.agents[role]?.lastEvent ?? "",
        },
      },
    })),

  setConnected: (v) => set({ connected: v }),

  clear: () => set({ events: [], agents: {} }),

  connectLive: (projectId) => {
    // nettoyage d'une session précédente
    unsubEvents?.();
    unsubState?.();
    mockTimers.forEach(clearTimeout);
    mockTimers = [];
    set({ events: [], agents: {}, connected: false });

    unsubEvents = liveSocket.on((e) => useAgentStore.getState().appendEvent(e));
    unsubState = liveSocket.onStateChange((v) => useAgentStore.getState().setConnected(v));
    liveSocket.connect(projectId, readStoredWsUrl());

    // Graceful fallback : WS injoignable → séquence mock après 2 s.
    const t = setTimeout(() => {
      if (!liveSocket.isOpen()) {
        seedMockActivity(set);
      }
    }, MOCK_SEED_DELAY_MS);
    mockTimers.push(t);
  },

  disconnectLive: () => {
    unsubEvents?.();
    unsubState?.();
    unsubEvents = null;
    unsubState = null;
    mockTimers.forEach(clearTimeout);
    mockTimers = [];
    liveSocket.close();
    set({ connected: false });
  },
}));

/** Sélecteur : nombre d'agents en cours d'exécution. */
export function selectActiveCount(s: AgentState): number {
  return Object.values(s.agents).filter((a) => a.status === "running").length;
}

/** Sélecteur : liste d'états d'agents triée par activité récente. */
export function selectAgentList(s: AgentState): AgentStatus[] {
  return Object.values(s.agents).sort((a, b) => b.lastTs - a.lastTs);
}
