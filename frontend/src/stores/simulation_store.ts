/** Store simulations — résultats par kind, lancement, dernier résultat. */
import { create } from "zustand";
import { apiClient } from "@/services/api_client";
import type { SimKind, SimResult } from "@/types";

interface SimState {
  results: Partial<Record<SimKind, SimResult>>;
  /** kinds en cours de calcul. */
  running: SimKind[];
  lastRunTs: number | null;
  run: (projectId: string, kinds: SimKind[]) => Promise<void>;
  /** Dernier résultat d'un kind (null si jamais lancé). */
  latest: (kind: SimKind) => SimResult | null;
  clear: () => void;
}

const ALL_KINDS: SimKind[] = ["thermal", "em", "si", "pi"];

export const useSimulationStore = create<SimState>((set, get) => ({
  results: {},
  running: [],
  lastRunTs: null,

  run: async (projectId, kinds) => {
    const wanted = kinds.length > 0 ? kinds : ALL_KINDS;
    set({ running: wanted });
    try {
      const results = await apiClient.simulate(projectId, wanted);
      set((s) => ({ results: { ...s.results, ...results }, running: [], lastRunTs: Date.now() }));
    } catch {
      // apiClient.simulate retombe déjà sur le mock ; ce catch est défensif.
      set({ running: [] });
    }
  },

  latest: (kind) => get().results[kind] ?? null,

  clear: () => set({ results: {}, running: [], lastRunTs: null }),
}));

/** Tous les kinds supportés (Thermique/EM/SI/PI). */
export const SIM_KINDS = ALL_KINDS;
