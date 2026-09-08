/** Landing — « De l'intention au Gerber » : 3 cerveaux, flux V3 en 6 étapes, CTA. */
import Link from "next/link";

const BRAINS = [
  {
    emoji: "🧠",
    title: "Cerveau symbolique",
    desc: "LLM orchestré + RAG (datasheets, IPC-2221/2581) + Knowledge Graph : l'intention en langage naturel devient une netlist, un BOM et des contraintes explicites.",
    tone: "text-accent-violet",
    ring: "border-accent-violet/30",
  },
  {
    emoji: "🤖",
    title: "Cerveau décisionnel",
    desc: "Agent RL + optimiseur autonome (recuit, évolution, bayésien) : placement et routage proposés, évalués, tenus ou rollbackés — seules les révisions validées sont gardées.",
    tone: "text-accent-cyan",
    ring: "border-accent-cyan/30",
  },
  {
    emoji: "🔬",
    title: "Cerveau physique",
    desc: "Thermique, signal integrity, power integrity, CEM + self-vérification (DRC/ERC/DFM) : chaque proposition est prouvée avant d'atteindre le Gerber.",
    tone: "text-emerald-300",
    ring: "border-emerald-400/30",
  },
] as const;

const FLOW = [
  { step: "1", title: "Intention", desc: "« Conçois une carte ESP32 4 couches avec BME680 sur USB-C »" },
  { step: "2", title: "Sélection", desc: "Netlist, BOM et footprints depuis la bibliothèque + le KG" },
  { step: "3", title: "Placement", desc: "Recuit + RL, contraintes thermiques et keepouts respectés" },
  { step: "4", title: "Routage", desc: "A* multicouche, impédances cibles, minimisation de vias" },
  { step: "5", title: "Vérification", desc: "DRC/ERC/DFM + simulations physiques, score qualité" },
  { step: "6", title: "Export", desc: "Gerber RS-274X, Excellon, BOM, POS, IPC-2581 — prêt usine" },
] as const;

export default function LandingPage() {
  return (
    <div className="mx-auto w-full max-w-[1200px] px-4">
      {/* Hero */}
      <section className="flex flex-col items-center py-20 text-center">
        <span className="badge border border-accent-cyan/30 bg-accent-cyan/10 text-accent-cyan">
          Plateforme EDA AI-native · orchestration 10 agents
        </span>
        <h1 className="mt-6 max-w-3xl text-5xl font-extrabold leading-tight tracking-tight md:text-6xl">
          De l&rsquo;<span className="text-accent-cyan">intention</span> au{" "}
          <span className="bg-gradient-to-r from-accent-cyan to-accent-violet bg-clip-text text-transparent">Gerber</span>
        </h1>
        <p className="mt-5 max-w-2xl text-lg text-ink-dim">
          Décrivez votre carte en langage naturel. Trois cerveaux IA conçoivent, routent,
          vérifient et exportent votre PCB — chaque décision est événementielle, vérifiée et réversible.
        </p>
        <div className="mt-8 flex flex-wrap items-center justify-center gap-3">
          <Link href="/designer" className="btn btn-primary px-6 py-3 text-[15px]">
            Lancer le designer →
          </Link>
          <Link href="/projects" className="btn btn-ghost border border-panel-border px-6 py-3 text-[15px]">
            Voir les projets
          </Link>
        </div>
      </section>

      {/* 3 cerveaux */}
      <section className="grid gap-4 pb-16 md:grid-cols-3">
        {BRAINS.map((b) => (
          <article key={b.title} className={`panel border ${b.ring} p-6`}>
            <div className="text-3xl" aria-hidden>{b.emoji}</div>
            <h2 className={`mt-3 text-lg font-semibold ${b.tone}`}>{b.title}</h2>
            <p className="mt-2 text-sm leading-relaxed text-ink-dim">{b.desc}</p>
          </article>
        ))}
      </section>

      {/* Flux V3 en 6 étapes */}
      <section className="pb-20">
        <h2 className="mb-6 text-center text-sm font-semibold uppercase tracking-[0.2em] text-ink-dim">
          Le flux V3 — intentionnel de bout en bout
        </h2>
        <ol className="grid gap-3 md:grid-cols-6">
          {FLOW.map((f) => (
            <li key={f.step} className="panel p-4">
              <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-accent-cyan/15 font-mono text-sm text-accent-cyan">
                {f.step}
              </div>
              <h3 className="mt-3 text-sm font-semibold">{f.title}</h3>
              <p className="mt-1 text-xs leading-relaxed text-ink-dim">{f.desc}</p>
            </li>
          ))}
        </ol>
      </section>

      {/* CTA final */}
      <section className="panel mb-16 flex flex-col items-center gap-4 border border-accent-violet/25 p-10 text-center">
        <h2 className="text-2xl font-bold">Prêt à concevoir votre première carte ?</h2>
        <p className="max-w-xl text-sm text-ink-dim">
          Ouvrez le designer : chat d&rsquo;intention, viewer 3D temps réel, activité des agents,
          simulations et export de fabrication dans une seule interface.
        </p>
        <Link href="/designer" className="btn btn-violet px-6 py-3 text-[15px]">
          Ouvrir le designer 🚀
        </Link>
      </section>
    </div>
  );
}
