/**
 * Charts, drawn by hand in SVG.
 *
 * No charting dependency: the plots here have to be honest about what they show
 * — measured points versus a fitted curve versus an extrapolation, sampled counts
 * versus the exact distribution — and that is easier to guarantee with 60 lines
 * of SVG than with a library's defaults.
 */

import { useMemo, useState } from "react";

export interface Series {
  key: string;
  label: string;
  y: Array<number | null>;
  kind?: "line" | "bar" | "scatter";
  colour?: string;
  dashed?: boolean;
  span?: "solid" | "extrapolated";
}

interface ChartProps {
  x: Array<string | number>;
  series: Series[];
  xLabel?: string;
  yLabel?: string;
  height?: number;
  yMin?: number;
  yMax?: number;
  annotations?: Array<{ x: string | number; label: string; colour?: string }>;
  formatY?: (value: number) => string;
  formatX?: (value: string | number) => string;
  onHover?: (index: number | null) => void;
}

const PALETTE = ["var(--c-primary)", "var(--c-secondary)", "var(--c-accent)", "var(--c-warn)", "var(--c-ok)"];

function niceBounds(values: number[], forcedMin?: number, forcedMax?: number): [number, number] {
  if (!values.length) return [0, 1];
  let min = forcedMin ?? Math.min(...values);
  let max = forcedMax ?? Math.max(...values);
  if (min === max) {
    const pad = Math.abs(min) * 0.15 + 1;
    return [min - pad, max + pad];
  }
  if (forcedMin === undefined) min = min - (max - min) * 0.08;
  if (forcedMax === undefined) max = max + (max - min) * 0.08;
  if (forcedMin === undefined && min > 0 && min < (max - min) * 0.6) min = 0;
  return [min, max];
}

function ticks(min: number, max: number, count = 4): number[] {
  return Array.from({ length: count + 1 }, (_, index) => min + ((max - min) * index) / count);
}

