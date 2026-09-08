/**
 * PlacementOverlay — overlay SVG au-dessus de la vue 2D : bbox des composants,
 * drag (souris + tactile) pour déplacer avec snap grille 0.5 mm, refs affichées.
 * Le déplacement est commité via onMove → design_store.moveComponent (PATCH).
 */
"use client";

import { useEffect, useRef, useState } from "react";
import { compRect, refColor, snapGrid } from "@/lib/pcb";
import type { DesignSchema } from "@/types";

export interface PlacementOverlayProps {
  design: DesignSchema;
  /** Commit du déplacement (ref, xMm, yMm) — déjà snappé à 0.5 mm. */
  onMove: (ref: string, xMm: number, yMm: number) => void;
}

interface DragState {
  ref: string;
  startX: number;
  startY: number;
  origX: number;
  origY: number;
  curX: number;
  curY: number;
}

export function PlacementOverlay({ design, onMove }: PlacementOverlayProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const dragRef = useRef<DragState | null>(null);
  const [drag, setDrag] = useState<DragState | null>(null);
  const [w, h] = design.board_size_mm;

  /** Conversion px → mm board (le viewBox a 4 mm de marge, comme la vue 2D). */
  const pxToMm = (): number => {
    const el = containerRef.current;
    if (!el) return 1;
    return (w + 4) / Math.max(1, el.clientWidth);
  };

  const commit = (st: DragState): void => {
    const comp = design.components.find((c) => c.ref === st.ref);
    const [bw, bh] = comp?.bbox_mm ?? [1, 1];
    const x = Math.min(w - bw / 2, Math.max(bw / 2, snapGrid(st.curX)));
    const y = Math.min(h - bh / 2, Math.max(bh / 2, snapGrid(st.curY)));
    onMove(st.ref, x, y);
  };

  // Listeners globaux pendant le drag (souris + tactile).
  useEffect(() => {
    if (!drag) return;
    const scale = pxToMm;
    const move = (clientX: number, clientY: number): void => {
      const st = dragRef.current;
      if (!st) return;
      const s = scale();
      st.curX = snapGrid(st.origX + (clientX - st.startX) * s);
      st.curY = snapGrid(st.origY - (clientY - st.startY) * s); // y inversé (SVG descend)
      setDrag({ ...st });
    };
    const onMouse = (e: MouseEvent): void => {
      e.preventDefault();
      move(e.clientX, e.clientY);
    };
    const onTouch = (e: TouchEvent): void => {
      const t = e.touches[0];
      if (t) {
        e.preventDefault();
        move(t.clientX, t.clientY);
      }
    };
    const up = (): void => {
      const st = dragRef.current;
      if (st) commit(st);
      dragRef.current = null;
      setDrag(null);
    };
    window.addEventListener("mousemove", onMouse, { passive: false });
    window.addEventListener("mouseup", up);
    window.addEventListener("touchmove", onTouch, { passive: false });
    window.addEventListener("touchend", up);
    return () => {
      window.removeEventListener("mousemove", onMouse);
      window.removeEventListener("mouseup", up);
      window.removeEventListener("touchmove", onTouch);
      window.removeEventListener("touchend", up);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [drag !== null, design]);

  const begin = (ref: string, clientX: number, clientY: number): void => {
    const comp = design.components.find((c) => c.ref === ref);
    if (!comp) return;
    const st: DragState = { ref, startX: clientX, startY: clientY, origX: comp.x_mm, origY: comp.y_mm, curX: comp.x_mm, curY: comp.y_mm };
    dragRef.current = st;
    setDrag(st);
  };

  return (
    <div ref={containerRef} className="absolute inset-0" style={{ pointerEvents: "none" }}>
      <svg viewBox={`-2 -2 ${w + 4} ${h + 4}`} className="h-full w-full" preserveAspectRatio="xMidYMid meet">
        {/* Zones draggable */}
        {design.components.map((c) => {
          const r = compRect(c, h);
          return (
            <rect
              key={c.ref}
              x={r.x}
              y={r.y}
              width={r.w}
              height={r.h}
              rx={0.35}
              fill="transparent"
              stroke="transparent"
              strokeWidth={0.3}
              style={{ pointerEvents: "auto", cursor: drag ? "grabbing" : "grab" }}
              onMouseDown={(e) => begin(c.ref, e.clientX, e.clientY)}
              onTouchStart={(e) => {
                const t = e.touches[0];
                if (t) begin(c.ref, t.clientX, t.clientY);
              }}
            >
              <title>{`${c.ref} — glisser pour déplacer (snap 0.5 mm)`}</title>
            </rect>
          );
        })}

        {/* Ghost pendant le drag */}
        {drag && (
          <g>
            {(() => {
              const comp = design.components.find((c) => c.ref === drag.ref);
              if (!comp) return null;
              const [bw, bh] = comp.bbox_mm;
              return (
                <rect
                  x={drag.curX - bw / 2}
                  y={h - drag.curY - bh / 2}
                  width={bw}
                  height={bh}
                  rx={0.35}
                  fill="#22D3EE"
                  fillOpacity={0.15}
                  stroke="#22D3EE"
                  strokeWidth={0.25}
                  strokeDasharray="0.6 0.3"
                  style={{ pointerEvents: "none" }}
                />
              );
            })()}
            <text
              x={drag.curX}
              y={h - drag.curY - 1.2}
              textAnchor="middle"
              fontSize={1.5}
              fill="#22D3EE"
              style={{ pointerEvents: "none", userSelect: "none" }}
            >
              {drag.ref} · {drag.curX.toFixed(1)}, {drag.curY.toFixed(1)} mm
            </text>
          </g>
        )}
      </svg>
    </div>
  );
}
