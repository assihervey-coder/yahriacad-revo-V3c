/**
 * LayerViewer — toolbar de couches (F.Cu / GND / PWR / B.Cu) : toggles de
 * visibilité qui filtrent l'affichage (store design_store) + sélection.
 */
"use client";

import { useDesignStore } from "@/stores/design_store";

/** Couleur de puce par type de couche. */
function layerColor(type: string): string {
  switch (type) {
    case "ground":
      return "#A78BFA";
    case "power":
      return "#f59e0b";
    case "mixed":
      return "#34d399";
    default:
      return "#22D3EE";
  }
}

const TYPE_LABEL: Record<string, string> = {
  signal: "signal",
  ground: "masse",
  power: "alim",
  mixed: "mixte",
};

export function LayerViewer() {
  const design = useDesignStore((s) => s.design);
  const visibleLayers = useDesignStore((s) => s.visibleLayers);
  const selectedLayer = useDesignStore((s) => s.selectedLayer);
  const toggleLayer = useDesignStore((s) => s.toggleLayer);
  const selectLayer = useDesignStore((s) => s.selectLayer);

  if (!design) return null;

  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <span className="mr-1 text-[11px] uppercase tracking-wider text-ink-dim">Couches</span>
      {design.layers.map((l) => {
        const visible = visibleLayers[l.name] !== false;
        const active = selectedLayer === l.name;
        return (
          <div key={l.name} className={`flex items-center overflow-hidden rounded-lg border ${active ? "border-accent-cyan/60" : "border-panel-border"}`}>
            <button
              type="button"
              onClick={() => selectLayer(l.name)}
              className={`flex items-center gap-1.5 px-2 py-1 text-xs transition-colors ${active ? "bg-accent-cyan/10 text-ink" : "bg-panel-soft text-ink-dim hover:text-ink"}`}
              title={`Sélectionner ${l.name} (${TYPE_LABEL[l.type] ?? l.type})`}
            >
              <span className="h-2 w-2 rounded-full" style={{ backgroundColor: layerColor(l.type), opacity: visible ? 1 : 0.25 }} />
              {l.name}
            </button>
            <button
              type="button"
              onClick={() => toggleLayer(l.name)}
              className={`px-1.5 py-1 text-[10px] ${visible ? "text-accent-cyan" : "text-ink-dim"}`}
              title={visible ? "Masquer la couche" : "Afficher la couche"}
              aria-label={`${visible ? "Masquer" : "Afficher"} ${l.name}`}
            >
              {visible ? "◉" : "○"}
            </button>
          </div>
        );
      })}
    </div>
  );
}