export function LineChart({
  x,
  series,
  xLabel,
  yLabel,
  height = 220,
  yMin,
  yMax,
  formatY = (value) => value.toPrecision(3),
  formatX = (value) => String(value),
  onHover,
}: ChartProps) {
  const [hover, setHover] = useState<number | null>(null);
  const width = 640;
  const margin = { top: 14, right: 16, bottom: 34, left: 56 };
  const innerWidth = width - margin.left - margin.right;
  const innerHeight = height - margin.top - margin.bottom;

  const allValues = series.flatMap((entry) => entry.y.filter((value): value is number => typeof value === "number"));
  const [min, max] = niceBounds(allValues, yMin, yMax);
  const xAt = (index: number) => (x.length <= 1 ? innerWidth / 2 : (innerWidth * index) / (x.length - 1));
  const yAt = (value: number) => innerHeight - ((value - min) / (max - min || 1)) * innerHeight;

  return (
    <div className="w-full">
      <svg
        viewBox={`0 0 ${width} ${height}`}
        className="w-full"
        style={{ height }}
        onMouseLeave={() => {
          setHover(null);
          onHover?.(null);
        }}
        onMouseMove={(event) => {
          const bounds = event.currentTarget.getBoundingClientRect();
          const ratio = (event.clientX - bounds.left) / bounds.width;
          const index = Math.round(((ratio * width - margin.left) / innerWidth) * (x.length - 1));
          const clamped = Math.max(0, Math.min(x.length - 1, index));
          setHover(clamped);
          onHover?.(clamped);
        }}
      >
        {/* grid + y axis */}
        {ticks(min, max).map((tick, index) => (
          <g key={index}>
            <line
              x1={margin.left}
              x2={width - margin.right}
              y1={margin.top + yAt(tick)}
              y2={margin.top + yAt(tick)}
              stroke="var(--c-line)"
              strokeWidth="0.6"
              strokeDasharray={index === 0 ? undefined : "2 5"}
            />
            <text
              x={margin.left - 8}
              y={margin.top + yAt(tick) + 3}
              textAnchor="end"
              className="mono-num"
              fontSize="9"
              fill="var(--c-faint)"
            >
              {formatY(tick)}
            </text>
          </g>
        ))}
        {/* x axis */}
        {x.map((label, index) => {
          const stride = Math.max(1, Math.ceil(x.length / 9));
          if (index % stride !== 0) return null;
          return (
            <text
              key={index}
              x={margin.left + xAt(index)}
              y={height - 12}
              textAnchor="middle"
              className="mono-num"
              fontSize="9"
              fill="var(--c-faint)"
            >
              {formatX(label)}
            </text>
          );
        })}

        {/* series */}
        {series.map((entry, seriesIndex) => {
          const colour = entry.colour ?? PALETTE[seriesIndex % PALETTE.length];
          const points = entry.y
            .map((value, index) => (typeof value === "number" ? [margin.left + xAt(index), margin.top + yAt(value)] : null))
            .filter((point): point is number[] => point !== null);
          if (entry.kind === "bar") {
            const barWidth = Math.max(2, innerWidth / Math.max(x.length, 1) - 2);
            return (
              <g key={entry.key}>
                {entry.y.map((value, index) =>
                  typeof value === "number" ? (
                    <rect
                      key={index}
                      x={margin.left + xAt(index) - barWidth / 2}
                      y={margin.top + yAt(Math.max(0, value))}
                      width={barWidth}
                      height={Math.abs(yAt(value) - yAt(Math.max(0, min)))}
                      fill={colour}
                      opacity={series.length > 1 ? 0.55 : 0.85}
                      rx={1.5}
                    />
                  ) : null,
                )}
              </g>
            );
          }
          if (entry.kind === "scatter") {
            return (
              <g key={entry.key}>
                {points.map((point, index) => (
                  <circle key={index} cx={point[0]} cy={point[1]} r={3.4} fill={colour} />
                ))}
              </g>
            );
          }
          return (
            <g key={entry.key}>
              <polyline
                points={points.map((point) => point.join(",")).join(" ")}
                fill="none"
                stroke={colour}
                strokeWidth={entry.span === "extrapolated" ? 1.2 : 1.9}
                strokeDasharray={entry.dashed || entry.span === "extrapolated" ? "5 4" : undefined}
                strokeLinejoin="round"
                strokeLinecap="round"
              />
              {points.map((point, index) => (
                <circle
                  key={index}
                  cx={point[0]}
                  cy={point[1]}
                  r={hover === index ? 4 : 2.2}
                  fill="var(--c-bg)"
                  stroke={colour}
                  strokeWidth="1.4"
                />
              ))}
            </g>
          );
        })}

        {/* hover guide */}
        {hover !== null && x.length > 0 && (
          <line
            x1={margin.left + xAt(hover)}
            x2={margin.left + xAt(hover)}
            y1={margin.top}
            y2={margin.top + innerHeight}
            stroke="var(--c-primary)"
            strokeWidth="0.8"
            strokeOpacity="0.5"
          />
        )}

        {yLabel && (
          <text x={12} y={margin.top + innerHeight / 2} fontSize="9" fill="var(--c-faint)" transform={`rotate(-90 12 ${margin.top + innerHeight / 2})`} textAnchor="middle">
            {yLabel}
          </text>
        )}
        {xLabel && (
          <text x={margin.left + innerWidth / 2} y={height - 1} fontSize="9" fill="var(--c-faint)" textAnchor="middle">
            {xLabel}
          </text>
        )}
      </svg>
      <Legend series={series} hover={hover} x={x} />
    </div>
  );
}

