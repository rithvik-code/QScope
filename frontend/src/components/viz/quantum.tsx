/**
 * Quantum visualisations.
 *
 * These are the microscope's optics: a circuit canvas you can step through, the
 * amplitude/phase view of a state vector, a Bloch projection, and the Quantum Diff
 * that shows what one gate moved.
 */

import { useMemo } from "react";
import type { CircuitDocument, CircuitOperation, TraceStep } from "../../lib/api";
import { Heatmap } from "./charts";

// ----------------------------------------------------------- CircuitCanvas

interface CanvasProps {
  circuit: CircuitDocument | null;
  activeIndex?: number | null;
  onSelect?: (index: number) => void;
  showClassical?: boolean;
  compact?: boolean;
}

const TWO_QUBIT_CONTROLLED = new Set(["CNOT", "CX", "CY", "CZ", "CH", "CP", "CSWAP", "TOFFOLI", "CCX", "CCZ", "MCX"]);

function gateColour(name: string): string {
  if (["H", "X", "Y", "Z", "S", "T", "SDG", "TDG", "SX", "SXDG"].includes(name)) return "var(--c-primary)";
  if (name.startsWith("R") || ["P", "U2", "U3"].includes(name)) return "var(--c-secondary)";
  if (["CNOT", "CX", "CZ", "CY", "SWAP", "ISWAP", "TOFFOLI", "CCX", "MCX", "CSWAP", "RXX", "RYY", "RZZ", "RZX"].includes(name))
    return "var(--c-accent)";
  return "var(--c-muted)";
}

function operationLabel(operation: CircuitOperation): string {
  if (operation.kind === "measure") return "M";
  if (operation.kind === "reset") return "|0⟩";
  if (operation.kind === "barrier") return "‖";
  if (operation.params?.length) {
    const shown = operation.params.map((value) => (Math.abs(value) < 1e-12 ? "0" : value.toFixed(2).replace(/\.?0+$/, "")));
    return `${operation.name}(${shown.join(",")})`;
  }
  return operation.name;
}

