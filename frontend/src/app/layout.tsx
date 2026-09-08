/** Layout racine — dark premium, nav top, contenu centré. */
import type { Metadata } from "next";
import type { ReactNode } from "react";
import { TopNav } from "@/components/layout/TopNav";
import "./globals.css";

export const metadata: Metadata = {
  title: "PCB_AI_DESIGNER_V3 — EDA AI-native",
  description: "De l'intention au Gerber : orchestration d'agents AI pour la conception PCB (placement, routage, vérification, fabrication).",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="fr">
      <body className="min-h-screen bg-base text-ink">
        <TopNav />
        {children}
      </body>
    </html>
  );
}
