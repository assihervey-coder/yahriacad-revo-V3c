/**
 * ConstraintEditDialog — édition chirurgicale des contraintes physiques :
 * clearance (mm), largeur de piste (mm), impédance cible (Ω).
 */
"use client";

import { useEffect, useState } from "react";
import { Modal } from "@/components/ui/Modal";
import { apiClient } from "@/services/api_client";
import { useDesignStore } from "@/stores/design_store";

export interface ConstraintEditDialogProps {
  open: boolean;
  projectId: string | null;
  onClose: () => void;
}

export function ConstraintEditDialog({ open, projectId, onClose }: ConstraintEditDialogProps) {
  const [clearance, setClearance] = useState("0.2");
  const [traceWidth, setTraceWidth] = useState("0.2");
  const [impedance, setImpedance] = useState("50");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState<string>("");

  // Valeurs par défaut cohérentes avec les contraintes mock.
  useEffect(() => {
    if (open) setSaved("");
  }, [open]);

  const save = async (): Promise<void> => {
    setSaving(true);
    await apiClient.updateConstraint(projectId ?? "demo-esp32-4l", {
      id: "c-clear",
      name: "Clearance minimale",
      kind: "clearance",
      target: `≥ ${clearance} mm`,
      severity: "error",
      violated: false,
      detail: "éditée manuellement",
    });
    await apiClient.updateConstraint(projectId ?? "demo-esp32-4l", {
      id: "c-trace",
      name: "Largeur de piste",
      kind: "trace_width",
      target: `≥ ${traceWidth} mm`,
      severity: "error",
      violated: false,
      detail: "éditée manuellement",
    });
    await apiClient.updateConstraint(projectId ?? "demo-esp32-4l", {
      id: "c-imp-usb",
      name: "Impédance cible USB",
      kind: "impedance",
      target: `${impedance} Ω ±5 %`,
      severity: "error",
      violated: false,
      detail: "éditée manuellement",
    });
    setSaving(false);
    setSaved(new Date().toLocaleTimeString("fr-FR", { hour12: false }));
    onClose();
  };

  return (
    <Modal
      open={open}
      title="Éditer les contraintes physiques"
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn btn-ghost border border-panel-border" onClick={onClose}>
            Annuler
          </button>
          <button type="button" className="btn btn-primary" onClick={() => void save()} disabled={saving}>
            {saving ? "Enregistrement…" : "Enregistrer"}
          </button>
        </>
      }
    >
      <div className="space-y-3">
        <div className="grid grid-cols-2 items-end gap-3">
          <div>
            <label className="label" htmlFor="c-clear">Clearance minimale</label>
            <div className="flex gap-1.5">
              <input id="c-clear" className="input font-mono" type="number" step="0.05" min={0.05} value={clearance} onChange={(e) => setClearance(e.target.value)} />
              <span className="badge border border-panel-border bg-panel-soft text-ink-dim">mm</span>
            </div>
          </div>
          <div>
            <label className="label" htmlFor="c-trace">Largeur de piste</label>
            <div className="flex gap-1.5">
              <input id="c-trace" className="input font-mono" type="number" step="0.05" min={0.05} value={traceWidth} onChange={(e) => setTraceWidth(e.target.value)} />
              <span className="badge border border-panel-border bg-panel-soft text-ink-dim">mm</span>
            </div>
          </div>
        </div>
        <div>
          <label className="label" htmlFor="c-imp">Impédance cible (nets contrôlés)</label>
          <div className="flex gap-1.5">
            <input id="c-imp" className="input font-mono" type="number" step="1" min={20} max={150} value={impedance} onChange={(e) => setImpedance(e.target.value)} />
            <span className="badge border border-panel-border bg-panel-soft text-ink-dim">Ω</span>
          </div>
        </div>
        <p className="text-[11px] text-ink-dim">
          Impédance différentielle USB : cible {impedance} Ω ±5 %. Ces valeurs sont envoyées à l&rsquo;API (PUT) —
          {saved ? ` dernier enregistrement à ${saved}.` : " aucune modification pour l'instant."}
        </p>
      </div>
    </Modal>
  );
}
