/** Panneau réutilisable — bloc #12161F, coins 12px, header optionnel. */
import type { ReactNode } from "react";

export interface PanelProps {
  title?: string;
  subtitle?: string;
  /** Slot à droite du header (boutons, badges...). */
  right?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
  /** Désactive le padding interne (viewer, heatmaps...). */
  flush?: boolean;
}

export function Panel({ title, subtitle, right, children, className = "", bodyClassName = "", flush = false }: PanelProps) {
  return (
    <section className={`panel flex min-h-0 flex-col ${className}`}>
      {(title || right) && (
        <header className="flex shrink-0 items-center justify-between gap-2 border-b border-panel-border px-4 py-3">
          <div className="min-w-0">
            {title && <h2 className="truncate text-sm font-semibold tracking-wide text-ink">{title}</h2>}
            {subtitle && <p className="truncate text-xs text-ink-dim">{subtitle}</p>}
          </div>
          {right && <div className="flex shrink-0 items-center gap-2">{right}</div>}
        </header>
      )}
      <div className={`min-h-0 flex-1 ${flush ? "" : "p-4"} ${bodyClassName}`}>{children}</div>
    </section>
  );
}
