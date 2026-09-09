/** Page paramètres — API URL, provider LLM, usine cible, device RL (localStorage). */
"use client";

import { useEffect, useState } from "react";
import { CreditDashboard } from "@/components/credit_dashboard/CreditDashboard";
import { Badge } from "@/components/ui/Badge";
import { apiClient } from "@/services/api_client";
import type { AppSettings } from "@/types";

const STORAGE_KEY = "pcb3.settings";

const DEFAULTS: AppSettings = {
  apiUrl: process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000",
  wsUrl: process.env.NEXT_PUBLIC_WS_URL || "ws://localhost:8000",
  llmProvider: "mock",
  factory: "jlcpcb",
  rlDevice: "auto",
};

export default function SettingsPage() {
  const [settings, setSettings] = useState<AppSettings>(DEFAULTS);
  const [saved, setSaved] = useState(false);
  const [health, setHealth] = useState<boolean | null>(null);

  // Chargement initial : localStorage puis sonde /health.
  useEffect(() => {
    try {
      const raw = window.localStorage.getItem(STORAGE_KEY);
      if (raw) {
        const parsed = JSON.parse(raw) as Partial<AppSettings>;
        setSettings({ ...DEFAULTS, ...parsed });
      }
    } catch {
      // localStorage indisponible ou corrompu → défauts
    }
    void apiClient.getHealth().then(setHealth);
  }, []);

  const save = (): void => {
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(settings));
    } catch {
      // quota/permissions — l'app continue avec les valeurs en mémoire
    }
    apiClient.setBaseURL(settings.apiUrl);
    setSaved(true);
    setTimeout(() => setSaved(false), 2500);
    void apiClient.getHealth().then(setHealth);
  };

  return (
    <div className="mx-auto w-full max-w-[760px] px-4 py-8">
      <header className="mb-6">
        <h1 className="text-2xl font-bold">Paramètres</h1>
        <p className="mt-1 text-sm text-ink-dim">
          Configuration persistée en localStorage (clé <span className="font-mono">pcb3.settings</span>).
        </p>
      </header>

      <form
        className="panel space-y-5 p-5"
        onSubmit={(e) => {
          e.preventDefault();
          save();
        }}
      >
        {/* Connexion */}
        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <label className="label" htmlFor="api-url">URL de l&rsquo;API</label>
            <input id="api-url" className="input font-mono text-xs" value={settings.apiUrl} onChange={(e) => setSettings({ ...settings, apiUrl: e.target.value })} placeholder="http://localhost:8000" />
          </div>
          <div>
            <label className="label" htmlFor="ws-url">URL WebSocket live</label>
            <input id="ws-url" className="input font-mono text-xs" value={settings.wsUrl} onChange={(e) => setSettings({ ...settings, wsUrl: e.target.value })} placeholder="ws://localhost:8000" />
          </div>
        </div>
        <div className="flex items-center gap-2 text-xs text-ink-dim">
          État API :
          {health === null ? (
            <Badge tone="slate">test…</Badge>
          ) : health ? (
            <Badge tone="green">joignable</Badge>
          ) : (
            <Badge tone="amber">injoignable — mode mock</Badge>
          )}
        </div>

        {/* IA */}
        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <label className="label" htmlFor="llm">Provider LLM</label>
            <select id="llm" className="input" value={settings.llmProvider} onChange={(e) => setSettings({ ...settings, llmProvider: e.target.value as AppSettings["llmProvider"] })}>
              <option value="mock">mock (déterministe, sans clé)</option>
              <option value="openai">openai</option>
              <option value="zai">zai</option>
            </select>
            <p className="mt-1.5 text-[11px] leading-relaxed text-ink-dim">
              Côté backend, définir <code className="text-cyan-300">LLM_PROVIDER=openai</code> et{" "}
              <code className="text-cyan-300">LLM_API_KEY=sk-…</code> (+{" "}
              <code className="text-cyan-300">LLM_MODEL=gpt-4o-mini</code> au besoin) puis{" "}
              <code className="text-cyan-300">make dev</code>. Le provider{" "}
              <code>mock</code> reste déterministe pour les tests et la démo.
            </p>
          </div>
          <div>
            <label className="label" htmlFor="rl-device">Device RL</label>
            <select id="rl-device" className="input" value={settings.rlDevice} onChange={(e) => setSettings({ ...settings, rlDevice: e.target.value as AppSettings["rlDevice"] })}>
              <option value="auto">auto</option>
              <option value="cpu">cpu (numpy)</option>
              <option value="cuda">cuda (torch)</option>
            </select>
          </div>
        </div>

        {/* Fabrication */}
        <div>
          <label className="label">Usine cible</label>
          <div className="flex gap-2">
            {(["jlcpcb", "pcbway"] as const).map((f) => (
              <button
                key={f}
                type="button"
                onClick={() => setSettings({ ...settings, factory: f })}
                className={`btn flex-1 ${settings.factory === f ? "btn-primary" : "btn-ghost border border-panel-border"}`}
              >
                {f === "jlcpcb" ? "JLCPCB" : "PCBWay"}
              </button>
            ))}
          </div>
          <p className="mt-1.5 text-[11px] text-ink-dim">
            Caps appliquées aux exports : trace min 0.127 mm, perçage min 0.3 mm, 4 couches max (JLCPCB 2/4/6 selon service).
          </p>
        </div>

        <div className="flex items-center justify-between border-t border-panel-border pt-4">
          <p className="text-[11px] text-ink-dim">
            Les URL prennent effet immédiatement pour l&rsquo;API ; le WS est reconnu à la prochaine session live.
          </p>
          <button type="submit" className="btn btn-primary">
            {saved ? "Enregistré ✓" : "Enregistrer"}
          </button>
        </div>
      </form>

      {/* Crédits */}
      <div className="mt-6">
        <CreditDashboard />
      </div>
    </div>
  );
}
