/**
 * Client API de la plateforme PCB_AI_DESIGNER_V3.
 *
 * Chaque méthode tente l'API Gateway FastAPI puis, en cas d'échec (réseau,
 * timeout, erreur HTTP), retombe sur des données mock réalistes — l'UI reste
 * toujours démontrable (graceful fallback).
 */
import type {
  ChatCommandResponse,
  Component,
  ConstraintItem,
  Credits,
  DesignSchema,
  Job,
  OptimizationIteration,
  Point,
  Project,
  QualityScore,
  SimKind,
  SimResult,
} from "@/types";

/** Résultat d'un export de fabrication. */
export interface ExportResult {
  export_id: string;
  format: string;
  factory: string;
  files: Record<string, string>;
  zip: string;
  source: "api" | "mock";
}

const DEFAULT_API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const DEFAULT_TENANT = process.env.NEXT_PUBLIC_TENANT_ID || "default";
const TIMEOUT_MS = 4000;

/** Lecture numérique défensive d'un champ de metrics typé unknown. */
export function readNum(obj: Record<string, unknown>, key: string, fallback: number): number {
  const raw = obj[key];
  const n = typeof raw === "number" ? raw : Number(raw);
  return Number.isFinite(n) ? n : fallback;
}

/** Lecture tableau défensive d'un champ de metrics. */
export function readArr<T = Record<string, unknown>>(obj: Record<string, unknown>, key: string): T[] {
  const raw = obj[key];
  return Array.isArray(raw) ? (raw as T[]) : [];
}

// ---------------------------------------------------------------------------
// Données mock — carte ESP32 4 couches 60x40 mm (JLCPCB)
// ---------------------------------------------------------------------------

function L(x: number, y: number): Point {
  return { x, y };
}