function Legend({ series, hover, x }: { series: Series[]; hover: number | null; x: Array<string | number> }) {
  return (
    <div className="mt-1 flex flex-wrap items-center gap-3">
      {series.map((entry, index) => (
        <span key={entry.key} className="inline-flex items-center gap-1.5 text-[10px] text-[var(--c-muted)]">
          <span
            className="inline-block h-1.5 w-3.5 rounded-full"
            style={{ background: entry.colour ?? PALETTE[index % PALETTE.length], opacity: entry.span === "extrapolated" ? 0.6 : 1 }}
          />
          {entry.label}
          {hover !== null && typeof entry.y[hover] === "number" && (
            <span className="mono-num text-[var(--c-text)]">= {(entry.y[hover] as number).toPrecision(3)}</span>
          )}
        </span>
      ))}
      {hover !== null && x[hover] !== undefined && (
        <span className="mono-num text-[10px] text-[var(--c-faint)]">at {String(x[hover])}</span>
      )}
    </div>
  );
}

// ------------------------------------------------------------- Histogram

export function InspectBars({
  items,
  colour = "var(--c-primary)",
  overlay,
  maxItems = 20,
  onSelect,
  selected,
  height = 14,
}: {
  items: Array<{ label: string; value: number; secondary?: number }>;
  colour?: string;
  overlay?: string;
  maxItems?: number;
  onSelect?: (label: string) => void;
  selected?: string | null;
  height?: number;
}) {
  const max = Math.max(...items.map((item) => Math.max(item.value, item.secondary ?? 0)), 1e-9);
  const shown = items.slice(0, maxItems);
  return (
    <div className="space-y-1">
      {shown.map((item) => (
        <button
          key={item.label}
          type="button"
          onClick={() => onSelect?.(item.label)}
          className={`group flex w-full items-center gap-2 rounded px-1 py-0.5 text-left transition-colors ${
            selected === item.label ? "bg-[color-mix(in_oklab,var(--c-primary)_14%,transparent)]" : "hover:bg-[color-mix(in_oklab,var(--c-text)_6%,transparent)]"
          }`}
        >
          <span className="mono-num w-14 shrink-0 text-[11px] text-[var(--c-text)]">{item.label}</span>
          <span className="relative block flex-1 overflow-hidden rounded-full bg-[var(--c-line)]/50" style={{ height }}>
            <span
              className="absolute inset-y-0 left-0 rounded-full transition-all duration-500"
              style={{ width: `${(item.value / max) * 100}%`, background: colour }}
            />
            {typeof item.secondary === "number" && (
              <span
                className="absolute inset-y-0 left-0 rounded-full border-r-2 transition-all duration-500"
                style={{ width: `${(item.secondary / max) * 100}%`, borderColor: overlay ?? "var(--c-text)", background: "transparent", opacity: 0.75 }}
              />
            )}
          </span>
          <span className="mono-num w-24 shrink-0 text-right text-[10px] text-[var(--c-muted)]">
            {item.value.toPrecision(4)}
            {typeof item.secondary === "number" && <span className="text-[var(--c-faint)]"> vs {item.secondary.toPrecision(3)}</span>}
          </span>
        </button>
      ))}
      {items.length > shown.length && (
        <p className="px-1 text-[10px] text-[var(--c-faint)]">
          showing the {shown.length} largest of {items.length}
        </p>
      )}
    </div>
  );
}

// ------------------------------------------------------------- Heatmap

