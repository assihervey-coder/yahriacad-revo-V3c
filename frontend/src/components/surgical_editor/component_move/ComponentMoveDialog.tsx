/**
 * ComponentMoveDialog — édition précise d'un composant : ref, X/Y en mm
 * (numériques), rotation 0/90/180/270 → design_store.moveComponent.
 */
"use client";

import { useEffect, useState } from "react";
import { Modal } from "@/components/ui/Modal";
import { useDesignStore } from "@/stores/design_store";

export interface ComponentMoveDialogProps {
  open: boolean;
  initialRef?: string;
  onClose: () => void;
}

export function ComponentMoveDialog({ open, initialRef, onClose }: ComponentMoveDialogProps) {
  const design = useDesignStore((s) => s.design);
  const moveComponent = useDesignStore((s) => s.moveComponent);
  const [ref, setRef] = useState(initialRef ?? "");
  const [x, setX] = useState("0");
  const [y, setY] = useState("0");
  const [rotation, setRotation] = useState("0");

  // Recharge les valeurs du composant sélectionné à chaque ouverture.
  useEffect(() => {
    if (!open || !design) return;
    const target = design.components.find((c) => c.ref === (initialRef || ref)) ?? design.components[0];
    if (!target) return;
    setRef(target.ref);
    setX(String(target.x_mm));
    setY(String(target.y_mm));
    setRotation(String(target.rotation_deg ?? 0));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, initialRef, design]);

  const apply = async (): Promise<void> => {
    const px = Number.parseFloat(x);
    const py = Number.parseFloat(y);
    if (!ref || !Number.isFinite(px) || !Number.isFinite(py)) return;
    await moveComponent(ref, px, py, Number.parseInt(rotation, 10));
    onClose();
  };

  return (
    <Modal
      open={open}
      title="Déplacer un composant (édition chirurgicale)"
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn btn-ghost border border-panel-border" onClick={onClose}>
            Annuler
          </button>
          <button type="button" className="btn btn-primary" onClick={() => void apply()}>
            Appliquer
          </button>
        </>
      }
    >
      <div className="space-y-3">
        <div>
          <label className="label" htmlFor="move-ref">Composant</label>
          <select id="move-ref" className="input" value={ref} onChange={(e) => setRef(e.target.value)}>
            {(design?.components ?? []).map((c) => (
              <option key={c.ref} value={c.ref}>
                {c.ref} · {c.value || c.footprint || "—"}
              </option>
            ))}
          </select>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="label" htmlFor="move-x">X (mm)</label>
            <input id="move-x" className="input font-mono" type="number" step="0.5" min={0} value={x} onChange={(e) => setX(e.target.value)} />
          </div>
          <div>
            <label className="label" htmlFor="move-y">Y (mm)</label>
            <input id="move-y" className="input font-mono" type="number" step="0.5" min={0} value={y} onChange={(e) => setY(e.target.value)} />
          </div>
        </div>
        <div>
          <label className="label" htmlFor="move-rot">Rotation</label>
          <select id="move-rot" className="input" value={rotation} onChange={(e) => setRotation(e.target.value)}>
            {["0", "90", "180", "270"].map((r) => (
              <option key={r} value={r}>
                {r}°
              </option>
            ))}
          </select>
        </div>
        <p className="text-[11px] text-ink-dim">
          Le déplacement est appliqué localement puis PATCHé à l&rsquo;API (fallback silencieux hors ligne).
        </p>
      </div>
    </Modal>
  );
}