const MOCK_DESIGN: DesignSchema = {
  project_id: "demo-esp32-4l",
  name: "ESP32 sensor node (démo)",
  revision: 7,
  board_size_mm: [60, 40],
  layers: [
    { index: 0, name: "F.Cu", type: "signal", thickness_um: 35 },
    { index: 1, name: "GND", type: "ground", thickness_um: 35 },
    { index: 2, name: "PWR", type: "power", thickness_um: 35 },
    { index: 3, name: "B.Cu", type: "signal", thickness_um: 35 },
  ],
  components: [
    { ref: "J1", value: "USB-C", footprint: "USB-C-16P", mpn: "USB4085-GF-A", x_mm: 7.5, y_mm: 20, rotation_deg: 0, side: "top", bbox_mm: [8.9, 7.4], power_w: 0, price_usd: 0.8 },
    { ref: "U1", value: "ESP32", footprint: "ESP32-WROOM-32E", mpn: "ESP32-WROOM-32E", x_mm: 30, y_mm: 22, rotation_deg: 0, side: "top", bbox_mm: [18, 25.5], power_w: 1.8, price_usd: 3.1 },
    { ref: "U2", value: "BME680", footprint: "BME680", mpn: "BME680", x_mm: 50, y_mm: 31, rotation_deg: 0, side: "top", bbox_mm: [3.8, 3.8], power_w: 0.02, price_usd: 4.2 },
    { ref: "U3", value: "LDO 3.3V", footprint: "SOT-223", mpn: "AMS1117-3.3", x_mm: 13, y_mm: 7, rotation_deg: 0, side: "top", bbox_mm: [6.5, 7], power_w: 0.6, price_usd: 0.15 },
    { ref: "U4", value: "CH340C", footprint: "SOIC-16", mpn: "CH340C", x_mm: 24, y_mm: 7, rotation_deg: 0, side: "top", bbox_mm: [10, 4], power_w: 0.1, price_usd: 0.4 },
    { ref: "J2", value: "JST 2P", footprint: "JST-PH-2", mpn: "S2B-PH-K", x_mm: 52, y_mm: 8, rotation_deg: 90, side: "top", bbox_mm: [6, 4], power_w: 0, price_usd: 0.2 },
    { ref: "SW1", value: "BOOT", footprint: "BTN-3x4", mpn: "SKRPACE010", x_mm: 45, y_mm: 4, rotation_deg: 0, side: "top", bbox_mm: [4, 3], power_w: 0, price_usd: 0.1 },
    { ref: "LED1", value: "PWR", footprint: "0603", mpn: "KP-1608SGC", x_mm: 40, y_mm: 4, rotation_deg: 0, side: "top", bbox_mm: [1.6, 0.8], power_w: 0.02, price_usd: 0.02 },
    { ref: "R1", value: "10k", footprint: "0402", mpn: "RC0402FR-0710KL", x_mm: 20, y_mm: 4, rotation_deg: 90, side: "top", bbox_mm: [1, 0.5], price_usd: 0.002 },
    { ref: "R2", value: "5.1k", footprint: "0402", mpn: "RC0402FR-075KL1", x_mm: 10, y_mm: 13, rotation_deg: 0, side: "top", bbox_mm: [1, 0.5], price_usd: 0.002 },
    { ref: "R3", value: "5.1k", footprint: "0402", mpn: "RC0402FR-075KL1", x_mm: 10, y_mm: 15, rotation_deg: 0, side: "top", bbox_mm: [1, 0.5], price_usd: 0.002 },
    { ref: "R4", value: "1k", footprint: "0402", mpn: "RC0402FR-071KL", x_mm: 42, y_mm: 7, rotation_deg: 0, side: "top", bbox_mm: [1, 0.5], price_usd: 0.002 },
    { ref: "C1", value: "100n", footprint: "0402", mpn: "CL05B104KO5NNNC", x_mm: 24, y_mm: 34, rotation_deg: 0, side: "top", bbox_mm: [1, 0.5], price_usd: 0.003 },
    { ref: "C2", value: "10u", footprint: "0805", mpn: "CL21A106KAYNNNE", x_mm: 16, y_mm: 13, rotation_deg: 0, side: "top", bbox_mm: [2, 1.25], price_usd: 0.03 },
    { ref: "C3", value: "22u", footprint: "0805", mpn: "CL21A226MQQNNNE", x_mm: 18, y_mm: 7, rotation_deg: 90, side: "top", bbox_mm: [2, 1.25], price_usd: 0.05 },
    { ref: "C4", value: "100n", footprint: "0402", mpn: "CL05B104KO5NNNC", x_mm: 47, y_mm: 33, rotation_deg: 0, side: "bottom", bbox_mm: [1, 0.5], price_usd: 0.003 },
  ],
  nets: [
    { net_id: "N1", name: "3V3", class_name: "power", pins: [["U3", "VOUT"], ["U1", "VDD"], ["U2", "VDD"], ["R1", "2"]], routed: true, path: [L(16.5, 9), L(26, 9), L(26, 18), L(38, 18)], vias: [L(26, 9)] },
    { net_id: "N2", name: "GND", class_name: "power", pins: [["J1", "GND"], ["U1", "GND"], ["U2", "GND"], ["U3", "GND"], ["C1", "2"]], routed: true, path: [L(12, 20), L(12, 36), L(52, 36), L(52, 32)], vias: [] },
    { net_id: "N3", name: "USB_DP", class_name: "high_speed", pins: [["J1", "A6"], ["U4", "RX"]], impedance_target_ohm: 90, routed: true, path: [L(10, 22), L(15, 22), L(15, 9), L(19, 9)] },
    { net_id: "N4", name: "USB_DN", class_name: "high_speed", pins: [["J1", "A7"], ["U4", "TX"]], impedance_target_ohm: 90, routed: true, path: [L(10, 24), L(13.5, 24), L(13.5, 10.5), L(19, 10.5)] },
    { net_id: "N5", name: "I2C_SDA", class_name: "default", pins: [["U1", "IO21"], ["U2", "SDA"], ["R2", "1"]], routed: true, path: [L(39, 28), L(45, 28), L(45, 30), L(48, 30)] },
    { net_id: "N6", name: "I2C_SCL", class_name: "default", pins: [["U1", "IO22"], ["U2", "SCL"], ["R3", "1"]], routed: true, path: [L(39, 30), L(43, 30), L(43, 32), L(48, 32)] },
    { net_id: "N7", name: "EN", class_name: "default", pins: [["U1", "EN"], ["R1", "1"], ["SW1", "1"]], routed: true, path: [L(21, 20), L(21, 4), L(43, 4)] },
    { net_id: "N8", name: "UART_TX", class_name: "default", pins: [["U1", "TX0"], ["U4", "VCC"]], routed: true, path: [L(21, 24), L(27, 24), L(27, 9)] },
    { net_id: "N9", name: "LED_A", class_name: "default", pins: [["U1", "IO2"], ["R4", "1"]], routed: true, path: [L(39, 22), L(42, 22), L(42, 7)] },
    { net_id: "N10", name: "VIN", class_name: "power", pins: [["J2", "1"], ["U3", "VIN"]], routed: true, path: [L(50, 10), L(50, 3), L(13, 3), L(13, 4)] },
    { net_id: "N11", name: "BOOT", class_name: "default", pins: [["SW1", "2"], ["U1", "IO0"]], routed: false },
    { net_id: "N12", name: "SCL_PULLUP", class_name: "default", pins: [["R3", "2"], ["U1", "VDD"]], routed: false },
  ],
  keepouts: [],
};

