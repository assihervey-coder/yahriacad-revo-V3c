/** Barre de navigation top — logo, liens actifs, badge crédits live. */
"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { apiClient } from "@/services/api_client";
import type { Credits } from "@/types";

const LINKS: { href: string; label: string }[] = [
  { href: "/projects", label: "Projets" },
  { href: "/designer", label: "Designer" },
  { href: "/simulations", label: "Simulations" },
  { href: "/settings", label: "Paramètres" },
];

export function TopNav() {
  const pathname = usePathname();
  const [credits, setCredits] = useState<Credits | null>(null);

  useEffect(() => {
    let alive = true;
    const load = async () => {
      const c = await apiClient.getCredits();
      if (alive) setCredits(c);
    };
    void load();
    const t = setInterval(load, 60_000);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, []);

  return (
    <header className="sticky top-0 z-40 border-b border-panel-border bg-base/90 backdrop-blur">
      <nav className="mx-auto flex h-14 w-full max-w-[1600px] items-center gap-6 px-4">
        <Link href="/" className="flex items-center gap-2 font-bold tracking-tight">
          <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-gradient-to-br from-accent-cyan to-accent-violet text-[13px] text-base">
            ⟠
          </span>
          <span className="text-[15px]">
            PCB_AI_DESIGNER<span className="text-accent-cyan">_V3</span>
          </span>
        </Link>

        <ul className="flex items-center gap-1 text-sm">
          {LINKS.map((l) => {
            const active = pathname === l.href || pathname.startsWith(`${l.href}/`);
            return (
              <li key={l.href}>
                <Link
                  href={l.href}
                  className={`rounded-lg px-3 py-1.5 transition-colors ${
                    active ? "bg-panel-soft text-accent-cyan" : "text-ink-dim hover:bg-panel-soft hover:text-ink"
                  }`}
                >
                  {l.label}
                </Link>
              </li>
            );
          })}
        </ul>

        <div className="ml-auto flex items-center gap-3">
          {credits && (
            <span
              className="badge border border-accent-violet/30 bg-accent-violet/15 text-accent-violet"
              title={credits.source === "mock" ? "Solde mock (API injoignable)" : `Solde réel du tenant ${credits.tenant}`}
            >
              <span aria-hidden>⚡</span>
              {credits.credits} crédits
              {credits.source === "mock" && <span className="text-amber-300">· mock</span>}
            </span>
          )}
        </div>
      </nav>
    </header>
  );
}
