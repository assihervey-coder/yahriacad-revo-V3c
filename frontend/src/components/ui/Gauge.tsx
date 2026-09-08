/** Jauges SVG réutilisables — circulaire (score) et barre horizontale (breakdown). */

export interface GaugeProps {
  value: number;
  max?: number;
  label?: string;
  unit?: string;
  /** Diamètre en px. */
  size?: number;
  color?: string;
  sublabel?: string;
}

const PALETTE: Record<string, string> = {
  good: "#34d399",
  warn: "#fbbf24",
  bad: "#fb7185",
  cyan: "#22D3EE",
  violet: "#A78BFA",
};

/** Choisit une couleur selon le ratio 0..1. */
export function ratioColor(ratio: number): string {
  if (ratio >= 0.8) return PALETTE.good;
  if (ratio >= 0.55) return PALETTE.warn;
  return PALETTE.bad;
}

/** Jauge circulaire SVG (score qualité, crédits, ...). */
export function Gauge({ value, max = 100, label, unit = "", size = 132, color, sublabel }: GaugeProps) {
  const clamped = Math.max(0, Math.min(value, max));
  const ratio = max > 0 ? clamped / max : 0;
  const stroke = 10;
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const filled = c * ratio;
  const col = color ?? ratioColor(ratio);
  const center = size / 2;

  return (
    <div className="flex flex-col items-center gap-1">
      <svg width={size} height={size} role="img" aria-label={`${label ?? "jauge"} : ${clamped}`}>
        <circle cx={center} cy={center} r={r} fill="none" stroke="#232A38" strokeWidth={stroke} />
        <circle
          cx={center}
          cy={center}
          r={r}
          fill="none"
          stroke={col}
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={`${filled} ${c - filled}`}
          transform={`rotate(-90 ${center} ${center})`}
        />
        <text x={center} y={center - 2} textAnchor="middle" className="fill-ink" fontSize={size / 4.2} fontWeight="700">
          {Math.round(clamped * 10) / 10}
          <tspan fontSize={size / 10} className="fill-ink-dim">{unit}</tspan>
        </text>
        {label && (
          <text x={center} y={center + size / 5.5} textAnchor="middle" fontSize={size / 12} className="fill-ink-dim">
            {label}
          </text>
        )}
      </svg>
      {sublabel && <span className="text-xs text-ink-dim">{sublabel}</span>}
    </div>
  );
}

export interface BarGaugeProps {
  value: number;
  max?: number;
  label?: string;
  right?: string;
  color?: string;
  height?: number;
}

/** Barre de progression horizontale (breakdown qualité, IR drop...). */
export function BarGauge({ value, max = 100, label, right, color, height = 8 }: BarGaugeProps) {
  const ratio = max > 0 ? Math.max(0, Math.min(1, value / max)) : 0;
  const col = color ?? ratioColor(ratio);
  return (
    <div className="w-full">
      {(label || right) && (
        <div className="mb-1 flex items-baseline justify-between text-xs">
          <span className="text-ink-dim">{label}</span>
          <span className="font-mono text-ink">{right}</span>
        </div>
      )}
      <div className="w-full overflow-hidden rounded-full bg-panel-border" style={{ height }}>
        <div className="h-full rounded-full transition-all" style={{ width: `${ratio * 100}%`, backgroundColor: col }} />
      </div>
    </div>
  );
}