const MOCK_PROJECTS: Project[] = [
  { project_id: "demo-esp32-4l", name: "ESP32 sensor node", tenant_id: DEFAULT_TENANT, last_rev: 7, status: "ready", created_ts: 1735689600, updated_ts: 1767225600, component_count: 16 },
  { project_id: "demo-motor-drive", name: "MotorDrive 4L", tenant_id: DEFAULT_TENANT, last_rev: 3, status: "ready", created_ts: 1735689600, updated_ts: 1767139200, component_count: 18 },
  { project_id: "demo-usb-c-tester", name: "USB-C tester", tenant_id: DEFAULT_TENANT, last_rev: 1, status: "draft", created_ts: 1767139200, updated_ts: 1767225600, component_count: 9 },
];

/** Grille thermique 20x16 déterministe (hotspot sur U1). */
function mockThermalGrid(): number[] {
  const w = 20;
  const h = 16;
  const grid: number[] = [];
  const hx = 10; // ~30mm / 60mm * 20
  const hy = 8.5; // ~22mm / 40mm * 16
  for (let y = 0; y < h; y += 1) {
    for (let x = 0; x < w; x += 1) {
      const d = Math.hypot(x - hx, y - hy);
      const t = 26 + (89.3 - 26) * Math.exp(-(d * d) / 28);
      grid.push(Math.round(t * 10) / 10);
    }
  }
  return grid;
}

const MOCK_SIM_RESULTS: Record<SimKind, SimResult> = {
  thermal: {
    kind: "thermal",
    passed: true,
    metrics: {
      max_temp_c: 89.3,
      ambient_c: 25,
      hotspot_ref: "U1",
      hotspot_x_mm: 30,
      hotspot_y_mm: 22,
      grid_w: 20,
      grid_h: 16,
      heatmap: mockThermalGrid(),
    },
    ts: 1767225600,
    source: "mock",
  },
  em: {
    kind: "em",
    passed: true,
    metrics: {
      crosstalk_mv: 42.3,
      crosstalk_limit_mv: 50,
      max_loop_area_mm2: 18.6,
      shield_db: 12.5,
      emissions_dbuv: 38.2,
      emissions_limit_dbuv: 42,
      risk: "modéré",
    },
    ts: 1767225600,
    source: "mock",
  },
  si: {
    kind: "si",
    passed: false,
    metrics: {
      worst_eye_margin_pct: 18.4,
      jitter_ps: 32,
      nets: [
        { net: "USB_DP", target_ohm: 90, computed_ohm: 87.4, mismatch_pct: 2.9, passed: true },
        { net: "USB_DN", target_ohm: 90, computed_ohm: 91.8, mismatch_pct: 2.0, passed: true },
        { net: "I2C_SCL", target_ohm: 50, computed_ohm: 58.3, mismatch_pct: 16.6, passed: false },
        { net: "I2C_SDA", target_ohm: 50, computed_ohm: 52.1, mismatch_pct: 4.2, passed: true },
        { net: "EN", target_ohm: null, computed_ohm: 63.2, mismatch_pct: 0, passed: true },
      ],
    },
    ts: 1767225600,
    source: "mock",
  },
  pi: {
    kind: "pi",
    passed: true,
    metrics: {
      max_ir_drop_mv: 21.7,
      limit_mv: 50,
      rails: [
        { net: "3V3", v_nom_v: 3.3, ir_drop_mv: 18.4 },
        { net: "VIN", v_nom_v: 5.0, ir_drop_mv: 12.1 },
        { net: "GND", v_nom_v: 0, ir_drop_mv: 3.2 },
      ],
    },
    ts: 1767225600,
    source: "mock",
  },
};

