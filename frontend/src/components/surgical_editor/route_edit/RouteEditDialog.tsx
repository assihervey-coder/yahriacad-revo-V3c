/**
 * RouteEditDialog — édition chirurgicale d'un routage : sélection d'un net,
 * édition des points (X/Y), ajout/suppression de via.
 */
"use client";

import { useEffect, useMemo, useState } from "react";
import { Modal } from "@/components/ui/Modal";
import { snapGrid } from "@/lib/pcb";
import { useDesignStore } from "@/stores/design_store";
import type { Point } from "@/types";

export interface RouteEditDialogProps {
  open: boolean;
  initialNetId?: string;
  onClose: () => void;
}

export function RouteEditDialog({ open, initialNetId, onClose }: RouteEditDialogProps) {
  const design = useDesignStore((s) => s.design);
  const updateNetPath = useDesignStore((s) => s.updateNetPath);
  const [netId, setNetId] = useState(initialNetId ?? "");
  const [points, setPoints] = useState<Point[]>([]);
  const [vias, setVias] = useState<Point[]>([]);

  const net = useMemo(() => design?.nets.find((n) => n.net_id === netId) ?? null, [design, netId]);

  // Charge le net sélectionné à l'ouverture / au changement de sélection.
  useEffect(() => {
    if (!open || !design) return;
    const target = design.nets.find((n) => n.net_id === (initialNetId || netId)) ?? design.nets[0];
    if (!target) return;
    setNetId(target.net_id);
    setPoints(target.path ? target.path.map((p) => ({ ...p })) : []);
    setVias(target.vias ? target.vias.map((v) => ({ ...v })) : []);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, initialNetId, design]);

  const setPoint = (i: number, axis: "x" | "y", raw: string): void => {
    const v = Number.parseFloat(raw);
    setPoints((pts) => pts.map((p, idx) => (idx === i ? { ...p, [axis]: Number.isFinite(v) ? v : 0 } : p)));
  };

  const save = (): void => {
    if (!net) return;
    updateNetPath(net.net_id, points.map((p) => ({ x: snapGrid(p.x), y: snapGrid(p.y) })), vias);
    onClose();
  };

  return (
    <Modal
      open={open}
      title="Éditer le routage d'un net"
      onClose={onClose}
      width="560px"
      footer={
        <>
          <button type="button" className="btn btn-ghost border border-panel-border" onClick={onClose}>
            Annuler
          </button>
          <button type="button" className="btn btn-primary" onClick={save} disabled={!net}>
            Enregistrer le path
          </button>
        </>
      }
    >
      <div className="space-y-3">
        <div>
          <label className="label" htmlFor="route-net">Net</label>
          <select id="route-net" className="input" value={netId} onChange={(e) => setNetId(e.target.value)}>
            {(design?.nets ?? []).map((n) => (
              <option key={n.net_id} value={n.net_id}>
                {n.name || n.net_id} {n.routed ? "" : "(non routé)"}
              </option>
            ))}
          </select>
        </div>

        {/* Points du path */}
        <div>
          <div className="mb-1 flex items-center justify-between">
            <span className="label mb-0">Points du path ({points.length})</span>
            <button
              type="button"
              className="btn btn-ghost border border-panel-border px-2 py-0.5 text-[11px]"
              onClick={() => {
                const last = points[points.length - 1] ?? { x: 0, y: 0 };
                setPoints([...points, { x: snapGrid(last.x + 2), y: snapGrid(last.y) }]);
              }}
            >
              + point
            </button>
          </div>
          <div className="max-h-48 space-y-1 overflow-y-auto pr-1">
            {points.map((p, i) => (
              <div key={`${i}-${p.x}-${p.y}`} className="flex items-center gap-2">
                <span className="w-6 shrink-0 text-right font-mono text-[11px] text-ink-dim">{i}</span>
                <input
                  className="input px-2 py-1 font-mono text-xs"
                  type="number"
                  step="0.5"
                  value={p.x}
                  onChange={(e) => setPoint(i, "x", e.target.value)}
                  aria-label={`Point ${i} X`}
                />
                <input
                  className="input px-2 py-1 font-mono text-xs"
                  type="number"
                  step="0.5"
                  value={p.y}
                  onChange={(e) => setPoint(i, "y", e.target.value)}
                  aria-label={`Point ${i} Y`}
                />
                <button
                  type="button"
                  className="btn btn-ghost px-1.5 py-1 text-xs text-rose-300 hover:text-rose-200"
                  onClick={() => setPoints(points.filter((_, idx) => idx !== i))}
                  aria-label={`Supprimer point ${i}`}
                >
                  ✕
                </button>
              </div>
            ))}
            {points.length === 0 && <p className="text-xs text-ink-dim">Aucun point — ajoutez-en pour router ce net.</p>}
          </div>
        </div>

        {/* Vias */}
        <div>
          <div className="mb-1 flex items-center justify-between">
            <span className="label mb-0">Vias ({vias.length})</span>
            <div className="flex gap-1">
              <button
                type="button"
                className="btn btn-ghost border border-panel-border px-2 py-0.5 text-[11px]"
                onClick={() => {
                  const src = points[0] ?? { x: 0, y: 0 };
                  setVias([...vias, { x: snapGrid(src.x), y: snapGrid(src.y) }]);
                }}
              >
                + via (dép. path)
              </button>
            </div>
          </div>
          {vias.length === 0 ? (
            <p className="text-xs text-ink-dim">Aucun via sur ce net.</p>
          ) : (
            <div className="space-y-1">
              {vias.map((v, i) => (
                <div key={`${i}-${v.x}-${v.y}`} className="flex items-center gap-2">
                  <span className="badge border border-panel-border bg-panel-soft font-mono text-ink-dim">via {i + 1}</span>
                  <input
                    className="input px-2 py-1 font-mono text-xs"
                    type="number"
                    step="0.5"
                    value={v.x}
                    onChange={(e) => {
                      const val = Number.parseFloat(e.target.value);
                      setVias(vias.map((vv, idx) => (idx === i ? { ...vv, x: Number.isFinite(val) ? val : 0 } : vv)));
                    }}
                    aria-label={`Via ${i + 1} X`}
                  />
                  <input
                    className="input px-2 py-1 font-mono text-xs"
                    type="number"
                    step="0.5"
                    value={v.y}
                    onChange={(e) => {
                      const val = Number.parseFloat(e.target.value);
                      setVias(vias.map((vv, idx) => (idx === i ? { ...vv, y: Number.isFinite(val) ? val : 0 } : vv)));
                    }}
                    aria-label={`Via ${i + 1} Y`}
                  />
                  <button
                    type="button"
                    className="btn btn-ghost px-1.5 py-1 text-xs text-rose-300 hover:text-rose-200"
                    onClick={() => setVias(vias.filter((_, idx) => idx !== i))}
                    aria-label={`Supprimer via ${i + 1}`}
                  >
                    ✕
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </Modal>
  );
}