export function Heatmap({
  data,
  size = 260,
  labels,
  signed = true,
  caption,
}: {
  data: number[][];
  size?: number;
  labels?: string[];
  signed?: boolean;
  caption?: string;
}) {
  const dimension = data.length;
  if (!dimension) return null;
  const magnitude = Math.max(...data.flat().map(Math.abs), 1e-12);
  const cell = size / dimension;
  const showLabels = dimension <= 8;
  return (
    <figure className="inline-block">
      <svg viewBox={`0 0 ${size + (showLabels ? 26 : 0)} ${size + (showLabels ? 18 : 0)}`} width={size + (showLabels ? 26 : 0)} height={size + (showLabels ? 18 : 0)}>
        <g transform={showLabels ? "translate(26,0)" : undefined}>
          {data.map((row, rowIndex) =>
            row.map((value, columnIndex) => {
              const intensity = Math.min(1, Math.abs(value) / magnitude);
              const colour =
                signed && value < 0
                  ? `color-mix(in oklab, var(--c-accent) ${intensity * 88}%, transparent)`
                  : `color-mix(in oklab, var(--c-primary) ${intensity * 88}%, transparent)`;
              return (
                <rect
                  key={`${rowIndex}-${columnIndex}`}
                  x={columnIndex * cell}
                  y={rowIndex * cell}
                  width={cell - 0.6}
                  height={cell - 0.6}
                  fill={colour}
                  stroke="var(--c-line)"
                  strokeWidth="0.3"
                >
                  <title>{`|${rowIndex}> , |${columnIndex}> = ${value.toPrecision(4)}`}</title>
                </rect>
              );
            }),
          )}
        </g>
        {showLabels &&
          labels?.map((label, index) => (
            <g key={label} className="mono-num" fontSize="8" fill="var(--c-faint)">
              <text x="22" y={index * cell + cell / 2 + 3} textAnchor="end">
                {label}
              </text>
              <text x={index * cell + cell / 2 + 26} y={size + 12} textAnchor="middle">
                {label}
              </text>
            </g>
          ))}
      </svg>
      {caption && <figcaption className="mt-1 text-[10px] text-[var(--c-faint)]">{caption}</figcaption>}
    </figure>
  );
}

// ------------------------------------------------------------- CompareBars

export function CompareBars({
  rows,
}: {
  rows: Array<{ metric: string; a: unknown; b: unknown; delta: number | null; labelA?: string; labelB?: string }>;
}) {
  const numeric = useMemo(
    () =>
      rows
        .filter((row) => typeof row.a === "number" && typeof row.b === "number")
        .map((row) => ({ ...row, a: row.a as number, b: row.b as number })),
    [rows],
  );
  if (!numeric.length) return <p className="text-[11px] text-[var(--c-faint)]">No comparable numeric metrics.</p>;
  return (
    <div className="space-y-2.5">
      {numeric.map((row) => {
        const max = Math.max(Math.abs(row.a), Math.abs(row.b), 1e-9);
        const better = row.delta !== null && row.delta < 0;
        return (
          <div key={row.metric}>
            <div className="mb-1 flex items-baseline justify-between">
              <span className="text-[11px] text-[var(--c-muted)]">{row.metric.replace(/_/g, " ")}</span>
              <span className="mono-num text-[10px] text-[var(--c-faint)]">
                {row.a.toPrecision(3)} → {row.b.toPrecision(3)}
                {row.delta !== null && (
                  <span style={{ color: better ? "var(--c-ok)" : row.delta > 0 ? "var(--c-warn)" : "var(--c-muted)" }}>
                    {" "}
                    ({row.delta > 0 ? "+" : ""}
                    {row.delta.toPrecision(3)})
                  </span>
                )}
              </span>
            </div>
            <div className="space-y-1">
              <span className="block h-1.5 overflow-hidden rounded-full bg-[var(--c-line)]/40">
                <span className="block h-full rounded-full" style={{ width: `${(row.a / max) * 100}%`, background: "var(--c-secondary)" }} />
              </span>
              <span className="block h-1.5 overflow-hidden rounded-full bg-[var(--c-line)]/40">
                <span className="block h-full rounded-full" style={{ width: `${(row.b / max) * 100}%`, background: "var(--c-primary)" }} />
              </span>
            </div>
          </div>
        );
      })}
    </div>
  );
}

export function Sparkline({ values, colour = "var(--c-primary)", height = 26 }: { values: number[]; colour?: string; height?: number }) {
  if (values.length < 2) return <span className="text-[10px] text-[var(--c-faint)]">—</span>;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const width = 96;
  const points = values
    .map((value, index) => `${(index / (values.length - 1)) * width},${height - ((value - min) / (max - min || 1)) * height}`)
    .join(" ");
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`}>
      <polyline points={points} fill="none" stroke={colour} strokeWidth="1.5" strokeLinejoin="round" />
    </svg>
  );
}

export { PALETTE };