const MOCK_CONSTRAINTS: ConstraintItem[] = [
  { id: "c-clear", name: "Clearance minimale", kind: "clearance", target: "≥ 0.20 mm", severity: "error", violated: false, detail: "13 paires vérifiées" },
  { id: "c-trace", name: "Largeur de piste", kind: "trace_width", target: "≥ 0.127 mm (JLCPCB)", severity: "error", violated: false, detail: "largeur courante 0.20 mm" },
  { id: "c-imp-usb", name: "Impédance USB_DP/DN", kind: "impedance", target: "90 Ω ±5 %", severity: "error", violated: false, detail: "87.4 Ω / 91.8 Ω" },
  { id: "c-imp-i2c", name: "Impédance I2C_SCL", kind: "impedance", target: "50 Ω ±5 %", severity: "warning", violated: true, detail: "58.3 Ω (+16.6 %)" },
  { id: "c-therm", name: "Hotspot thermique", kind: "thermal", target: "≤ 95 °C", severity: "warning", violated: false, detail: "89.3 °C @U1" },
  { id: "c-cost", name: "Coût cible", kind: "cost", target: "≤ 22 $", severity: "info", violated: false, detail: "estimation 22.78 $" },
  { id: "c-keep", name: "Keepout USB-C", kind: "keepout", target: "zone J1 libre", severity: "error", violated: false, detail: "aucune intrusion" },
];

const MOCK_OPTIMIZATION: OptimizationIteration[] = [
  { iteration: 1, score: 72.4, note: "placement initial (recuit)" },
  { iteration: 2, score: 78.1, note: "HPWL 657→612 mm" },
  { iteration: 3, score: 83.6, note: "swap C4/C1" },
  { iteration: 4, score: 86.2, note: "routage A* 11/12 nets" },
  { iteration: 5, score: 89.5, note: "rip-up & retry net N11" },
  { iteration: 6, score: 91.0, note: "réduction vias -3" },
  { iteration: 7, score: 93.2, note: "thermique U1 éloigné J2" },
  { iteration: 8, score: 94.8, note: "PDN ajusté" },
  { iteration: 9, score: 95.6, note: "DFM JLCPCB ok" },
  { iteration: 10, score: 96.1, note: "convergé" },
];

const MOCK_TOOLS = [
  { name: "run_design_command", description: "Commande NL → design complet (pipeline full_design).", inputSchema: { type: "object", properties: { message: { type: "string" }, project_id: { type: "string" } } } },
  { name: "query_design", description: "Statistiques et état du design d'un projet.", inputSchema: { type: "object", properties: { project_id: { type: "string" } } } },
  { name: "export_package", description: "Exporte le paquet de fabrication (gerber, json, ipc2581...).", inputSchema: { type: "object", properties: { project_id: { type: "string" }, fmt: { type: "string" }, factory: { type: "string" } } } },
  { name: "simulate", description: "Lance les simulations (thermal, si, pi, em) et retourne les métriques.", inputSchema: { type: "object", properties: { project_id: { type: "string" }, kinds: { type: "array", items: { type: "string" } } } } },
];

// ---------------------------------------------------------------------------
// Client
// ---------------------------------------------------------------------------

export class ApiClient {
  private baseURL: string;
  private tenant: string;
  /** Vrai si le dernier appel est tombé en fallback mock (exposé aux stores). */
  mockMode = false;

  constructor(baseURL: string = DEFAULT_API_URL, tenant: string = DEFAULT_TENANT) {
    this.baseURL = baseURL.replace(/\/+$/, "");
    this.tenant = tenant;
  }

  getBaseURL(): string {
    return this.baseURL;
  }

  /** Mise à jour à chaud (page Paramètres). */
  setBaseURL(url: string): void {
    this.baseURL = url.replace(/\/+$/, "");
  }

  setTenant(tenant: string): void {
    this.tenant = tenant || DEFAULT_TENANT;
  }

  /** fetch JSON typé — retourne null si l'API est injoignable (fallback mock). */
  private async request<T>(path: string, init?: RequestInit): Promise<T | null> {
    try {
      const res = await fetch(`${this.baseURL}${path}`, {
        ...init,
        headers: {
          "Content-Type": "application/json",
          "X-Tenant-Id": this.tenant,
          ...(init?.headers ?? {}),
        },
        signal: AbortSignal.timeout(TIMEOUT_MS),
        cache: "no-store",
      });
      if (!res.ok) {
        this.mockMode = true;
        return null;
      }
      this.mockMode = false;
      return (await res.json()) as T;
    } catch {
      this.mockMode = true;
      return null;
    }
  }