export function CircuitCanvas({ circuit, activeIndex, onSelect, showClassical = true, compact = false }: CanvasProps) {
  const layout = useMemo(() => {
    if (!circuit) return null;
    const rowHeight = compact ? 26 : 34;
    const wireGap = compact ? 30 : 44;
    const left = compact ? 40 : 56;
    const top = 22;
    const qubits = circuit.num_qubits;
    const clbits = circuit.num_clbits;
    const columns: Array<{ index: number; x: number; width: number; operation: CircuitOperation }> = [];
    // operations sharing a layer are drawn in the same column
    let cursor = left;
    const layerOf = new Map<number, number>();
    circuit.operations.forEach((operation, index) => {
      const wires = [...operation.controls, ...operation.targets];
      const layersUsed = wires.map((wire) => layerOf.get(wire) ?? -1);
      const start = Math.max(...layersUsed, -1) + 1;
      wires.forEach((wire) => layerOf.set(wire, start));
      columns.push({ index, x: 0, width: 0, operation });
    });
    const layerCount = Math.max(...Array.from(layerOf.values()), 0) + 1;
    const layerWidths = new Array(layerCount).fill(compact ? 40 : 52);
    circuit.operations.forEach((operation, index) => {
      const wires = [...operation.controls, ...operation.targets];
      const layer = Math.max(...wires.map((wire) => layerOf.get(wire) ?? 0));
      const label = operationLabel(operation);
      layerWidths[layer] = Math.max(layerWidths[layer], label.length * (compact ? 6.4 : 7.4) + (compact ? 14 : 20));
    });
    const layerStarts: number[] = [];
    layerWidths.forEach((width) => {
      layerStarts.push(cursor);
      cursor += width;
    });
    columns.forEach((column) => {
      const wires = [...column.operation.controls, ...column.operation.targets];
      const layer = Math.max(...wires.map((wire) => layerOf.get(wire) ?? 0));
      column.x = layerStarts[layer];
      column.width = layerWidths[layer];
    });
    const classicalTop = top + qubits * rowHeight + (compact ? 8 : 14);
    const width = cursor + (compact ? 20 : 40);
    const height = top + qubits * rowHeight + (showClassical && clbits ? clbits * (compact ? 20 : 24) + 12 : compact ? 10 : 24);
    return { rowHeight, wireGap, left, top, qubits, clbits, columns, width, height, classicalTop };
  }, [circuit, compact, showClassical]);

  if (!circuit || !layout) {
    return <p className="text-[11px] text-[var(--c-faint)]">No circuit yet.</p>;
  }

  const wireY = (qubit: number) => layout.top + qubit * layout.rowHeight + layout.rowHeight / 2;
  const clbitY = (clbit: number) => layout.classicalTop + clbit * (compact ? 20 : 24);

  return (
    <div className="overflow-x-auto">
      <svg viewBox={`0 0 ${layout.width} ${layout.height}`} width={layout.width} height={layout.height} className="min-w-full">
        {/* wires */}
        {Array.from({ length: layout.qubits }, (_, qubit) => (
          <g key={`q${qubit}`}>
            <line x1={0} x2={layout.width - 8} y1={wireY(qubit)} y2={wireY(qubit)} stroke="var(--c-line-strong)" strokeWidth="1" />
            <text x={8} y={wireY(qubit) + 3.5} className="mono-num" fontSize={compact ? 9 : 10} fill="var(--c-faint)">
              q{qubit}
            </text>
          </g>
        ))}
        {showClassical &&
          Array.from({ length: layout.clbits }, (_, clbit) => (
            <g key={`c${clbit}`}>
              <line
                x1={0}
                x2={layout.width - 8}
                y1={clbitY(clbit)}
                y2={clbitY(clbit)}
                stroke="var(--c-faint)"
                strokeWidth="1"
                strokeDasharray="4 4"
              />
              <text x={8} y={clbitY(clbit) + 3.5} className="mono-num" fontSize="9" fill="var(--c-faint)">
                c{clbit}
              </text>
            </g>
          ))}

        {/* operations */}
        {layout.columns.map(({ index, x, width, operation }) => {
          const active = activeIndex === index;
          const colour = operation.kind === "gate" ? gateColour(operation.name) : "var(--c-muted)";
          const wires = [...operation.controls, ...operation.targets];
          const topWire = Math.min(...wires);
          const bottomWire = Math.max(...wires);
          const stroke = active ? "var(--c-primary)" : colour;
          const boxWidth = Math.max(18, width - 10);
          const boxX = x + 5;
          const isControlled = operation.controls.length > 0;

          return (
            <g
              key={operation.opid ?? index}
              className="cursor-pointer"
              onClick={() => onSelect?.(index)}
              opacity={activeIndex === null || active || activeIndex === undefined ? 1 : 0.72}
            >
              <title>{`#${index} · ${operation.name} on ${wires.map((wire) => `q${wire}`).join(", ")}`}</title>
              {(isControlled || wires.length > 1) && (
                <line x1={x + width / 2} x2={x + width / 2} y1={wireY(topWire)} y2={wireY(bottomWire)} stroke={stroke} strokeWidth="1.2" />
              )}
              {isControlled &&
                operation.controls.map((control) => (
                  <circle
                    key={`ctl-${control}`}
                    cx={x + width / 2}
                    cy={wireY(control)}
                    r={3.4}
                    fill={operation.control_values?.[0] === 0 ? "var(--c-bg)" : stroke}
                    stroke={stroke}
                    strokeWidth="1.2"
                  />
                ))}
              {operation.kind === "barrier" ? (
                <line x1={x + width / 2} x2={x + width / 2} y1={wireY(topWire) - 8} y2={wireY(bottomWire) + 8} stroke="var(--c-warn)" strokeWidth="1.2" strokeDasharray="3 3" />
              ) : operation.kind === "measure" ? (
                <g>
                  <rect x={boxX} y={wireY(operation.targets[0]) - 9} width={boxWidth} height="18" rx="3" fill="color-mix(in oklab, var(--c-muted) 20%, transparent)" stroke={stroke} strokeWidth="1.1" />
                  <text x={boxX + boxWidth / 2} y={wireY(operation.targets[0]) + 4} textAnchor="middle" className="mono-num" fontSize="10" fill="var(--c-text)">
                    M
                  </text>
                  {operation.classical_targets?.map((clbit) => (
                    <line
                      key={clbit}
                      x1={x + width / 2}
                      x2={x + width / 2}
                      y1={wireY(operation.targets[0]) + 9}
                      y2={clbitY(clbit)}
                      stroke="var(--c-faint)"
                      strokeWidth="1"
                      strokeDasharray="3 3"
                    />
                  ))}
                  {operation.classical_targets?.map((clbit) => (
                    <rect key={`cm-${clbit}`} x={boxX + 2} y={clbitY(clbit) - 7} width={boxWidth - 4} height="14" rx="2" fill="color-mix(in oklab, var(--c-muted) 16%, transparent)" stroke="var(--c-faint)" strokeWidth="0.8" />
                  ))}
                </g>
              ) : operation.kind === "reset" ? (
                <text x={x + width / 2} y={wireY(operation.targets[0]) + 4} textAnchor="middle" className="mono-num" fontSize="10" fill={stroke}>
                  |0⟩
                </text>
              ) : (
                <g>
                  <rect
                    x={boxX}
                    y={wireY(wires[wires.length - 1]) - 9}
                    width={boxWidth}
                    height="18"
                    rx="4"
                    fill={active ? "color-mix(in oklab, var(--c-primary) 26%, transparent)" : "color-mix(in oklab, var(--c-bg) 55%, transparent)"}
                    stroke={stroke}
                    strokeWidth={active ? 1.6 : 1.1}
                  />
                  <text
                    x={boxX + boxWidth / 2}
                    y={wireY(wires[wires.length - 1]) + 3.5}
                    textAnchor="middle"
                    className="mono-num"
                    fontSize={compact ? 9 : 10}
                    fill="var(--c-text)"
                  >
                    {operationLabel(operation)}
                  </text>
                </g>
              )}
              {operation.condition && (
                <text x={boxX} y={wireY(wires[wires.length - 1]) - 12} className="mono-num" fontSize="8" fill="var(--c-warn)">
                  c[{operation.condition.clbit}]={operation.condition.value}
                </text>
              )}
            </g>
          );
        })}
        {!circuit.operations.length && (
          <text x={layout.width / 2} y={layout.height / 2} textAnchor="middle" fontSize="11" fill="var(--c-faint)">
            empty circuit — add a gate
          </text>
        )}
      </svg>
    </div>
  );
}

