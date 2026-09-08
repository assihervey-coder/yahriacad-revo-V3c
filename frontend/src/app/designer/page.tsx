/**
 * Page designer — la pièce maîtresse : 3 colonnes
 *   chat (+ commandes rapides + jobs) | viewer PCB (toolbar couches + overlays) |
 *   panneau agents (activité / contraintes / édition chirurgicale).
 * Header : stats design — composants / nets / routage / qualité.
 */
"use client";

import { useEffect, useMemo, useState } from "react";
import { ChatPanel } from "@/components/chat_interface/chat/ChatPanel";
import { DesignCommandBar } from "@/components/chat_interface/design_commands/DesignCommandBar";
import { AgentActivityFeed } from "@/components/chat_interface/agent_activity/AgentActivityFeed";
import { PcbViewer3D, type ViewerMode } from "@/components/viewer_3d/PcbViewer3D";
import { LayerViewer } from "@/components/viewer_3d/webgl/LayerViewer";
import { PlacementOverlay } from "@/components/pcb_editor/placement/PlacementOverlay";
import { RoutingOverlay } from "@/components/pcb_editor/routing/RoutingOverlay";
import { ConstraintsPanel } from "@/components/pcb_editor/constraints/ConstraintsPanel";
import { ComponentMoveDialog } from "@/components/surgical_editor/component_move/ComponentMoveDialog";
import { RouteEditDialog } from "@/components/surgical_editor/route_edit/RouteEditDialog";
import { ConstraintEditDialog } from "@/components/surgical_editor/constraint_edit/ConstraintEditDialog";
import { JobsDashboard } from "@/components/dashboard/jobs/JobsDashboard";
import { FirmwarePreview } from "@/components/firmware_preview/FirmwarePreview";
import { Badge } from "@/components/ui/Badge";
import { apiClient } from "@/services/api_client";
import { useAgentStore, type AgentState } from "@/stores/agent_store";
import { selectStats, useDesignStore } from "@/stores/design_store";
import { useProjectStore } from "@/stores/project_store";
import type { QualityScore } from "@/types";

type OverlayMode = "none" | "placement" | "routing";
type RightTab = "agents" | "constraints" | "editor";

/** Dernier job_id vu dans le flux d'activité (pour JobsDashboard). */
function selectLastJobId(s: AgentState): string | null {
  for (const e of s.events) {
    const jobId = e.payload.job_id ?? e.payload.jobId;
    if (typeof jobId === "string" && jobId) return jobId;
  }
  return null;
}