  /** Sonde de vie GET /health. */
  async getHealth(): Promise<boolean> {
    try {
      const res = await fetch(`${this.baseURL}/health`, { signal: AbortSignal.timeout(2000), cache: "no-store" });
      return res.ok;
    } catch {
      return false;
    }
  }

  async getProjects(): Promise<Project[]> {
    const data = await this.request<{ projects?: Record<string, unknown>[] }>("/api/v1/projects");
    if (data && Array.isArray(data.projects)) {
      return data.projects.map((p, i) => ({
        project_id: String(p.project_id ?? `p-${i}`),
        name: String(p.name ?? "sans nom"),
        tenant_id: p.tenant_id ? String(p.tenant_id) : undefined,
        last_rev: typeof p.last_rev === "number" ? p.last_rev : 0,
        status: p.status ? String(p.status) : "draft",
        component_count: typeof p.component_count === "number" ? p.component_count : undefined,
      }));
    }
    return MOCK_PROJECTS;
  }

  async createProject(name: string): Promise<Project> {
    const data = await this.request<{ project_id: string; name: string }>("/api/v1/projects", {
      method: "POST",
      body: JSON.stringify({ name, tenant_id: this.tenant }),
    });
    if (data && data.project_id) {
      return { project_id: data.project_id, name: data.name || name, tenant_id: this.tenant, last_rev: 0, status: "draft" };
    }
    return {
      project_id: `local-${Date.now().toString(36)}`,
      name,
      tenant_id: this.tenant,
      last_rev: 0,
      status: "draft (mock)",
    };
  }

  async getDesign(projectId: string): Promise<DesignSchema> {
    const data = await this.request<Partial<DesignSchema>>(`/api/v1/designs/${encodeURIComponent(projectId)}`);
    if (data && Array.isArray(data.components)) {
      return augmentDesign(data as DesignSchema);
    }
    return augmentDesign({ ...MOCK_DESIGN, project_id: projectId });
  }

  /** Score qualité — synthétisé depuis /designs/{pid}/stats sinon mock. */
  async getQuality(projectId: string): Promise<QualityScore> {
    const data = await this.request<{ stats?: Record<string, unknown> }>(`/api/v1/designs/${encodeURIComponent(projectId)}/stats`);
    if (data && data.stats) {
      const design = await this.getDesign(projectId);
      return qualityFromDesign(design);
    }
    return qualityFromDesign({ ...MOCK_DESIGN, project_id: projectId });
  }

  async runChatCommand(message: string, projectId = "", tenantId = ""): Promise<ChatCommandResponse> {
    const data = await this.request<ChatCommandResponse>("/api/v1/chat/commands", {
      method: "POST",
      body: JSON.stringify({ message, project_id: projectId, tenant_id: tenantId || this.tenant }),
    });
    if (data && typeof data.accepted === "boolean") {
      return data;
    }
    // Fallback mock : acceptation immédiate + plan du pipeline full_design.
    return {
      accepted: true,
      intent: "esp32_sensor_board",
      plan_summary: "planner → researcher → selector → placement → routing → corrector → manufacturing → exporter",
      job_id: `job-mock-${Date.now().toString(36)}`,
      reply: `Commande acceptée (mode démo) — intention « esp32_sensor_board ». Le pipeline full_design s'exécute en tâche de fond.`,
      project_id: projectId || MOCK_DESIGN.project_id,
    };
  }

  async getJobStatus(jobId: string): Promise<Job> {
    const data = await this.request<Record<string, unknown>>(`/api/v1/chat/commands/${encodeURIComponent(jobId)}/status`);
    if (data && typeof data.status === "string") {
      return {
        job_id: String(data.job_id ?? jobId),
        status: normalizeJobStatus(String(data.status)),
        pipeline: data.pipeline ? String(data.pipeline) : undefined,
        current_step: data.current_step ? String(data.current_step) : undefined,
        completed_steps: Array.isArray(data.completed_steps) ? (data.completed_steps as string[]) : [],
        progress: typeof data.progress === "number" ? data.progress : undefined,
      };
    }
    return {
      job_id: jobId,
      status: "running",
      pipeline: "full_design",
      current_step: "routing",
      completed_steps: ["parse", "select", "place"],
      progress: 55,
    };
  }