// ----------------------------------------------------------- AmplitudeBars

export interface Amplitude {
  basis: string;
  real: number;
  imag: number;
  magnitude: number;
  probability: number;
  phase: number;
}

/** Phase as a colour on the chromatic circle, so phase structure is visible at a glance. */
export function phaseColour(phase: number, alpha = 1): string {
  const degrees = ((phase * 180) / Math.PI + 360) % 360;
  return `color-mix(in oklab, hsl(${degrees.toFixed(0)} 78% 62%) ${Math.round(alpha * 100)}%, transparent)`;
}

export function AmplitudeBars({
  amplitudes,
  limit = 16,
  onSelect,
  selected,
}: {
  amplitudes: Amplitude[];
  limit?: number;
  onSelect?: (basis: string) => void;
  selected?: string | null;
}) {
  const sorted = useMemo(
    () => [...amplitudes].sort((a, b) => b.probability - a.probability || a.basis.localeCompare(b.basis)).slice(0, limit),
    [amplitudes, limit],
  );
  const maxProbability = Math.max(...sorted.map((entry) => entry.probability), 1e-9);
  const maxMagnitude = Math.max(...sorted.map((entry) => entry.magnitude), 1e-9);

  return (
    <div className="space-y-1.5">
      {sorted.map((entry) => (
        <button
          key={entry.basis}
          type="button"
          onClick={() => onSelect?.(entry.basis)}
          className={`flex w-full items-center gap-2 rounded-md px-1.5 py-1 text-left transition-colors ${
            selected === entry.basis ? "bg-[color-mix(in_oklab,var(--c-primary)_13%,transparent)]" : "hover:bg-[color-mix(in_oklab,var(--c-text)_6%,transparent)]"
          }`}
        >
          <span className="mono-num w-16 shrink-0 text-[11px] text-[var(--c-text)]">|{entry.basis}⟩</span>
          <span className="relative block h-3.5 flex-1 overflow-hidden rounded-sm bg-[var(--c-line)]/45">
            <span
              className="absolute inset-y-0 left-0 transition-all duration-500"
              style={{ width: `${(entry.probability / maxProbability) * 100}%`, background: phaseColour(entry.phase, 0.85) }}
            />
            <span
              className="absolute inset-y-0 border-r border-[var(--c-text)]/70"
              style={{ width: `${(entry.magnitude / maxMagnitude) * 100}%` }}
            />
          </span>
          <span className="mono-num w-16 shrink-0 text-right text-[10px] text-[var(--c-muted)]">{entry.probability.toFixed(4)}</span>
          <span className="mono-num w-24 shrink-0 text-right text-[10px]">
            <span className="text-[var(--c-secondary)]">{entry.real.toFixed(3)}</span>
            <span className="text-[var(--c-faint)]">{entry.imag >= 0 ? "+" : "−"}</span>
            <span className="text-[var(--c-accent)]">{Math.abs(entry.imag).toFixed(3)}i</span>
          </span>
          <span className="mono-num w-14 shrink-0 text-right text-[10px]" style={{ color: phaseColour(entry.phase) }}>
            {((entry.phase * 180) / Math.PI).toFixed(0)}°
          </span>
        </button>
      ))}
    </div>
  );
}

