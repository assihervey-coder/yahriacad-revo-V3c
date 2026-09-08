/**
 * LiveSocket — WebSocket temps réel vers /ws/{project_id} (API Gateway).
 *
 * - reconnexion automatique avec backoff exponentiel 1s → 8s,
 * - heartbeat "ping" toutes les 25s (le serveur répond {type:"pong"}),
 * - normalisation des messages {type, payload, ts} en AgentEvent typé.
 */
import type { AgentEvent } from "@/types";

export type AgentEventHandler = (event: AgentEvent) => void;
export type StateHandler = (connected: boolean) => void;

const DEFAULT_WS_URL = process.env.NEXT_PUBLIC_WS_URL || "ws://localhost:8000";
const HEARTBEAT_MS = 25_000;
const MAX_BACKOFF_MS = 8_000;
/** Types de messages serveur non diffusés au store. */
const IGNORED_TYPES = new Set(["ping", "pong"]);

let seq = 0;

export class LiveSocket {
  private ws: WebSocket | null = null;
  private projectId = "";
  private attempt = 0;
  private closedByUser = false;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private heartbeatTimer: ReturnType<typeof setInterval> | null = null;
  private eventHandlers = new Set<AgentEventHandler>();
  private stateHandlers = new Set<StateHandler>();
  private lastEvents = new Map<string, number>();

  /** Ouvre (ou rouvre) la connexion pour un projet donné. */
  connect(projectId: string, wsUrl?: string): void {
    this.close();
    this.projectId = projectId;
    this.closedByUser = false;
    this.attempt = 0;
    this.open(wsUrl);
  }

  private open(wsUrl?: string): void {
    if (typeof window === "undefined" || !this.projectId) return;
    const base = (wsUrl || process.env.NEXT_PUBLIC_WS_URL || DEFAULT_WS_URL).replace(/\/+$/, "");
    let ws: WebSocket;
    try {
      ws = new WebSocket(`${base}/ws/${encodeURIComponent(this.projectId)}`);
    } catch {
      this.scheduleReconnect(wsUrl);
      return;
    }
    this.ws = ws;

    ws.onopen = () => {
      this.attempt = 0;
      this.setConnected(true);
      this.startHeartbeat();
    };

    ws.onmessage = (raw: MessageEvent) => {
      const evt = parseEvent(raw.data);
      if (evt) this.emit(evt);
    };

    ws.onerror = () => {
      ws.close();
    };

    ws.onclose = () => {
      this.stopHeartbeat();
      this.setConnected(false);
      if (!this.closedByUser) this.scheduleReconnect(wsUrl);
    };
  }

  private emit(evt: AgentEvent): void {
    // Anti-doublon : certains bus rediffusent des events à l'identique.
    const key = `${evt.type}:${evt.ts}`;
    if ((this.lastEvents.get(key) ?? 0) + 50 > Date.now()) return;
    this.lastEvents.set(key, Date.now());
    for (const h of this.eventHandlers) {
      try {
        h(evt);
      } catch {
        // un handler défaillant ne casse jamais la boucle live
      }
    }
  }

  private setConnected(v: boolean): void {
    for (const h of this.stateHandlers) h(v);
  }

  private scheduleReconnect(wsUrl?: string): void {
    if (this.reconnectTimer) return;
    const delay = Math.min(MAX_BACKOFF_MS, 1000 * 2 ** this.attempt);
    this.attempt += 1;
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.open(wsUrl);
    }, delay);
  }

  private startHeartbeat(): void {
    this.stopHeartbeat();
    this.heartbeatTimer = setInterval(() => {
      if (this.ws?.readyState === WebSocket.OPEN) {
        try {
          this.ws.send("ping");
        } catch {
          // socket en cours de fermeture — la reconnexion gèrera
        }
      }
    }, HEARTBEAT_MS);
  }

  private stopHeartbeat(): void {
    if (this.heartbeatTimer) {
      clearInterval(this.heartbeatTimer);
      this.heartbeatTimer = null;
    }
  }

  /** Abonne un handler d'événements — retourne la fonction de désabonnement. */
  on(handler: AgentEventHandler): () => void {
    this.eventHandlers.add(handler);
    return () => this.eventHandlers.delete(handler);
  }

  /** Abonne un handler d'état connexion/déconnexion. */
  onStateChange(handler: StateHandler): () => void {
    this.stateHandlers.add(handler);
    return () => this.stateHandlers.delete(handler);
  }

  isOpen(): boolean {
    return this.ws?.readyState === WebSocket.OPEN;
  }

  /** Ferme proprement (sans reconnexion). */
  close(): void {
    this.closedByUser = true;
    this.stopHeartbeat();
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    if (this.ws) {
      try {
        this.ws.close();
      } catch {
        // déjà fermée
      }
      this.ws = null;
    }
  }
}

/** Parse un message WS brut en AgentEvent (null si keepalive/mal formé). */
function parseEvent(data: unknown): AgentEvent | null {
  if (typeof data !== "string" || data.trim() === "") return null;
  try {
    const obj = JSON.parse(data) as { type?: unknown; payload?: unknown; ts?: unknown };
    if (typeof obj.type !== "string") return null;
    if (IGNORED_TYPES.has(obj.type)) return null;
    seq += 1;
    return {
      id: `evt-${Date.now().toString(36)}-${seq}`,
      type: obj.type,
      payload: (obj.payload && typeof obj.payload === "object" ? obj.payload : {}) as Record<string, unknown>,
      ts: typeof obj.ts === "number" ? obj.ts : Date.now() / 1000,
    };
  } catch {
    return null;
  }
}

/** Singleton partagé (un seul socket pour toute l'app). */
export const liveSocket = new LiveSocket();
