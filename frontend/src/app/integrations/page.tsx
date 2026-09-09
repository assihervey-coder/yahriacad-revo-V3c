/**
 * Page Intégrations — ponts EDA réels de la plateforme.
 *
 *  - KiCad    : import (netlist / .kicad_pcb / schéma JSON / session PCB),
 *               export .kicad_pcb + netlist, push live WebSocket ;
 *  - Altium   : import / export du pont JSON + synchronisation (conflits) ;
 *  - Sessions : sauvegarde atomique, listing, restauration (graphe+versioning) ;
 *  - Surrogates β : état des substituts neuronaux (échantillons, R², latence)
 *               + entraînement manuel ;
 *  - Optimiseur autonome : propositions RL/LLM après verdict VALID.
 */
"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { apiClient } from "@/services/api_client";
import type { SessionMeta, SurrogateStatusEntry } from "@/services/api_client";
import { useProjectStore, selectDefaultProject } from "@/stores/project_store";
import { Panel } from "@/components/ui/Panel";
import { Badge } from "@/components/ui/Badge";

const KICAD_SAMPLE = `(export (version "E")
  (components
    (comp (ref "U1") (value "ESP32-WROOM-32E"))
    (comp (ref "R1") (value "10k")))
  (nets
    (net (code 1) (name "PWR")
      (node (ref "U1") (pin "1")) (node (ref "R1") (pin "2")))))`;

const ALTIUM_SAMPLE = {
  components: [
    { ref: "U1", value: "MCU", footprint: "QFN-16_0.5mm", x: 12, y: 12,
      pads: [{ name: "1", x: -1.5, y: 0, net_id: "PWR" }, { name: "2", x: 1.5, y: 0, net_id: "GND" }] },
    { ref: "C1", value: "100n", footprint: "C_0402_1005Metric", x: 20, y: 12,
      pads: [{ name: "1", x: -0.5, y: 0, net_id: "PWR" }, { name: "2", x: 0.5, y: 0, net_id: "GND" }] },
  ],
  nets: [{ net_id: "PWR" }, { net_id: "GND" }],
  board_size: { w: 40, h: 30 },
};

type Line = { text: string; tone?: "ok" | "err" | "info" };

function logAppend(setLog: React.Dispatch<React.SetStateAction<Line[]>>, line: Line) {
  setLog((prev) => [...prev.slice(-40), line]);
}