/** The same amplitudes as phasors on a circle — the phase view a table cannot give. */
export function PhaseDial({ amplitudes, size = 190, limit = 24 }: { amplitudes: Amplitude[]; size?: number; limit?: number }) {
  const radius = size / 2 - 16;
  const centre = size / 2;
  const strongest = [...amplitudes].sort((a, b) => b.magnitude - a.magnitude).slice(0, limit);
  return (
    <svg viewBox={`0 0 ${size} ${size}`} width={size} height={size}>
      <circle cx={centre} cy={centre} r={radius} fill="none" stroke="var(--c-line)" strokeWidth="1" />
      <circle cx={centre} cy={centre} r={radius * 0.5} fill="none" stroke="var(--c-line)" strokeWidth="0.6" strokeDasharray="2 4" />
      <line x1={centre - radius} x2={centre + radius} y1={centre} y2={centre} stroke="var(--c-line)" strokeWidth="0.6" />
      <line x1={centre} x2={centre} y1={centre - radius} y2={centre + radius} stroke="var(--c-line)" strokeWidth="0.6" />
      <text x={centre + radius} y={centre - 5} fontSize="8" fill="var(--c-faint)" textAnchor="end">
        0°
      </text>
      {strongest.map((entry) => {
        const x = centre + Math.cos(entry.phase) * radius * entry.magnitude;
        const y = centre - Math.sin(entry.phase) * radius * entry.magnitude;
        return (
          <g key={entry.basis}>
            <line x1={centre} y1={centre} x2={x} y2={y} stroke={phaseColour(entry.phase)} strokeWidth="1.2" strokeOpacity="0.85" />
            <circle cx={x} cy={y} r={2.4} fill={phaseColour(entry.phase)} />
            <title>{`|${entry.basis}⟩: magnitude ${entry.magnitude.toFixed(4)}, phase ${((entry.phase * 180) / Math.PI).toFixed(1)}°`}</title>
          </g>
        );
      })}
    </svg>
  );
}

