import { useEffect, useId, useRef, useState } from "react";

/**
 * Small, dependency-free charts. They only plot values that are already in the bundle
 * -- scaling a value to a pixel position is the only arithmetic here. Every chart is
 * rendered at its real pixel width (measured), so labels stay legible on a phone
 * instead of shrinking with a fixed viewBox.
 */

export function useElementWidth<T extends HTMLElement>(fallback = 640) {
  const ref = useRef<T>(null);
  const [width, setWidth] = useState(fallback);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const update = () => setWidth(el.clientWidth || fallback);
    update();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(update);
    observer.observe(el);
    return () => observer.disconnect();
  }, [fallback]);
  return [ref, width] as const;
}

export type PointTone =
  | "locked" | "rejected" | "reference" | "promising" | "experimental"
  | "neutral" | "frontier" | "dominated";

export interface ScatterPoint {
  id: string;
  label: string;
  x: number;
  y: number;
  tone: PointTone;
  showLabel?: boolean;
  /** Put the label under the marker instead of above it, to avoid a neighbour's label. */
  labelBelow?: boolean;
  detail?: string;
}

export interface ChartAxis {
  label: string;
  domain: [number, number];
  ticks: number[];
  format: (v: number) => string;
}

/** Marker shapes differ by tone, so a point's category never depends on colour alone. */
function Marker({ tone, cx, cy }: { tone: PointTone; cx: number; cy: number }) {
  switch (tone) {
    case "locked":
      return (
        <>
          <circle cx={cx} cy={cy} r={11} className="mk-ring" />
          <circle cx={cx} cy={cy} r={6} className="mk-fill" />
        </>
      );
    case "rejected":
      return (
        <path className="mk-stroke" d={`M${cx - 5},${cy - 5}L${cx + 5},${cy + 5}M${cx + 5},${cy - 5}L${cx - 5},${cy + 5}`} />
      );
    case "reference":
      return <rect className="mk-hollow" x={cx - 5} y={cy - 5} width={10} height={10} />;
    case "promising":
      return <path className="mk-hollow" d={`M${cx},${cy - 7}L${cx + 7},${cy}L${cx},${cy + 7}L${cx - 7},${cy}Z`} />;
    case "experimental":
      return <path className="mk-hollow" d={`M${cx},${cy - 7}L${cx + 7},${cy + 6}L${cx - 7},${cy + 6}Z`} />;
    case "frontier":
      return <path className="mk-fill" d={`M${cx},${cy - 8}L${cx + 8},${cy}L${cx},${cy + 8}L${cx - 8},${cy}Z`} />;
    case "dominated":
      return <circle cx={cx} cy={cy} r={4} className="mk-hollow" />;
    default:
      return <circle cx={cx} cy={cy} r={5} className="mk-hollow" />;
  }
}

export function LegendSwatch({ tone }: { tone: PointTone }) {
  return (
    <svg width={22} height={22} aria-hidden="true" className={`pt pt-${tone}`}>
      <Marker tone={tone} cx={11} cy={11} />
    </svg>
  );
}

