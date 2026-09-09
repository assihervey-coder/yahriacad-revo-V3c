/**
 * PcbViewer3D — conteneur du viewer : import DYNAMIQUE de ThreeViewer
 * (next/dynamic, ssr:false) + fallback 2D SVG du board si three/WebGL
 * indisponible ou sur demande utilisateur. Les overlays (children) sont
 * rendus par-dessus la vue 2D uniquement.
 */
"use client";

import dynamic from "next/dynamic";
import { useEffect, useState, type ReactNode } from "react";
import type { DesignSchema } from "@/types";
import { compRect, pathPointsAttr, refColor, traceColor } from "@/lib/pcb";

const ThreeViewer = dynamic(() => import("./threejs/ThreeViewer").then((m) => m.ThreeViewer), {
  ssr: false,
  loading: () => (
    <div className="flex h-full items-center justify-center text-sm text-ink-dim">Chargement de la scène 3D…</div>
  ),
});

export type ViewerMode = "3d" | "2d";

export interface PcbViewer3DProps {
  design: DesignSchema | null;
  layersVisible?: Record<string, boolean>;
  autoRotate?: boolean;
  onModeChange?: (mode: ViewerMode) => void;
  /** Overlays SVG (placement/routage) rendus au-dessus de la vue 2D. */
  children?: ReactNode;
}

/** Couleur de fond du board 2D. */
const SIDE_BOTTOM = "rgba(148,163,184,0.35)";

export function PcbViewer3D({ design, layersVisible = {}, autoRotate = true, onModeChange, children }: PcbViewer3DProps) {
  const [mode, setMode] = useState<ViewerMode>("3d");
  const [threeFailed, setThreeFailed] = useState(false);
  const [exploded, setExploded] = useState(0);
  const effective: ViewerMode = threeFailed ? "2d" : mode;

  useEffect(() => {
    onModeChange?.(effective);
  }, [effective, onModeChange]);

  const [w, h] = design?.board_size_mm ?? [60, 40];
  const layerOk = (layerIdx: number): boolean => {
    const name = design?.layers[layerIdx]?.name ?? design?.layers[0]?.name ?? "F.Cu";
    return layersVisible[name] !== false;
  };

  return (
    <div className="relative h-full w-full overflow-hidden rounded-xl border border-panel-border bg-base">
      {effective === "3d" ? (
        <ThreeViewer
          design={design}
          layersVisible={layersVisible}
          autoRotate={autoRotate}
          exploded={exploded}
          onError={() => setThreeFailed(true)}
        />
      ) : (
        <>
          {/* Fallback 2D : rectangles composants colorés par type + traces des nets */}
          <svg viewBox={`-2 -2 ${w + 4} ${h + 4}`} className="h-full w-full" preserveAspectRatio="xMidYMid meet" role="img" aria-label="Vue 2D du PCB">
            <defs>
              <pattern id="grid" width="5" height="5" patternUnits="userSpaceOnUse">
                <path d="M 5 0 L 0 0 0 5" fill="none" stroke="#1a2130" strokeWidth="0.15" />
              </pattern>
            </defs>
            <rect x={0} y={0} width={w} height={h} rx={1.5} fill="#0d1420" stroke="#2f394d" strokeWidth={0.35} />
            <rect x={0} y={0} width={w} height={h} rx={1.5} fill="url(#grid)" />

            {/* Traces (nets routés) */}
            {(design?.nets ?? []).map((n) => {
              if (!n.path || n.path.length < 2) return null;
              const idx = n.layer ?? 0;
              if (!layerOk(idx)) return null;
              return (
                <polyline
                  key={n.net_id}
                  points={pathPointsAttr(n.path, h)}
                  fill="none"
                  stroke={traceColor(n)}
                  strokeWidth={n.class_name === "power" ? 0.7 : 0.4}
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  opacity={0.85}
                />
              );
            })}

            {/* Composants */}
            {(design?.components ?? []).map((c) => {
              const r = compRect(c, h);
              const col = refColor(c.ref);
              const bottom = c.side === "bottom";
              return (
                <g key={c.ref}>
                  <rect
                    x={r.x}
                    y={r.y}
                    width={r.w}
                    height={r.h}
                    rx={0.35}
                    fill={col}
                    fillOpacity={bottom ? 0.25 : 0.65}
                    stroke={col}
                    strokeWidth={0.18}
                    strokeDasharray={bottom ? "0.5 0.3" : undefined}
                  />
                  <text
                    x={r.x + r.w / 2}
                    y={r.y - 0.45}
                    textAnchor="middle"
                    fontSize={Math.min(1.6, Math.max(0.9, r.w / 4))}
                    fill="#9CA3AF"
                    style={{ pointerEvents: "none", userSelect: "none" }}
                  >
                    {c.ref}
                  </text>
                </g>
              );
            })}
          </svg>
          {/* Overlays positionnés au-dessus de la vue 2D */}
          {children}
        </>
      )}

      {/* Toolbar mode */}
      <div className="absolute left-3 top-3 flex items-center gap-2">
        {effective === "3d" && (
          <label className="flex items-center gap-1.5 rounded-lg border border-panel-border bg-panel/90 px-2 py-1 text-[10px] text-ink-dim">
            éclaté
            <input
              type="range"
              min={0}
              max={100}
              value={Math.round(exploded * 100)}
              onChange={(e) => setExploded(Number(e.target.value) / 100)}
              className="h-1 w-20 accent-cyan-400"
              title="Sépare les couches du stack (vue éclatée)"
            />
          </label>
        )}
      </div>
      <div className="absolute right-3 top-12 flex gap-1.5">
        <button
          type="button"
          onClick={() => setMode("3d")}
          disabled={threeFailed}
          className={`btn px-2.5 py-1 text-xs ${effective === "3d" ? "btn-primary" : "btn-ghost border-panel-border"}`}
          title={threeFailed ? "WebGL indisponible — vue 2D uniquement" : "Vue 3D three.js"}
        >
          3D
        </button>
        <button
          type="button"
          onClick={() => setMode("2d")}
          className={`btn px-2.5 py-1 text-xs ${effective === "2d" ? "btn-primary" : "btn-ghost border-panel-border"}`}
          title="Vue 2D SVG (overlays éditables)"
        >
          2D
        </button>
        {effective === "2d" && (
          <span className="badge border border-panel-border bg-panel text-[10px] text-ink-dim" style={{ color: SIDE_BOTTOM }}>
            bottom = hachuré
          </span>
        )}
      </div>

      {design && (
        <div className="absolute bottom-3 left-3 flex items-center gap-2 text-[11px] text-ink-dim">
          <span className="badge border border-panel-border bg-panel">{design.name}</span>
          <span className="badge border border-panel-border bg-panel">rev {design.revision}</span>
          <span className="badge border border-panel-border bg-panel">
            {w} × {h} mm
          </span>
        </div>
      )}
    </div>
  );
}