export default function DesignerPage() {
  const design = useDesignStore((s) => s.design);
  const loading = useDesignStore((s) => s.loading);
  const source = useDesignStore((s) => s.source);
  const visibleLayers = useDesignStore((s) => s.visibleLayers);
  const loadDesign = useDesignStore((s) => s.load);
  const refreshDesign = useDesignStore((s) => s.refresh);
  const moveComponent = useDesignStore((s) => s.moveComponent);
  const stats = useDesignStore(selectStats);
  const currentProject = useProjectStore((s) => s.current);

  const [viewerMode, setViewerMode] = useState<ViewerMode>("3d");
  const [overlay, setOverlay] = useState<OverlayMode>("placement");
  const [rightTab, setRightTab] = useState<RightTab>("agents");
  const [autoRotate, setAutoRotate] = useState(true);
  const [firmwareOpen, setFirmwareOpen] = useState(false);
  const [moveOpen, setMoveOpen] = useState(false);
  const [routeOpen, setRouteOpen] = useState(false);
  const [constraintOpen, setConstraintOpen] = useState(false);
  const [quality, setQuality] = useState<QualityScore | null>(null);
  const lastJobId = useAgentStore(selectLastJobId);

  const projectId = design?.project_id ?? currentProject?.project_id ?? null;

  // Chargement initial : projets → design + flux WS des agents.
  useEffect(() => {
    void (async () => {
      await useProjectStore.getState().load();
      const pid = useProjectStore.getState().current?.project_id;
      await loadDesign(pid);
      const effectivePid = useDesignStore.getState().projectId ?? pid ?? "demo-esp32-4l";
      useAgentStore.getState().connectLive(effectivePid);
    })();
    return () => useAgentStore.getState().disconnectLive();
  }, [loadDesign]);

  // Qualité recalculée à chaque nouvelle révision.
  const revision = design?.revision ?? 0;
  useEffect(() => {
    let alive = true;
    void (async () => {
      const q = await apiClient.getQuality(projectId ?? "demo-esp32-4l");
      if (alive) setQuality(q);
    })();
    return () => {
      alive = false;
    };
  }, [projectId, revision]);

  // Recentrage auto de la caméra désactivé en édition d'overlay.
  const headerStats = useMemo(
    () => [
      { label: "Composants", value: stats ? String(stats.components) : "—", tone: "cyan" as const },
      { label: "Nets", value: stats ? String(stats.nets) : "—", tone: "violet" as const },
      { label: "Routage", value: stats ? `${stats.routingPct}%` : "—", tone: stats && stats.routingPct >= 90 ? ("green" as const) : ("amber" as const) },
      { label: "Qualité", value: quality ? `${quality.overall}` : "…", tone: quality && quality.overall >= 85 ? ("green" as const) : ("amber" as const) },
    ],
    [stats, quality],
  );

  return (
    <div className="flex h-[calc(100vh-56px)] flex-col gap-3 p-3">
      {/* Header stats */}
      <header className="flex flex-wrap items-center gap-3">
        <h1 className="text-lg font-bold">
          Designer <span className="text-ink-dim">— {design?.name ?? "chargement…"}</span>
        </h1>
        <div className="flex flex-wrap gap-1.5">
          {headerStats.map((s) => (
            <Badge key={s.label} tone={s.tone}>
              {s.label} · <span className="font-mono font-bold">{s.value}</span>
            </Badge>
          ))}
          <Badge tone={source === "mock" ? "amber" : "cyan"}>{source === "mock" ? "mock" : `rev ${stats?.revision ?? 0}`}</Badge>
        </div>
        <div className="ml-auto flex gap-1.5">
          <button type="button" className="btn btn-ghost border border-panel-border px-2.5 py-1 text-xs" onClick={() => void refreshDesign()}>
            ⟳ Actualiser
          </button>
          <button
            type="button"
            className={`btn px-2.5 py-1 text-xs ${autoRotate ? "btn-primary" : "btn-ghost border-panel-border"}`}
            onClick={() => setAutoRotate((v) => !v)}
            title="Rotation automatique de la vue 3D"
          >
            ↻ Rotation
          </button>
        </div>
      </header>

      {/* 3 colonnes */}
      <div className="grid min-h-0 flex-1 grid-cols-1 gap-3 lg:grid-cols-[360px_1fr_340px]">
        {/* Colonne gauche : chat */}
        <section className="panel flex min-h-0 flex-col">
          <div className="border-b border-panel-border p-3">
            <DesignCommandBar />
          </div>
          <ChatPanel />
          <div className="border-t border-panel-border p-3">
            <JobsDashboard jobId={lastJobId} />
          </div>
        </section>

        {/* Colonne centrale : viewer */}
        <section className="flex min-h-0 flex-col gap-3">
          <div className="relative min-h-0 flex-1">
            <PcbViewer3D design={design} layersVisible={visibleLayers} autoRotate={autoRotate} onModeChange={setViewerMode}>
              {design && viewerMode === "2d" && overlay === "placement" && (
                <PlacementOverlay design={design} onMove={(ref, x, y) => void moveComponent(ref, x, y)} />
              )}
              {design && viewerMode === "2d" && overlay === "routing" && <RoutingOverlay design={design} />}
            </PcbViewer3D>
            {loading && (
              <div className="absolute inset-0 z-10 flex items-center justify-center rounded-xl bg-base/70 text-sm text-ink-dim">
                Chargement du design…
              </div>
            )}
          </div>

          {/* Toolbar : couches + overlays + édition */}
          <div className="panel flex flex-wrap items-center gap-3 p-3">
            <LayerViewer />
            <div className="ml-auto flex flex-wrap items-center gap-1.5">
              <span className="text-[11px] uppercase tracking-wider text-ink-dim">Overlay</span>
              {(
                [
                  ["placement", "Placement"],
                  ["routing", "Routage"],
                  ["none", "Aucun"],
                ] as [OverlayMode, string][]
              ).map(([id, label]) => (
                <button
                  key={id}
                  type="button"
                  onClick={() => setOverlay(id)}
                  className={`btn px-2 py-1 text-[11px] ${overlay === id ? "btn-primary" : "btn-ghost border-panel-border"}`}
                  disabled={viewerMode !== "2d"}
                  title={viewerMode !== "2d" ? "Overlays disponibles en vue 2D" : label}
                >
                  {label}
                </button>
              ))}
              <span className="mx-1 h-4 w-px bg-panel-border" />
              <button type="button" className="btn btn-ghost border border-panel-border px-2 py-1 text-[11px]" onClick={() => setMoveOpen(true)}>
                ✥ Déplacer
              </button>
              <button type="button" className="btn btn-ghost border border-panel-border px-2 py-1 text-[11px]" onClick={() => setRouteOpen(true)}>
                ⟋ Route
              </button>
              <button type="button" className="btn btn-ghost border border-panel-border px-2 py-1 text-[11px]" onClick={() => setConstraintOpen(true)}>
                ⚖ Contrainte
              </button>
              <button
                type="button"
                className={`btn px-2 py-1 text-[11px] ${firmwareOpen ? "btn-violet" : "btn-ghost border-panel-border"}`}
                onClick={() => setFirmwareOpen((v) => !v)}
              >
                ⌨ Firmware
              </button>
            </div>
          </div>

          {firmwareOpen && (
            <div className="max-h-[240px] min-h-0 overflow-y-auto">
              <FirmwarePreview />
            </div>
          )}
        </section>

        {/* Colonne droite : agents / contraintes / édition */}
        <section className="flex min-h-0 flex-col gap-2">
          <div className="flex gap-1">
            {(
              [
                ["agents", "Agents"],
                ["constraints", "Contraintes"],
                ["editor", "Éditeur"],
              ] as [RightTab, string][]
            ).map(([id, label]) => (
              <button
                key={id}
                type="button"
                onClick={() => setRightTab(id)}
                className={`btn flex-1 px-2 py-1.5 text-xs ${rightTab === id ? "btn-primary" : "btn-ghost border-panel-border"}`}
              >
                {label}
              </button>
            ))}
          </div>
          <div className="min-h-0 flex-1">
            {rightTab === "agents" && <AgentActivityFeed />}
            {rightTab === "constraints" && <ConstraintsPanel projectId={projectId} />}
            {rightTab === "editor" && (
              <div className="panel flex h-full flex-col items-center justify-center gap-3 p-6 text-center">
                <p className="text-sm text-ink-dim">
                  Édition chirurgicale : déplacement précis, édition de routage et contraintes physiques.
                </p>
                <div className="flex flex-col gap-2">
                  <button type="button" className="btn btn-primary" onClick={() => setMoveOpen(true)}>
                    ✥ Déplacer un composant
                  </button>
                  <button type="button" className="btn btn-primary" onClick={() => setRouteOpen(true)}>
                    ⟋ Éditer un routage
                  </button>
                  <button type="button" className="btn btn-primary" onClick={() => setConstraintOpen(true)}>
                    ⚖ Éditer les contraintes
                  </button>
                </div>
                {design && (
                  <p className="font-mono text-[11px] text-ink-dim">
                    {design.components.length} composants · {design.nets.length} nets · rev {design.revision}
                  </p>
                )}
              </div>
            )}
          </div>
        </section>
      </div>

      {/* Dialogues chirurgicaux */}
      <ComponentMoveDialog open={moveOpen} onClose={() => setMoveOpen(false)} />
      <RouteEditDialog open={routeOpen} onClose={() => setRouteOpen(false)} />
      <ConstraintEditDialog open={constraintOpen} projectId={projectId} onClose={() => setConstraintOpen(false)} />
    </div>
  );
}