export function ScatterChart({
  ariaLabel,
  points,
  x,
  y,
  lines = [],
  height = 340,
  legend,
}: {
  ariaLabel: string;
  points: ScatterPoint[];
  x: ChartAxis;
  y: ChartAxis;
  lines?: { id: string; label: string; points: { x: number; y: number }[] }[];
  height?: number;
  legend?: { tone: PointTone | "line"; label: string }[];
}) {
  const [ref, measured] = useElementWidth<HTMLDivElement>();
  const [active, setActive] = useState<string | null>(null);
  const width = Math.max(300, measured);
  const narrow = width < 520;
  const m = { top: 20, right: narrow ? 14 : 28, bottom: 48, left: 60 };
  const innerW = width - m.left - m.right;
  const innerH = height - m.top - m.bottom;
  const sx = (v: number) => m.left + ((v - x.domain[0]) / (x.domain[1] - x.domain[0])) * innerW;
  const sy = (v: number) => m.top + (1 - (v - y.domain[0]) / (y.domain[1] - y.domain[0])) * innerH;
  const current = points.find((p) => p.id === active) ?? null;
  const clipId = `plot-${useId().replace(/[^a-zA-Z0-9_-]/g, "")}`;

  return (
    <div className="chart" ref={ref}>
      <svg width={width} height={height} role="group" aria-label={ariaLabel}>
        <defs>
          <clipPath id={clipId}>
            <rect x={m.left} y={m.top} width={innerW} height={innerH} />
          </clipPath>
        </defs>
        {y.ticks.map((t) => (
          <g key={`y-${t}`} aria-hidden="true">
            <line className="gridline" x1={m.left} x2={width - m.right} y1={sy(t)} y2={sy(t)} />
            <text className="tick" x={m.left - 8} y={sy(t)} textAnchor="end" dominantBaseline="middle">
              {y.format(t)}
            </text>
          </g>
        ))}
        {x.ticks.map((t) => (
          <g key={`x-${t}`} aria-hidden="true">
            <line className="gridline" x1={sx(t)} x2={sx(t)} y1={m.top} y2={height - m.bottom} />
            <text className="tick" x={sx(t)} y={height - m.bottom + 18} textAnchor="middle">
              {x.format(t)}
            </text>
          </g>
        ))}
        <text className="axis-label" x={m.left + innerW / 2} y={height - 8} textAnchor="middle" aria-hidden="true">
          {x.label}
        </text>
        <text className="axis-label" aria-hidden="true" textAnchor="middle"
          transform={`translate(16 ${m.top + innerH / 2}) rotate(-90)`}>
          {y.label}
        </text>
        {lines.map((l) => (
          <polyline key={l.id} className="series" aria-hidden="true" clipPath={`url(#${clipId})`}
            points={l.points.map((p) => `${sx(p.x).toFixed(1)},${sy(p.y).toFixed(1)}`).join(" ")} />
        ))}
        {points.map((p) => {
          const cx = sx(p.x);
          const cy = sy(p.y);
          const flip = cx > width - 170;
          const showLabel = p.showLabel && (!narrow || p.tone === "locked");
          return (
            <g key={p.id}
              className={`pt pt-${p.tone}${p.id === active ? " is-active" : ""}`}
              tabIndex={0}
              role="img"
              aria-label={`${p.label}. ${x.label} ${x.format(p.x)}, ${y.label} ${y.format(p.y)}.${p.detail ? ` ${p.detail}` : ""}`}
              onMouseEnter={() => setActive(p.id)}
              onMouseLeave={() => setActive(null)}
              onFocus={() => setActive(p.id)}
              onBlur={() => setActive(null)}>
              <Marker tone={p.tone} cx={cx} cy={cy} />
              {/* drawn last so the whole 14px disc catches the pointer, marker included */}
              <circle cx={cx} cy={cy} r={14} className="hit" />
              {showLabel ? (
                <text className={`pt-label${p.tone === "locked" ? " strong" : ""}`}
                  x={cx + (flip ? -14 : 14)} y={p.labelBelow ? cy + 20 : cy - 10}
                  textAnchor={flip ? "end" : "start"}>
                  {p.label}
                </text>
              ) : null}
            </g>
          );
        })}
      </svg>
      {current ? (
        <div className="chart-tip" aria-hidden="true"
          style={{
            left: Math.min(Math.max(sx(current.x), 90), width - 90),
            top: Math.max(sy(current.y) - 12, 0),
          }}>
          <strong>{current.label}</strong>
          <span>{x.label}: {x.format(current.x)}</span>
          <span>{y.label}: {y.format(current.y)}</span>
          {current.detail ? <span className="muted">{current.detail}</span> : null}
        </div>
      ) : null}
      {legend ? (
        <ul className="chart-legend">
          {legend.map((l) => (
            <li key={l.label}>
              {l.tone === "line"
                ? <svg width={22} height={22} aria-hidden="true"><line x1={2} x2={20} y1={11} y2={11} className="series" /></svg>
                : <LegendSwatch tone={l.tone} />}
              <span>{l.label}</span>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

/** Horizontal bars as plain HTML, so long process names wrap instead of being clipped. */
export function BarList({
  ariaLabel,
  rows,
  format,
}: {
  ariaLabel: string;
  rows: { id: string; label: string; value: number; highlight?: boolean; note?: string }[];
  format: (v: number) => string;
}) {
  const top = rows.reduce((mx, r) => Math.max(mx, r.value), 0);
  return (
    <ul className="barlist" aria-label={ariaLabel}>
      {rows.map((r) => (
        <li key={r.id} className={`bar-row${r.highlight ? " is-highlight" : ""}`}>
          <span className="bar-label">
            {r.label}
            {r.note ? <span className="bar-note"> {r.note}</span> : null}
          </span>
          <span className="bar-track" aria-hidden="true">
            <span className="bar-fill" style={{ width: `${top > 0 ? (r.value / top) * 100 : 0}%` }} />
          </span>
          <span className="bar-value mono">{format(r.value)}</span>
        </li>
      ))}
    </ul>
  );
}

/**
 * One dot per session on a 0-100% axis, with the diagnostic threshold drawn in.
 * Sessions with the same coverage stack upwards instead of hiding each other.
 * Stacking is deterministic (sorted order), never random jitter.
 */
export function CoverageStrip({
  ariaLabel,
  rows,
  threshold,
}: {
  ariaLabel: string;
  rows: { id: string; value: number; flagged: boolean; detail: string }[];
  threshold: number;
}) {
  const [ref, measured] = useElementWidth<HTMLDivElement>();
  const width = Math.max(300, measured);
  const m = { left: 16, right: 16 };
  const innerW = width - m.left - m.right;
  const sx = (v: number) => m.left + v * innerW;
  const step = 11;
  const sorted = [...rows].sort((a, b) => a.value - b.value || a.id.localeCompare(b.id));
  const lastX: number[] = [];
  const placed = sorted.map((r) => {
    const px = sx(r.value);
    let level = 0;
    while (lastX[level] !== undefined && px - lastX[level] < 10) level += 1;
    lastX[level] = px;
    return { ...r, px, level };
  });
  const levels = Math.max(1, ...placed.map((p) => p.level + 1));
  const base = 22 + levels * step;
  const height = base + 34;

  return (
    <div className="chart" ref={ref}>
      <svg width={width} height={height} role="img" aria-label={ariaLabel}>
        <line className="axis" x1={m.left} x2={width - m.right} y1={base + 6} y2={base + 6} />
        {[0, 0.25, 0.5, 0.75, 1].map((t) => (
          <text key={t} className="tick" x={sx(t)} y={base + 24}
            textAnchor={t === 0 ? "start" : t === 1 ? "end" : "middle"}>
            {Math.round(t * 100)}%
          </text>
        ))}
        <line className="threshold" x1={sx(threshold)} x2={sx(threshold)} y1={8} y2={base + 10} />
        <text className="threshold-label" x={sx(threshold) + 6} y={14}>
          threshold {threshold.toFixed(2)}
        </text>
        {placed.map((p) => {
          const cy = base - p.level * step;
          return p.flagged ? (
            <path key={p.id} className="dot-flagged"
              d={`M${p.px},${cy - 5}L${p.px + 5},${cy + 4}L${p.px - 5},${cy + 4}Z`}>
              <title>{p.detail}</title>
            </path>
          ) : (
            <circle key={p.id} className="dot-healthy" cx={p.px} cy={cy} r={4}>
              <title>{p.detail}</title>
            </circle>
          );
        })}
      </svg>
    </div>
  );
}
