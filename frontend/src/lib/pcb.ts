/** Helpers géométrie/couleur partagés par les vues et overlays PCB. */
import type { Component, Net, Point } from "@/types";

/** Inverse l'axe Y (SVG y descend, PCB y monte). */
export function flipY(y: number, boardH: number): number {
  return boardH - y;
}

/** Rectangle d'un composant en coordonnées SVG (coin haut-gauche). */
export function compRect(c: Component, boardH: number): { x: number; y: number; w: number; h: number } {
  const [bw, bh] = c.bbox_mm;
  const ry = flipY(c.y_mm, boardH);
  return { x: c.x_mm - bw / 2, y: ry - bh / 2, w: bw, h: bh };
}

/** Points d'un path de net en coordonnées SVG (attribut points d'une polyline). */
export function pathPointsAttr(path: Point[] | undefined, boardH: number): string {
  if (!path) return "";
  return path.map((p) => `${p.x},${flipY(p.y, boardH)}`).join(" ");
}

/** Longueur d'un path en mm (somme des segments). */
export function pathLength(path: Point[] | undefined): number {
  if (!path || path.length < 2) return 0;
  let total = 0;
  for (let i = 1; i < path.length; i += 1) {
    total += Math.hypot(path[i].x - path[i - 1].x, path[i].y - path[i - 1].y);
  }
  return Math.round(total * 10) / 10;
}

/** Couleur d'une trace selon la classe du net. */
export function traceColor(net: Net): string {
  switch (net.class_name) {
    case "power":
      return "#f59e0b";
    case "high_speed":
      return "#22D3EE";
    case "differential":
      return "#A78BFA";
    case "analog":
      return "#34d399";
    default:
      return "#60a5fa";
  }
}

const REF_COLORS: Record<string, string> = {
  U: "#A78BFA", // CI
  C: "#22D3EE", // condensateurs
  R: "#64748B", // résistances
  J: "#f59e0b", // connecteurs
  D: "#34d399", // diodes
  L: "#fb923c", // inductances
  S: "#f472b6", // switches
  Y: "#60a5fa", // cristaux
  Q: "#4ade80", // transistors
};

/** Couleur d'un composant par préfixe de ref. */
export function refColor(ref: string): string {
  return REF_COLORS[ref.charAt(0).toUpperCase()] ?? "#94a3b8";
}

/** Snap à une grille de 0.5 mm. */
export function snapGrid(v: number, step = 0.5): number {
  return Math.round(v / step) * step;
}
