/**
 * RoutingOverlay — traces par net au-dessus de la vue 2D : highlight au
 * survol, tooltip (nom, classe, longueur, impédance) et badge rouge pour les
 * nets non routés.
 */
"use client";

import { useRef, useState } from "react";
import { Badge } from "@/components/ui/Badge";
import { flipY, pathLength, pathPointsAttr, traceColor } from "@/lib/pcb";
import type { DesignSchema, Net } from "@/types";

export interface RoutingOverlayProps {
  design: DesignSchema;
}

interface HoverInfo {
  net: Net;
  px: number;
  py: number;
}

export function RoutingOverlay({ design }: RoutingOverlayProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [hover, setHover] = useState<HoverInfo | null>(null);
  const [w, h] = design.board_size_mm;

  const centerOf = (net: Net): { x: number; y: number } | null => {
    const comp = net.pins.length > 0 ? design.components.find((c) => c.ref === net.pins[0][0]) : undefined;
    const comp2 = net.pins.length > 1 ? design.components.find((c) => c.ref === net.pins[1][0]) : undefined;
    if (comp && comp2) return { x: (comp.x_mm + comp2.x_mm) / 2, y: (comp.y_mm + comp2.y_mm) / 2 };
    if (comp) return { x: comp.x_mm, y: comp.y_mm };
    return null;
  };

  const onEnter = (net: Net, clientX: number, clientY: number): void => {
    const el = containerRef.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    setHover({ net, px: clientX - rect.left, py: clientY - rect.top });
  };

  return (
    <div ref={containerRef} className="absolute inset-0" style={{ pointerEvents: "none" }}>
      <svg viewBox={`-2 -2 ${w + 4} ${h + 4}`} className="h-full w-full" preserveAspectRatio="xMidYMid meet">
        {/* Nets routés : traces cliquables/hover */}
        {design.nets.map((net) => {
          if (net.routed && net.path && net.path.length >= 2) {
            const hovered = hover?.net.net_id === net.net_id;
            return (
              <g key={net.net_id} style={{ pointerEvents: "auto" }}>
                {hovered && (
                  <polyline
                    points={pathPointsAttr(net.path, h)}
                    fill="none"
                    stroke={traceColor(net)}
                    strokeWidth={1.6}
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    opacity={0.25}
                  />
                )}
                <polyline
                  points={pathPointsAttr(net.path, h)}
                  fill="none"
                  stroke={traceColor(net)}
                  strokeWidth={hovered ? 0.9 : 0.45}
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  onMouseEnter={(e) => onEnter(net, e.clientX, e.clientY)}
                  onMouseMove={(e) => onEnter(net, e.clientX, e.clientY)}
                  onMouseLeave={() => setHover(null)}
                  style={{ cursor: "help" }}
                />
                {(net.vias ?? []).map((v, i) => (
                  <circle key={`${net.net_id}-via-${i}`} cx={v.x} cy={flipY(v.y, h)} r={0.45} fill="#d4af37" stroke="#0b0e14" strokeWidth={0.08} />
                ))}
              </g>
            );
          }
          // Non routé : pointillé rouge reliant les deux premiers pads
          const c = centerOf(net);
          if (!c) return null;
          return (
            <g key={net.net_id} style={{ pointerEvents: "auto" }}>
              <circle
                cx={c.x}
                cy={flipY(c.y, h)}
                r={0.9}
                fill="transparent"
                stroke="#fb7185"
                strokeWidth={0.2}
                strokeDasharray="0.5 0.3"
                onMouseEnter={(e) => onEnter(net, e.clientX, e.clientY)}
                onMouseMove={(e) => onEnter(net, e.clientX, e.clientY)}
                onMouseLeave={() => setHover(null)}
                style={{ cursor: "help" }}
              />
              <circle cx={c.x} cy={flipY(c.y, h)} r={0.25} fill="#fb7185" />
            </g>
          );
        })}
      </svg>

      {/* Tooltip */}
      {hover && (
        <div
          className="pointer-events-none absolute z-20 w-max max-w-[240px] rounded-lg border border-panel-border bg-panel/95 p-2.5 shadow-panel backdrop-blur"
          style={{
            left: Math.min(hover.px + 12, (containerRef.current?.clientWidth ?? 300) - 250),
            top: Math.max(4, hover.py - 60),
          }}
        >
          <div className="flex items-center gap-1.5">
            <span className="text-xs font-semibold text-ink">{hover.net.name ?? hover.net.net_id}</span>
            <Badge tone="cyan">{hover.net.class_name ?? "default"}</Badge>
            {!hover.net.routed && <Badge tone="red">non routé</Badge>}
          </div>
          <div className="mt-1 space-y-0.5 text-[11px] text-ink-dim">
            <p>
              Longueur : <span className="font-mono text-ink">{hover.net.routed ? `${pathLength(hover.net.path)} mm` : "—"}</span>
            </p>
            {hover.net.impedance_target_ohm != null && (
              <p>
                Impédance cible : <span className="font-mono text-ink">{hover.net.impedance_target_ohm} Ω</span>
              </p>
            )}
            <p>
              Pads : <span className="font-mono text-ink">{hover.net.pins.length}</span>
            </p>
          </div>
        </div>
      )}
    </div>
  );
}
