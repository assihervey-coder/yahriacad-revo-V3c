/** Store design — DesignSchema courant, couches visibles, édition chirurgicale. */
import { create } from "zustand";
import { apiClient } from "@/services/api_client";
import { useProjectStore } from "@/stores/project_store";
import type { DesignSchema } from "@/types";

/** Statistiques compactes calculées depuis le design. */
export interface DesignStats {
  components: number;
  nets: number;
  routed: number;
  routingPct: number;
  layers: number;
  revision: number;
}

interface DesignState {
  design: DesignSchema | null;
  projectId: string | null;
  loading: boolean;
  source: "api" | "mock" | null;
  /** Visibilité par nom de couche (F.Cu, GND, PWR, B.Cu...). */
  visibleLayers: Record<string, boolean>;
  selectedLayer: string | null;
  load: (projectId?: string) => Promise<void>;
  refresh: () => Promise<void>;
  selectLayer: (name: string) => void;
  toggleLayer: (name: string) => void;
  /** Déplacement (drag ou dialogue) — maj locale optimiste + PATCH API. */
  moveComponent: (ref: string, xMm: number, yMm: number, rotationDeg?: number) => Promise<void>;
  /** Édition chirurgicale d'un routage (points + vias) — maj locale. */
  updateNetPath: (netId: string, path: { x: number; y: number }[], vias: { x: number; y: number }[]) => void;
  reset: () => void;
}

export const useDesignStore = create<DesignState>((set, get) => ({
  design: null,
  projectId: null,
  loading: false,
  source: null,
  visibleLayers: {},
  selectedLayer: null,

  load: async (projectId) => {
    const pid = projectId ?? get().projectId ?? useProjectStore.getState().current?.project_id ?? "demo-esp32-4l";
    set({ loading: true, projectId: pid });
    try {
      const design = await apiClient.getDesign(pid);
      const layers: Record<string, boolean> = {};
      for (const l of design.layers) layers[l.name] = true;
      set({
        design,
        loading: false,
        visibleLayers: layers,
        selectedLayer: design.layers[0]?.name ?? null,
        source: apiClient.mockMode ? "mock" : "api",
      });
    } catch {
      set({ loading: false });
    }
  },

  refresh: async () => {
    const pid = get().projectId;
    if (pid) await get().load(pid);
  },

  selectLayer: (name) => set({ selectedLayer: name }),

  toggleLayer: (name) =>
    set((s) => ({ visibleLayers: { ...s.visibleLayers, [name]: !(s.visibleLayers[name] ?? true) } })),

  moveComponent: async (ref, xMm, yMm, rotationDeg) => {
    // 1) maj optimiste locale (l'UI ne doit jamais attendre le réseau)
    set((s) => {
      if (!s.design) return s;
      const design: DesignSchema = {
        ...s.design,
        components: s.design.components.map((c) =>
          c.ref === ref
            ? { ...c, x_mm: xMm, y_mm: yMm, rotation_deg: rotationDeg ?? c.rotation_deg ?? 0 }
            : c,
        ),
      };
      return { design };
    });
    // 2) PATCH backend (échec silencieux — le state local reste la vérité UI)
    const pid = get().projectId;
    if (pid) {
      try {
        await apiClient.moveComponent(pid, ref, xMm, yMm, rotationDeg);
      } catch {
        // fallback silencieux
      }
    }
  },

  updateNetPath: (netId, path, vias) =>
    set((s) => {
      if (!s.design) return s;
      const design: DesignSchema = {
        ...s.design,
        nets: s.design.nets.map((n) => (n.net_id === netId ? { ...n, path, vias, routed: path.length >= 2 } : n)),
      };
      return { design };
    }),

  reset: () => set({ design: null, projectId: null, visibleLayers: {}, selectedLayer: null }),
}));

/** Sélecteur : statistiques du design courant (null si vide). */
export function selectStats(s: DesignState): DesignStats | null {
  const d = s.design;
  if (!d) return null;
  const routed = d.nets.filter((n) => n.routed).length;
  return {
    components: d.components.length,
    nets: d.nets.length,
    routed,
    routingPct: d.nets.length > 0 ? Math.round((routed / d.nets.length) * 100) : 0,
    layers: d.layers.length,
    revision: d.revision,
  };
}