// --------------------------------------------------------------- BlochSphere

/** Orthographic projection of the Bloch vector, with the three axes drawn. */
export function BlochSphere({
  x,
  y,
  z,
  label,
  size = 128,
  showAxes = true,
}: {
  x: number;
  y: number;
  z: number;
  label?: string;
  size?: number;
  showAxes?: boolean;
}) {
  const centre = size / 2;
  const radius = size / 2 - 16;
  const azimuth = (25 * Math.PI) / 180;
  const elevation = (22 * Math.PI) / 180;
  const project = (px: number, py: number, pz: number) => {
    const rotatedX = px * Math.cos(azimuth) - py * Math.sin(azimuth);
    const rotatedY = px * Math.sin(azimuth) + py * Math.cos(azimuth);
    const screenX = rotatedX;
    const screenY = rotatedY * Math.sin(elevation) - pz * Math.cos(elevation);
    return [centre + screenX * radius, centre + screenY * radius] as const;
  };
  const [tipX, tipY] = project(x, y, z);
  const length = Math.sqrt(x * x + y * y + z * z);
  const [shadowX, shadowY] = project(x, y, 0);

  return (
    <svg viewBox={`0 0 ${size} ${size}`} width={size} height={size}>
      <circle cx={centre} cy={centre} r={radius} fill="color-mix(in oklab, var(--c-panel-2) 60%, transparent)" stroke="var(--c-line-strong)" strokeWidth="1" />
      <ellipse cx={centre} cy={centre} rx={radius} ry={radius * Math.sin(elevation)} fill="none" stroke="var(--c-line)" strokeWidth="0.7" />
      {showAxes && (
        <g stroke="var(--c-line-strong)" strokeWidth="0.8">
          {[
            project(1, 0, 0),
            project(0, 1, 0),
            project(0, 0, 1),
          ].map((positive, index) => {
            const negative = project(
              index === 0 ? -1 : 0,
              index === 1 ? -1 : 0,
              index === 2 ? -1 : 0,
            );
            const positivePoint = positive;
            return <line key={index} x1={negative[0]} y1={negative[1]} x2={positivePoint[0]} y2={positivePoint[1]} />;
          })}
        </g>
      )}
      <g fontSize="8" fill="var(--c-faint)" className="mono-num">
        <text x={project(1, 0, 0)[0] + 3} y={project(1, 0, 0)[1] + 3}>
          x
        </text>
        <text x={project(0, 1, 0)[0] + 3} y={project(0, 1, 0)[1] + 3}>
          y
        </text>
        <text x={project(0, 0, 1)[0] - 3} y={project(0, 0, 1)[1] - 3}>
          z
        </text>
      </g>
      <line x1={centre} y1={centre} x2={shadowX} y2={shadowY} stroke="var(--c-faint)" strokeWidth="0.8" strokeDasharray="2 3" />
      <line x1={centre} y1={centre} x2={tipX} y2={tipY} stroke="var(--c-primary)" strokeWidth="1.8" strokeLinecap="round" />
      <circle cx={tipX} cy={tipY} r={3.6} fill="var(--c-primary)" />
      <circle cx={centre} cy={centre} r={1.6} fill="var(--c-faint)" />
      {label && (
        <text x={centre} y={size - 2} textAnchor="middle" fontSize="9" fill="var(--c-muted)" className="mono-num">
          {label} |r|={length.toFixed(3)}
        </text>
      )}
    </svg>
  );
}

// ---------------------------------------------------------------- StateDiff

