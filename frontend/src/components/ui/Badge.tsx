/** Badge coloré par statut — mapping automatique des statuts d'agents/jobs. */
import type { ReactNode } from "react";

export type BadgeTone = "cyan" | "violet" | "green" | "red" | "amber" | "slate" | "blue";

const TONES: Record<BadgeTone, string> = {
  cyan: "bg-accent-cyan/15 text-accent-cyan border-accent-cyan/30",
  violet: "bg-accent-violet/15 text-accent-violet border-accent-violet/30",
  green: "bg-emerald-400/15 text-emerald-300 border-emerald-400/30",
  red: "bg-rose-500/15 text-rose-300 border-rose-500/30",
  amber: "bg-amber-400/15 text-amber-300 border-amber-400/30",
  blue: "bg-sky-500/15 text-sky-300 border-sky-500/30",
  slate: "bg-panel-soft text-ink-dim border-panel-border",
};

export function Badge({ children, tone = "slate", className = "" }: { children: ReactNode; tone?: BadgeTone; className?: string }) {
  return (
    <span className={`badge border ${TONES[tone]} ${className}`}>{children}</span>
  );
}

/** Mappe un statut libre (API/WS) vers une couleur. */
export function mapStatusTone(status: string): BadgeTone {
  const s = status.toLowerCase();
  if (/(done|pass|ok|valid|completed|connected|ready)/.test(s)) return "green";
  if (/(run|progress|assigned|queued|wait)/.test(s)) return "cyan";
  if (/(fail|error|ko|violat|invalid|down)/.test(s)) return "red";
  if (/(warn|degrad|marginal|mock)/.test(s)) return "amber";
  if (/(violet|review|optimize)/.test(s)) return "violet";
  return "slate";
}

/** Badge de statut automatique (texte affiché en majuscules). */
export function StatusBadge({ status, icon }: { status: string; icon?: string }) {
  return (
    <Badge tone={mapStatusTone(status)}>
      {icon && <span aria-hidden>{icon}</span>}
      <span className="uppercase tracking-wider">{status}</span>
    </Badge>
  );
}
