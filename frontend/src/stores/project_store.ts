/** Store projets — liste, projet courant, création (avec fallback mock). */
import { create } from "zustand";
import { apiClient } from "@/services/api_client";
import type { Project } from "@/types";

interface ProjectState {
  projects: Project[];
  current: Project | null;
  loading: boolean;
  /** "mock" si l'API était injoignable au dernier chargement. */
  source: "api" | "mock" | null;
  load: () => Promise<void>;
  create: (name: string) => Promise<Project>;
  select: (projectId: string) => void;
}

export const useProjectStore = create<ProjectState>((set) => ({
  projects: [],
  current: null,
  loading: false,
  source: null,

  load: async () => {
    set({ loading: true });
    try {
      const projects = await apiClient.getProjects();
      set({ projects, loading: false, source: apiClient.mockMode ? "mock" : "api" });
    } catch {
      set({ loading: false });
    }
  },

  create: async (name) => {
    const project = await apiClient.createProject(name);
    set((s) => ({ projects: [project, ...s.projects], current: project }));
    return project;
  },

  select: (projectId) => {
    set((s) => ({ current: s.projects.find((p) => p.project_id === projectId) ?? null }));
  },
}));

/** Sélecteur : projet par défaut (courant sinon premier de la liste). */
export function selectDefaultProject(s: ProjectState): Project | null {
  return s.current ?? s.projects[0] ?? null;
}