/** Quantum Diff: what one operation moved, row by row. */
export function StateDiff({
  step,
  limit = 12,
}: {
  step: TraceStep;
  limit?: number;
}) {
  const rows = useMemo(() => {
    const before = new Map(step.state_before.amplitudes.map((entry) => [entry.basis, entry]));
    const after = new Map(step.state.amplitudes.map((entry) => [entry.basis, entry]));
    const bases = new Set([...before.keys(), ...after.keys()]);
    return Array.from(bases)
      .map((basis) => ({
        basis,
        before: before.get(basis) ?? { probability: 0, magnitude: 0, phase: 0, real: 0, imag: 0 },
        after: after.get(basis) ?? { probability: 0, magnitude: 0, phase: 0, real: 0, imag: 0 },
      }))
      .map((row) => ({ ...row, delta: row.after.probability - row.before.probability }))
      .sort((a, b) => Math.abs(b.delta) - Math.abs(a.delta))
      .slice(0, limit);
  }, [step, limit]);

  const maxDelta = Math.max(...rows.map((row) => Math.abs(row.delta)), 1e-9);

  return (
    <div className="space-y-1">
      <div className="label-xs flex items-center gap-2">
        probability change
        <span className="text-[var(--c-faint)]">
          {step.state_before.entanglement_status} → {step.state.entanglement_status}
        </span>
      </div>
      {rows.map((row) => (
        <div key={row.basis} className="flex items-center gap-2">
          <span className="mono-num w-16 shrink-0 text-[11px]">|{row.basis}⟩</span>
          <span className="relative block h-3 flex-1 rounded-sm bg-[var(--c-line)]/40">
            <span
              className="absolute inset-y-0 transition-all duration-500"
              style={{
                left: row.delta >= 0 ? "50%" : undefined,
                right: row.delta < 0 ? "50%" : undefined,
                width: `${(Math.abs(row.delta) / maxDelta) * 50}%`,
                background: row.delta >= 0 ? "var(--c-primary)" : "var(--c-accent)",
              }}
            />
            <span className="absolute inset-y-0 left-1/2 w-px bg-[var(--c-line-strong)]" />
          </span>
          <span className="mono-num w-28 shrink-0 text-right text-[10px] text-[var(--c-muted)]">
            {row.before.probability.toFixed(3)} → {row.after.probability.toFixed(3)}
          </span>
          <span
            className="mono-num w-16 shrink-0 text-right text-[10px]"
            style={{ color: row.delta >= 0 ? "var(--c-primary)" : "var(--c-accent)" }}
          >
            {row.delta >= 0 ? "+" : ""}
            {row.delta.toFixed(3)}
          </span>
        </div>
      ))}
    </div>
  );
}

/** A density matrix view: magnitude heat map plus purity/entropy context. */
export interface DensityMatrixPayload {
  real: number[][];
  imag: number[][];
  magnitude?: number[][];
  purity?: number;
  entropy?: number;
  num_qubits?: number;
}

/** A density matrix view: signed heat map of the real part, with its phase structure noted. */
export function DensityView({
  matrix,
  qubits,
  caption,
}: {
  matrix: DensityMatrixPayload;
  qubits: number;
  caption?: string;
}) {
  const labels = useMemo(
    () => Array.from({ length: 2 ** qubits }, (_, index) => index.toString(2).padStart(qubits, "0")),
    [qubits],
  );
  const values = useMemo(
    () => (matrix.real?.length ? matrix.real : Array.from({ length: 2 ** qubits }, () => new Array(2 ** qubits).fill(0))),
    [matrix, qubits],
  );
  return (
    <div className="space-y-2">
      <Heatmap data={values} labels={labels} size={240} caption={caption ?? "real part of the density matrix"} />
      {(matrix.purity !== undefined || matrix.entropy !== undefined) && (
        <p className="mono-num text-[10px] text-[var(--c-muted)]">
          purity {matrix.purity?.toFixed(4) ?? "—"} · entropy {matrix.entropy?.toFixed(4) ?? "—"} bits
        </p>
      )}
    </div>
  );
}

export function PureStateOnly({ hint }: { hint: string }) {
  return (
    <div className="rounded-lg border border-dashed border-[var(--c-line)] px-3 py-5 text-center text-[11px] text-[var(--c-faint)]">
      {hint}
    </div>
  );
}
