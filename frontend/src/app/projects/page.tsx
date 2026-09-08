/** Page projets — cartes + modal de création (POST /api/v1/projects). */
"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { ProjectsDashboard } from "@/components/dashboard/projects/ProjectsDashboard";
import { Modal } from "@/components/ui/Modal";
import { Badge, mapStatusTone } from "@/components/ui/Badge";
import { useDesignStore } from "@/stores/design_store";
import { useProjectStore } from "@/stores/project_store";

export default function ProjectsPage() {
  const router = useRouter();
  const projects = useProjectStore((s) => s.projects);
  const loading = useProjectStore((s) => s.loading);
  const source = useProjectStore((s) => s.source);
  const load = useProjectStore((s) => s.load);
  const create = useProjectStore((s) => s.create);
  const select = useProjectStore((s) => s.select);
  const loadDesign = useDesignStore((s) => s.load);

  const [modalOpen, setModalOpen] = useState(false);
  const [name, setName] = useState("");
  const [creating, setCreating] = useState(false);

  useEffect(() => {
    void load();
  }, [load]);

  const openProject = (projectId: string): void => {
    select(projectId);
    void loadDesign(projectId);
    router.push("/designer");
  };

  const submitCreate = async (): Promise<void> => {
    const trimmed = name.trim();
    if (!trimmed) return;
    setCreating(true);
    const p = await create(trimmed);
    setCreating(false);
    setModalOpen(false);
    setName("");
    openProject(p.project_id);
  };

  return (
    <div className="mx-auto w-full max-w-[1200px] px-4 py-8">
      <header className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold">Projets</h1>
          <p className="mt-1 text-sm text-ink-dim">
            {projects.length} projet{projects.length > 1 ? "s" : ""} · source{" "}
            <Badge tone={source === "mock" ? "amber" : "green"}>{source === "mock" ? "mock (API injoignable)" : "API"}</Badge>
          </p>
        </div>
        <button type="button" className="btn btn-primary" onClick={() => setModalOpen(true)}>
          + Nouveau projet
        </button>
      </header>

      {/* Cartes projets */}
      <section className="mb-10 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {loading && <p className="text-sm text-ink-dim">Chargement…</p>}
        {projects.map((p) => (
          <button
            key={p.project_id}
            type="button"
            onClick={() => openProject(p.project_id)}
            className="panel group p-4 text-left transition-transform hover:-translate-y-0.5"
          >
            <div className="flex items-start justify-between gap-2">
              <h2 className="font-semibold text-ink group-hover:text-accent-cyan">{p.name}</h2>
              <Badge tone={mapStatusTone(p.status ?? "draft")}>{p.status ?? "draft"}</Badge>
            </div>
            <p className="mt-1 font-mono text-[11px] text-ink-dim">{p.project_id}</p>
            <div className="mt-3 flex gap-2 text-[11px] text-ink-dim">
              <span className="badge border border-panel-border bg-panel-soft">rev {p.last_rev ?? 0}</span>
              <span className="badge border border-panel-border bg-panel-soft">{p.component_count ?? "—"} comp.</span>
            </div>
          </button>
        ))}
      </section>

      {/* Tableau détaillé */}
      <section>
        <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-ink-dim">Vue détaillée</h2>
        <div className="panel p-4">
          <ProjectsDashboard onSelect={openProject} />
        </div>
      </section>

      {/* Modal création */}
      <Modal
        open={modalOpen}
        title="Nouveau projet"
        onClose={() => setModalOpen(false)}
        footer={
          <>
            <button type="button" className="btn btn-ghost border border-panel-border" onClick={() => setModalOpen(false)}>
              Annuler
            </button>
            <button type="button" className="btn btn-primary" onClick={() => void submitCreate()} disabled={creating || name.trim() === ""}>
              {creating ? "Création…" : "Créer"}
            </button>
          </>
        }
      >
        <label className="label" htmlFor="project-name">Nom du projet</label>
        <input
          id="project-name"
          className="input"
          placeholder="Ex : ESP32 gateway LoRa 4 couches"
          value={name}
          onChange={(e) => setName(e.target.value)}
          autoFocus
        />
        <p className="mt-2 text-[11px] text-ink-dim">
          Le projet est créé via POST /api/v1/projects (tenant header X-Tenant-Id). Si l&rsquo;API est
          injoignable, un projet local « mock » est créé pour la démo.
        </p>
      </Modal>
    </div>
  );
}