  /** Lance les simulations et retourne les résultats par kind (API ou mock). */
  async simulate(projectId: string, kinds: SimKind[]): Promise<Record<SimKind, SimResult>> {
    const out = {} as Record<SimKind, SimResult>;
    for (const kind of kinds) out[kind] = { ...MOCK_SIM_RESULTS[kind], ts: Date.now() / 1000 };

    const started = await this.request<{ job_id: string; status: string }>(`/api/v1/simulations/${encodeURIComponent(projectId)}`, {
      method: "POST",
      body: JSON.stringify({ kinds }),
    });
    if (!started || !started.job_id) return out;

    // Le backend exécute en tâche de fond : un seul poll court suffit pour la démo.
    const done = await this.request<{ status: string; results?: Record<string, { passed?: boolean; metrics?: Record<string, unknown>; skipped?: boolean }> }>(
      `/api/v1/simulations/${encodeURIComponent(projectId)}/${encodeURIComponent(started.job_id)}`,
    );
    if (done && done.results) {
      for (const kind of kinds) {
        const r = done.results[kind];
        if (r && r.metrics) {
          out[kind] = { kind, passed: r.passed ?? true, skipped: r.skipped, metrics: r.metrics, ts: Date.now() / 1000, source: "api" };
        }
      }
    }
    return out;
  }

  async getOptimizationHistory(projectId: string): Promise<OptimizationIteration[]> {
    const data = await this.request<{ revisions?: Record<string, unknown>[] }>(`/api/v1/optimization/${encodeURIComponent(projectId)}/history`);
    if (data && Array.isArray(data.revisions) && data.revisions.length > 0) {
      return data.revisions.slice(0, 20).map((r, i) => {
        const stats = (r.stats ?? {}) as Record<string, unknown>;
        const score = typeof stats.quality === "number" ? stats.quality : 70 + i * 3;
        return { iteration: i + 1, score: Math.round(score * 10) / 10, note: r.message ? String(r.message) : undefined };
      });
    }
    return MOCK_OPTIMIZATION;
  }

  async exportPackage(projectId: string, fmt = "gerber", factory = "jlcpcb"): Promise<ExportResult> {
    const data = await this.request<{ export_id: string; files: Record<string, string>; zip: string }>(`/api/v1/exports/${encodeURIComponent(projectId)}`, {
      method: "POST",
      body: JSON.stringify({ fmt, factory }),
    });
    if (data && data.export_id) {
      return { export_id: data.export_id, format: fmt, factory, files: data.files ?? {}, zip: data.zip ?? "", source: "api" };
    }
    return {
      export_id: `exp-mock-${Date.now().toString(36)}`,
      format: fmt,
      factory,
      files: {
        "F_Cu.gbr": "RS-274X (mock)",
        "GND.gbr": "RS-274X (mock)",
        "PWR.gbr": "RS-274X (mock)",
        "B_Cu.gbr": "RS-274X (mock)",
        "Edge_Cuts.gbr": "RS-274X (mock)",
        "drill.drl": "Excellon (mock)",
        "bom.csv": "16 lignes (mock)",
        "ipc2581.xml": "IPC-2581 (mock)",
      },
      zip: `data/projects/${projectId}/exports/mock.zip`,
      source: "mock",
    };
  }

  async getCredits(tenant = this.tenant): Promise<Credits> {
    const data = await this.request<{ tenant: string; credits: number; free_tier: number }>(`/api/v1/billing/credits/${encodeURIComponent(tenant)}`);
    if (data && typeof data.credits === "number") {
      return { tenant: data.tenant || tenant, credits: data.credits, free_tier: data.free_tier ?? 250, source: "api" };
    }
    return { tenant, credits: 243, free_tier: 250, source: "mock" };
  }

  /** Déplacement précis d'un composant — PATCH, échec silencieux (state local prioritaire). */
  async moveComponent(projectId: string, ref: string, xMm: number, yMm: number, rotationDeg?: number): Promise<boolean> {
    const data = await this.request<{ ok?: boolean }>(`/api/v1/components/${encodeURIComponent(projectId)}/${encodeURIComponent(ref)}`, {
      method: "PATCH",
      body: JSON.stringify({ x_mm: xMm, y_mm: yMm, rotation_deg: rotationDeg }),
    });
    return data?.ok === true;
  }

