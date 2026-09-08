/**
 * Types TS partagés du frontend — alignés sur shared/schemas/design_schemas.py
 * et les réponses de l'API Gateway (FastAPI). La source de vérité reste le
 * DesignGraph backend ; ces types en sont la représentation filaire.
 */

/** Point en millimètres (coordonnées carte, y vers le haut côté PCB). */
export interface Point {
  x: number;
  y: number;
}

/** Couche cuivre du stackup. */
export interface Layer {
  index: number;
  name: string;
  type: "signal" | "power" | "ground" | "mixed";
  thickness_um?: number;
  dielectric_thickness_um?: number;
  er?: number;
}

/** Pad d'empreinte (position relative au composant). */
export interface Pad {
  name: string;
  x_mm: number;
  y_mm: number;
  width_mm?: number;
  height_mm?: number;
  net_id?: string | null;
  layer?: number;
}

/** Composant placé sur la carte. */
export interface Component {
  ref: string; // "R1", "U3", "C12"
  value?: string;
  footprint?: string;
  mpn?: string;
  x_mm: number;
  y_mm: number;
  rotation_deg?: number;
  side: "top" | "bottom";
  bbox_mm: [number, number];
  pads?: Pad[];
  power_w?: number;
  price_usd?: number;
}

/** Net électrique — path/vias sont optionnels (renseignés si routé). */
export interface Net {
  net_id: string;
  name?: string;
  class_name?: string; // default | power | high_speed | differential | analog
  pins: [string, string][]; // (ref, pad)
  impedance_target_ohm?: number | null;
  max_length_mm?: number | null;
  matched_group?: string | null;
  routed: boolean;
  path?: Point[];
  vias?: Point[];
  layer?: number;
}

/** Design complet (snapshot filaire d'un projet). */
export interface DesignSchema {
  project_id: string;
  name: string;
  revision: number;
  board_size_mm: [number, number];
  layers: Layer[];
  components: Component[];
  nets: Net[];
  keepouts?: Record<string, unknown>[];
}

/** Projet (état ProjectState côté API). */
export interface Project {
  project_id: string;
  name: string;
  tenant_id?: string;
  user_id?: string;
  last_rev?: number;
  status?: string;
  created_ts?: number;
  updated_ts?: number;
  component_count?: number;
}

/** Événement agent normalisé depuis le WebSocket {type, payload, ts}. */
export interface AgentEvent {
  id: string;
  type: string;
  payload: Record<string, unknown>;
  ts: number;
}

/** Réponse de POST /api/v1/chat/commands. */
export interface ChatCommandResponse {
  accepted: boolean;
  intent: string;
  plan_summary: string;
  job_id: string;
  reply: string;
  project_id?: string;
  correlation_id?: string;
}

/** Type de simulation supporté. */
export type SimKind = "thermal" | "em" | "si" | "pi";

/** Résultat d'une simulation (metrics libres selon le kind). */
export interface SimResult {
  kind: SimKind;
  passed: boolean;
  skipped?: boolean;
  metrics: Record<string, unknown>;
  ts?: number;
  source: "api" | "mock";
}

/** Job du workflow (pipeline full_design / reoptimize). */
export interface Job {
  job_id: string;
  status: "queued" | "running" | "completed" | "failed";
  pipeline?: string;
  current_step?: string;
  completed_steps?: string[];
  progress?: number;
  started_ts?: number;
}

/** Score qualité ventilé par axe. */
export interface QualityScore {
  overall: number;
  drc: number;
  erc: number;
  dfm: number;
  routing: number;
  thermal: number;
  si: number;
  cost: number;
}

/** Contrainte active + état de violation. */
export interface ConstraintItem {
  id: string;
  name: string;
  kind: "clearance" | "trace_width" | "impedance" | "thermal" | "cost" | "keepout" | "other";
  target: string;
  severity: "error" | "warning" | "info";
  violated: boolean;
  detail?: string;
}

/** Itération d'optimisation (historique). */
export interface OptimizationIteration {
  iteration: number;
  score: number;
  ts?: number;
  note?: string;
}

/** Solde de crédits d'un tenant. */
export interface Credits {
  tenant: string;
  credits: number;
  free_tier: number;
  source: "api" | "mock";
}

/** Paramètres utilisateur (persistés en localStorage). */
export interface AppSettings {
  apiUrl: string;
  wsUrl: string;
  llmProvider: "mock" | "openai" | "zai";
  factory: "jlcpcb" | "pcbway";
  rlDevice: "cpu" | "cuda" | "auto";
}

/** Message de chat affiché dans le panneau. */
export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  text: string;
  intent?: string;
  jobId?: string;
  plan?: string;
  ts: number;
  pending?: boolean;
}