export default function IntegrationsPage() {
  const current = useProjectStore(selectDefaultProject);
  const projectId = current?.project_id ?? "";

  const [kicadText, setKicadText] = useState("");
  const [altiumText, setAltiumText] = useState("");
  const [sessions, setSessions] = useState<SessionMeta[]>([]);
  const [surrogates, setSurrogates] = useState<Record<string, SurrogateStatusEntry>>({});
  const [minSamples, setMinSamples] = useState(25);
  const [log, setLog] = useState<Line[]>([]);
  const [busy, setBusy] = useState("");

  useEffect(() => {
    void apiClient.listSessions().then(setSessions);
    void apiClient.surrogateStatus().then((s) => {
      if (s) {
        setSurrogates(s.surrogates ?? {});
        setMinSamples(s.min_samples ?? 25);
      }
    });
  }, []);

  const say = useCallback((text: string, tone: Line["tone"] = "info") => {
    logAppend(setLog, { text, tone });
  }, []);

  // ------------------------------------------------------------- actions
  const doKicadImport = async () => {
    setBusy("kicad-import");
    const r = await apiClient.importKiCad(kicadText, "");
    say(r.ok
      ? `KiCad importé → projet ${r.project_id} (${r.format} : ${r.stats?.components ?? "?"} composants, ${r.stats?.nets ?? "?"} nets)`
      : `Échec import KiCad : ${r.detail ?? "inconnu"}`, r.ok ? "ok" : "err");
    setBusy("");
  };

  const doKicadExport = async () => {
    if (!projectId) return say("Sélectionne un projet d'abord", "err");
    setBusy("kicad-export");
    const files = await apiClient.exportKiCad(projectId, "both");
    if (files) {
      for (const [name, f] of Object.entries(files)) {
        say(`Export KiCad ${name} : ${f.bytes} octets → ${f.path}`, "ok");
      }
    } else {
      say("Échec export KiCad (API injoignable ou design absent)", "err");
    }
    setBusy("");
  };

  const doKicadLive = async () => {
    if (!projectId) return say("Sélectionne un projet d'abord", "err");
    setBusy("kicad-live");
    const r = await apiClient.kicadLivePush(projectId);
    say(r?.pushed ? "Design poussé vers KiCad live" : (r?.detail ?? "KiCad offline (aucun pont WebSocket sur ws://localhost:7999)"), r?.pushed ? "ok" : "err");
    setBusy("");
  };

  const doAltiumImport = async () => {
    setBusy("altium-import");
    let payload: unknown;
    try {
      payload = JSON.parse(altiumText || JSON.stringify(ALTIUM_SAMPLE));
    } catch {
      setBusy("");
      return say("JSON Altium invalide", "err");
    }
    const r = await apiClient.importAltium(payload, "");
    say(r.ok ? `Altium importé → projet ${r.project_id}` : `Échec import Altium : ${r.detail ?? "?"}`, r.ok ? "ok" : "err");
    setBusy("");
  };

  const doAltiumExport = async () => {
    if (!projectId) return say("Sélectionne un projet d'abord", "err");
    setBusy("altium-export");
    const payload = await apiClient.exportAltium(projectId);
    say(payload ? `Export Altium OK (${Object.keys(payload).join(", ")})` : "Échec export Altium", payload ? "ok" : "err");
    setBusy("");
  };

  const doAltiumSync = async () => {
    if (!projectId) return say("Sélectionne un projet d'abord", "err");
    setBusy("altium-sync");
    const report = await apiClient.syncAltium(projectId, ALTIUM_SAMPLE, "local_wins");
    const sync = (report as { sync?: Record<string, unknown> } | null)?.sync;
    say(sync ? `Sync Altium : résolution ${sync.resolution}${Array.isArray(sync.changed_components) && sync.changed_components.length ? `, changements ${JSON.stringify(sync.changed_components)}` : ""}` : "Échec sync Altium", sync ? "ok" : "err");
    setBusy("");
  };

  const refreshSessions = async () => {
    setSessions(await apiClient.listSessions());
    say("Sessions rafraîchies");
  };

  const doSaveSession = async () => {
    if (!projectId) return say("Sélectionne un projet d'abord", "err");
    setBusy("session-save");
    const r = await apiClient.saveSession(projectId);
    say(r?.saved ? `Session sauvegardée → ${r.path}` : "Échec sauvegarde session", r?.saved ? "ok" : "err");
    if (r?.saved) await refreshSessions();
    setBusy("");
  };

  const doRestoreSession = async (pid: string) => {
    setBusy(`session-restore-${pid}`);
    const r = await apiClient.restoreSession(pid, true);
    const applied = (r as { applied_revision?: number } | null)?.applied_revision;
    const stats = (r as { stats?: Record<string, unknown> } | null)?.stats;
    say(r ? `Session restaurée (rev ${applied ?? "?"}) : ${stats?.components ?? "?"} composants` : "Échec restauration", r ? "ok" : "err");
    setBusy("");
  };

  const doTrainSurrogates = async () => {
    setBusy("surrogate-train");
    const r = await apiClient.trainSurrogates();
    say(r ? `Surrogates entraînés : ${r.count}` : "Entraînement impossible (pas assez d'échantillons ?)", r && r.count > 0 ? "ok" : "info");
    const s = await apiClient.surrogateStatus();
    if (s) setSurrogates(s.surrogates ?? {});
    setBusy("");
  };

  // ------------------------------------------------------------- rendu
  return (
    <main className="mx-auto w-full max-w-[1400px] px-4 py-8">
      <div className="mb-6 flex items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Intégrations EDA</h1>
          <p className="mt-1 text-sm text-ink/60">
            Ponts pcb_plugin : KiCad (import/export/live) · Altium (bridge + sync) · session_restorer ·
            surrogates neuronaux β · optimiseur autonome (propositions RL/LLM après verdict VALID).
          </p>
        </div>
        <div className="text-right text-sm">
          <div className="text-ink/60">Projet courant</div>
          {projectId ? (
            <span className="font-mono text-accent-cyan">{projectId.slice(0, 18)}…</span>
          ) : (
            <Link href="/projects" className="text-accent-cyan underline">sélectionner un projet</Link>
          )}
        </div>
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        {/* ---- KiCad ---- */}
        <Panel title="KiCad" subtitle="import / export / live (pcbnew WebSocket)" right={<Badge tone="cyan">pcb_plugin</Badge>}>
          <textarea
            className="input h-40 w-full resize-none font-mono text-xs"
            placeholder={KICAD_SAMPLE}
            value={kicadText}
            onChange={(e) => setKicadText(e.target.value)}
          />
          <div className="mt-3 flex flex-wrap gap-2">
            <button className="btn" disabled={busy === "kicad-import"} onClick={() => void doKicadImport()}>
              Importer (netlist / .kicad_pcb / JSON)
            </button>
            <button className="btn" disabled={busy === "kicad-export" || !projectId} onClick={() => void doKicadExport()}>
              Exporter .kicad_pcb + netlist
            </button>
            <button className="btn" disabled={busy === "kicad-live" || !projectId} onClick={() => void doKicadLive()}>
              Push live
            </button>
          </div>
          <p className="mt-2 text-xs text-ink/50">
            Import auto-détecté : netlist s-expression, .kicad_pcb, schéma JSON, session PCB, pont Altium.
          </p>
        </Panel>

        {/* ---- Altium ---- */}
        <Panel title="Altium Designer" subtitle="bridge JSON + synchronisation" right={<Badge tone="violet">actif</Badge>}>
          <textarea
            className="input h-40 w-full resize-none font-mono text-xs"
            placeholder="JSON du pont Altium {components, nets, board_size…} — vide = exemple"
            value={altiumText}
            onChange={(e) => setAltiumText(e.target.value)}
          />
          <div className="mt-3 flex flex-wrap gap-2">
            <button className="btn" disabled={busy === "altium-import"} onClick={() => void doAltiumImport()}>
              Importer
            </button>
            <button className="btn" disabled={busy === "altium-export" || !projectId} onClick={() => void doAltiumExport()}>
              Exporter JSON
            </button>
            <button className="btn" disabled={busy === "altium-sync" || !projectId} onClick={() => void doAltiumSync()}>
              Synchroniser (local_wins)
            </button>
          </div>
          <p className="mt-2 text-xs text-ink/50">
            La sync compare (ref, position, nets) par composant et remonte les conflits modifiés des deux côtés.
          </p>
        </Panel>

        {/* ---- Sessions ---- */}
        <Panel title="Sessions" subtitle="sauvegarde atomique graphe + versioning" right={<Badge tone="slate">session_restorer</Badge>}>
          <div className="flex gap-2">
            <button className="btn" disabled={busy === "session-save" || !projectId} onClick={() => void doSaveSession()}>
              Sauvegarder le projet courant
            </button>
            <button className="btn" onClick={() => void refreshSessions()}>Rafraîchir</button>
          </div>
          <div className="mt-3 max-h-48 overflow-y-auto">
            {sessions.length === 0 ? (
              <p className="text-sm text-ink/50">Aucune session sauvegardée.</p>
            ) : (
              <table className="w-full text-left text-xs">
                <thead className="text-ink/50">
                  <tr><th className="py-1">Projet</th><th>Nom</th><th>Âge</th><th></th></tr>
                </thead>
                <tbody>
                  {sessions.map((s) => (
                    <tr key={`${s.user_id}/${s.project_id}`} className="border-t border-panel-border/50">
                      <td className="py-1 font-mono">{s.project_id.slice(0, 14)}…</td>
                      <td>{s.name || "—"}</td>
                      <td>{formatAge(s.saved_at)}</td>
                      <td>
                        <button
                          className="text-accent-cyan hover:underline"
                          disabled={busy.startsWith("session-restore")}
                          onClick={() => void doRestoreSession(s.project_id)}
                        >
                          restaurer + appliquer
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </Panel>

        {/* ---- Surrogates β ---- */}
        <Panel title="Surrogates neuronaux" subtitle="inférence rapide à la place du solveur complet" right={<Badge tone="amber">bêta</Badge>}>
          <div className="grid gap-2 sm:grid-cols-2">
            {["thermal", "si", "pi", "emi"].map((kind) => {
              const st: SurrogateStatusEntry | undefined = surrogates[kind];
              return (
                <div key={kind} className="rounded-lg border border-panel-border/60 p-2.5">
                  <div className="flex items-center justify-between">
                    <span className="font-semibold">{kind}</span>
                    <Badge tone={st?.trained ? "green" : "slate"}>{st?.trained ? "entraîné" : "collecte"}</Badge>
                  </div>
                  <div className="mt-1 text-xs text-ink/60">
                    échantillons {st?.n_samples ?? 0}/{minSamples}
                    {st?.r2 != null && <> · R² {st.r2.toFixed(3)}</>}
                    {st?.last_latency_ms != null && <> · {st.last_latency_ms.toFixed(3)} ms</>}
                  </div>
                </div>
              );
            })}
          </div>
          <button className="btn mt-3" disabled={busy === "surrogate-train"} onClick={() => void doTrainSurrogates()}>
            Entraîner maintenant
          </button>
          <p className="mt-2 text-xs text-ink/50">
            Chaque simulation complète alimente le dataset (JSONL persistant) ; dès le seuil d&apos;échantillons
            le surrogate remplace le solveur complet dans la boucle multi-physique et l&apos;agent simulation.
          </p>
        </Panel>

        {/* ---- Optimiseur autonome ---- */}
        <Panel
          title="Optimiseur autonome"
          subtitle="propositions RL + LLM + world model, porte verdict VALID"
          right={<Badge tone="green">AUTO</Badge>}
          className="lg:col-span-2"
        >
          <p className="text-sm text-ink/70">
            L&apos;AutonomousOptimizer n&apos;intervient QUE lorsque le SelfVerifier rend un verdict VALID :
            les proposers (LLM, RL, world model en imagination MPC) génèrent des mouvements, évalués par le
            FastEvaluator, arbitrés par le keeper (aucune régression acceptée). En verdict INVALID, le
            correcteur prend la main (chaîne neck-down → re-routage → rollback). Le pipeline complet
            <code className="mx-1 rounded bg-panel px-1">reoptimize</code> (verify → optimize → verify → export)
            est aussi lancable depuis le <Link href="/designer" className="text-accent-cyan hover:underline">Designer</Link>.
          </p>
          <p className="mt-2 text-xs text-ink/50">
            API : <code className="rounded bg-panel px-1">POST /api/v1/optimization/&#123;project_id&#125;/proposals</code> ·
            409 + issues si verdict INVALID · <code className="rounded bg-panel px-1">apply=true</code> pour
            committer le meilleur graphe comme nouvelle révision.
          </p>
        </Panel>

        {/* ---- Journal ---- */}
        <Panel title="Journal d'activité" subtitle="résultats des opérations d'intégration" className="lg:col-span-2">
          <div className="max-h-56 overflow-y-auto font-mono text-xs">
            {log.length === 0 ? (
              <p className="text-ink/50">Les actions des ponts EDA apparaîtront ici.</p>
            ) : (
              log.map((l, i) => (
                <p key={i} className={l.tone === "ok" ? "text-emerald-400" : l.tone === "err" ? "text-red-400" : "text-ink/70"}>
                  <span className="text-ink/40">›</span> {l.text}
                </p>
              ))
            )}
          </div>
        </Panel>
      </div>
    </main>
  );
}

function formatAge(ts: number): string {
  if (!ts) return "—";
  const s = Math.max(0, Date.now() / 1000 - ts);
  if (s < 60) return `${Math.round(s)} s`;
  if (s < 3600) return `${Math.round(s / 60)} min`;
  if (s < 86400) return `${Math.round(s / 3600)} h`;
  return `${Math.round(s / 86400)} j`;
}
