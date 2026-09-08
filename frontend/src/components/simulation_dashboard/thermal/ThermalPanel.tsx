/**
 * ThermalPanel — heatmap CSS grid 20x16 (bleu → rouge) depuis metrics.heatmap
 * + max_temp_c en gros chiffre. Fallback : grille synthétique déterministe.
 */
"use client";

import { Badge } from "@/components/ui/Badge";
import { readArr, readNum } from "@/services/api_client";
import type { SimResult } from "@/types";

/** Couleur bleu→rouge pour une température entre ambient et max. */
function tempColor(t: number, tMin: number, tMax: number): string {
  const ratio = tMax > tMin ? Math.max(0, Math.min(1, (t - tMin) / (tMax - tMin))) : 0;
  // Interpolation : #1d4ed8 (bleu) → #22d3ee → #fbbf24 → #ef4444
  const stops: [number, [number, number, number]][] = [
    [0, [29, 78, 216]],
    [0.35, [34, 211, 238]],
    [0.65, [251, 191, 36]],
    [1, [239, 68, 68]],
  ];
  for (let i = 1; i < stops.length; i += 1) {
    if (ratio <= stops[i][0]) {
      const [r0, g0, b0] = stops[i - 1][1];
      const [r1, g1, b1] = stops[i][1];
      const k = (ratio - stops[i - 1][0]) / (stops[i][0] - stops[i - 1][0] || 1);
      return `rgb(${Math.round(r0 + (r1 - r0) * k)}, ${Math.round(g0 + (g1 - g0) * k)}, ${Math.round(b0 + (b1 - b0) * k)})`;
    }
  }
  return "rgb(239,68,68)";
}

/** Grille synthétique si l'API n'en fournit pas. */
function synthGrid(w: number, h: number, maxC: number, hx: number, hy: number): number[] {
  const grid: number[] = [];
  for (let y = 0; y < h; y += 1) {
    for (let x = 0; x < w; x += 1) {
      const d = Math.hypot(x - hx, y - hy);
      grid.push(26 + (maxC - 26) * Math.exp(-(d * d) / 28));
    }
  }
  return grid;
}

export function ThermalPanel({ result }: { result: SimResult | null }) {
  if (!result) {
    return <p className="text-sm text-ink-dim">Lancez la simulation thermique pour afficher la heatmap.</p>;
  }

  const gw = readNum(result.metrics, "grid_w", 20);
  const gh = readNum(result.metrics, "grid_h", 16);
  const maxC = readNum(result.metrics, "max_temp_c", 89.3);
  const ambient = readNum(result.metrics, "ambient_c", 25);
  const hotspotRef = typeof result.metrics.hotspot_ref === "string" ? result.metrics.hotspot_ref : "U1";
  const hx = readNum(result.metrics, "hotspot_x_mm", 30);
  const hy = readNum(result.metrics, "hotspot_y_mm", 22);
  const boardW = readNum(result.metrics, "board_w_mm", 60);
  const boardH = readNum(result.metrics, "board_h_mm", 40);

  const raw = readArr<number>(result.metrics, "heatmap");
  const grid = raw.length === gw * gh ? raw : synthGrid(gw, gh, maxC, (hx / boardW) * gw, (hy / boardH) * gh);

  return (
    <div className="flex flex-wrap items-start gap-6">
      {/* Gros chiffre */}
      <div className="min-w-[150px]">
        <div className="flex items-baseline gap-1">
          <span className="text-5xl font-extrabold text-ink">{maxC.toFixed(1)}</span>
          <span className="text-lg text-ink-dim">°C</span>
        </div>
        <p className="mt-1 text-xs text-ink-dim">
          max @ <span className="font-mono text-ink">{hotspotRef}</span> · ambiant {ambient}°C
        </p>
        <div className="mt-3 flex flex-wrap gap-1.5">
          <Badge tone={maxC <= 95 ? "green" : maxC <= 110 ? "amber" : "red"}>{maxC <= 95 ? "dans le budget" : "hotspot critique"}</Badge>
          <Badge tone={result.source === "api" ? "cyan" : "amber"}>{result.source === "api" ? "API" : "mock"}</Badge>
        </div>
      </div>

      {/* Heatmap CSS grid */}
      <div
        className="grid overflow-hidden rounded-lg border border-panel-border"
        style={{ gridTemplateColumns: `repeat(${gw}, 14px)`, gap: 0 }}
        role="img"
        aria-label={`Heatmap thermique ${gw}x${gh}`}
      >
        {grid.map((t, i) => (
          <div
            key={`cell-${i}`}
            title={`${t.toFixed(1)} °C`}
            style={{ width: 14, height: 14, backgroundColor: tempColor(t, ambient, maxC) }}
          />
        ))}
      </div>

      {/* Légende */}
      <div className="space-y-1 text-[11px] text-ink-dim">
        <div className="flex items-center gap-1.5">
          <span className="h-2.5 w-6 rounded-sm" style={{ background: "linear-gradient(90deg, rgb(29,78,216), rgb(34,211,238), rgb(251,191,36), rgb(239,68,68))" }} />
          <span>{ambient}°C → {maxC.toFixed(0)}°C</span>
        </div>
        <p>Grille {gw}×{gh} · régime permanent</p>
      </div>
    </div>
  );
}