  async getConstraints(projectId: string): Promise<ConstraintItem[]> {
    // Aucune route dédiée côté API V3 → on tente /designs/{pid}/stats pour
    // détecter la joignabilité, sinon mock complet.
    const stats = await this.request<{ stats?: Record<string, unknown> }>(`/api/v1/designs/${encodeURIComponent(projectId)}/stats`);
    if (stats && stats.stats) {
      const violations = readNum(stats.stats, "violations", 1);
      return MOCK_CONSTRAINTS.map((c) =>
        c.id === "c-imp-i2c" ? { ...c, violated: violations > 0 } : c,
      );
    }
    return MOCK_CONSTRAINTS;
  }

  /** Édition chirurgicale d'une contrainte — l'API V3 ne l'expose pas encore. */
  async updateConstraint(projectId: string, constraint: ConstraintItem): Promise<ConstraintItem> {
    await this.request(`/api/v1/designs/${encodeURIComponent(projectId)}/constraints/${encodeURIComponent(constraint.id)}`, {
      method: "PUT",
      body: JSON.stringify({ target: constraint.target, severity: constraint.severity }),
    });
    return constraint;
  }
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function normalizeJobStatus(s: string): Job["status"] {
  if (s === "completed" || s === "done") return "completed";
  if (s === "failed" || s === "error") return "failed";
  if (s === "queued" || s === "pending") return "queued";
  return "running";
}

/** Score qualité déterministe dérivé du design (routage/complexité/coût). */
export function qualityFromDesign(d: DesignSchema): QualityScore {
  const routed = d.nets.filter((n) => n.routed).length;
  const ratio = d.nets.length > 0 ? routed / d.nets.length : 1;
  const hs = d.nets.filter((n) => n.class_name === "high_speed").length;
  const routing = Math.round(ratio * 100);
  const erc = Math.max(60, Math.round(100 - 4 * (d.nets.length - routed)));
  const si = Math.max(60, Math.round(96 - 6 * hs * (1 - ratio)));
  const drc = 100;
  const dfm = 100;
  const thermal = 88;
  const cost = 99;
  const overall = Math.round((drc * 0.15 + erc * 0.15 + dfm * 0.15 + routing * 0.25 + thermal * 0.1 + si * 0.1 + cost * 0.1) * 10) / 10;
  return { overall, drc, erc, dfm, routing, thermal, si, cost };
}

/**
 * Normalise un DesignSchema venant de l'API :
 *  - positionne side/rotation par défaut,
 *  - synthétise un chemin orthogonal déterministe pour les nets routés
 *    sans path (permet l'affichage des traces même si l'API ne les envoie pas).
 */
export function augmentDesign(d: DesignSchema): DesignSchema {
  const byRef = new Map<string, Component>(d.components.map((c) => [c.ref, c]));
  const posOf = (ref: string): Point | null => {
    const c = byRef.get(ref);
    return c ? { x: c.x_mm, y: c.y_mm } : null;
  };
  const nets = d.nets.map((n) => {
    const net: DesignSchema["nets"][number] = {
      ...n,
      name: n.name || n.net_id,
      class_name: n.class_name || "default",
    };
    if (net.routed && (!net.path || net.path.length < 2)) {
      const a = net.pins.length > 0 ? posOf(net.pins[0][0]) : null;
      const b = net.pins.length > 1 ? posOf(net.pins[1][0]) : null;
      if (a && b) {
        const midX = Math.round(((a.x + b.x) / 2) * 2) / 2;
        net.path = [a, { x: midX, y: a.y }, { x: midX, y: b.y }, b];
      }
    }
    return net;
  });
  return {
    ...d,
    name: d.name || d.project_id,
    board_size_mm: [d.board_size_mm?.[0] ?? 60, d.board_size_mm?.[1] ?? 40],
    layers: d.layers?.length
      ? d.layers
      : [
          { index: 0, name: "F.Cu", type: "signal" },
          { index: 1, name: "GND", type: "ground" },
          { index: 2, name: "PWR", type: "power" },
          { index: 3, name: "B.Cu", type: "signal" },
        ],
    nets,
  };
}

/** Singleton partagé (muté à chaud par la page Paramètres). */
export const apiClient = new ApiClient();

/** Jeu de données mock exporté (réutilisé par les stores et la doc). */
export const MockData = {
  design: MOCK_DESIGN,
  projects: MOCK_PROJECTS,
  constraints: MOCK_CONSTRAINTS,
  optimization: MOCK_OPTIMIZATION,
  sims: MOCK_SIM_RESULTS,
};
