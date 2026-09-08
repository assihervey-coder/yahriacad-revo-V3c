/**
 * ProjectsDashboard — tableau des projets : révision, nb composants,
 * qualité (badge couleur), dernière modification.
 */
"use client";

import { useEffect, useMemo, useState } from "react";
import { Badge } from "@/components/ui/Badge";
import { apiClient } from "@/services/api_client";
import type { Project } from "@/types";

/** Qualité pseudo-déterministe par projet (0..100) — le vrai score vient de /designs/{pid}/stats. */
function pseudoQuality(p: Project): number {
  let hash = 0;
  const key = `${p.project_id}:${p.last_rev ?? 0}`;
  for (let i = 0; i < key.length; i += 1) hash = (hash * 31 + key.charCodeAt(i)) % 997;
  return 62 + (hash % 37);
}

function fmtDate(ts?: number): string {
  if (!ts) return "—";
  const ms = ts > 10_000_000_000 ? ts : ts * 1000;
  const d = new Date(ms);
  const now = Date.now();
  const diffMin = Math.round((now - d.getTime()) / 60000);
  if (diffMin < 1) return "à l'instant";
  if (diffMin < 60) return `il y a ${diffMin} min`;
  if (diffMin < 1440) return `il y a ${Math.round(diffMin / 60)} h`;
  return d.toLocaleDateString("fr-FR", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
}

export function ProjectsDashboard({ onSelect }: { onSelect?: (projectId: string) => void }) {
  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState("");

  useEffect(() => {
    let alive = true;
    void (async () => {
      const list = await apiClient.getProjects();
      if (alive) {
        setProjects(list);
        setLoading(false);
      }
    })();
    return () => {
      alive = false;
    };
  }, []);

  const filtered = useMemo(
    () => projects.filter((p) => p.name.toLowerCase().includes(query.toLowerCase())),
    [projects, query],
  );

  if (loading) return <p className="p-4 text-sm text-ink-dim">Chargement des projets…</p>;

  return (
    <div className="space-y-3">
      <input
        className="input max-w-xs"
        placeholder="Filtrer par nom…"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        aria-label="Filtrer les projets"
      />
      <div className="overflow-x-auto">
        <table className="w-full min-w-[560px] text-left text-sm">
          <thead>
            <tr className="border-b border-panel-border text-[11px] uppercase tracking-wider text-ink-dim">
              <th className="px-3 py-2">Projet</th>
              <th className="px-3 py-2">Révision</th>
              <th className="px-3 py-2">Composants</th>
              <th className="px-3 py-2">Qualité</th>
              <th className="px-3 py-2">Dernière modif.</th>
              <th className="px-3 py-2" />
            </tr>
          </thead>
          <tbody>
            {filtered.map((p) => {
              const q = pseudoQuality(p);
              return (
                <tr key={p.project_id} className="border-b border-panel-border/60 transition-colors hover:bg-panel-soft">
                  <td className="px-3 py-2.5">
                    <div className="font-medium text-ink">{p.name}</div>
                    <div className="font-mono text-[11px] text-ink-dim">{p.project_id}</div>
                  </td>
                  <td className="px-3 py-2.5 font-mono text-ink-dim">r{p.last_rev ?? 0}</td>
                  <td className="px-3 py-2.5">{p.component_count ?? "—"}</td>
                  <td className="px-3 py-2.5">
                    <Badge tone={q >= 85 ? "green" : q >= 70 ? "amber" : "red"}>{q}/100</Badge>
                  </td>
                  <td className="px-3 py-2.5 text-ink-dim">{fmtDate(p.updated_ts)}</td>
                  <td className="px-3 py-2.5 text-right">
                    {onSelect && (
                      <button type="button" className="btn btn-primary px-2.5 py-1 text-xs" onClick={() => onSelect(p.project_id)}>
                        Ouvrir
                      </button>
                    )}
                  </td>
                </tr>
              );
            })}
            {filtered.length === 0 && (
              <tr>
                <td colSpan={6} className="px-3 py-6 text-center text-ink-dim">
                  Aucun projet ne correspond.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
