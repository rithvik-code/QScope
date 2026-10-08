/**
 * Benchmark — the performance observatory.
 *
 * Everything here is measured on this machine, in this process, with a warm-up and
 * repeated trials, and reported as a median with its spread.  Measured points and
 * fitted extrapolations are drawn differently on purpose: a fitted curve is a model,
 * not a measurement, and this view never lets the two look the same.
 */

import { useMemo, useState } from "react";
import { AnimatedNumber, InView } from "../components/motion";
import type { ModeKey } from "../components/Shell";
import {
  Button,
  DataTable,
  Empty,
  Field,
  KeyValueList,
  Notice,
  NumberInput,
  Panel,
  SectionTitle,
  StatTile,
  Tag,
  TextInput,
} from "../components/ui";
import { LineChart } from "../components/viz/charts";
import { formatMegabytes, formatSeconds, titleCase } from "../lib/format";
import type { BenchmarkPayload, BenchmarkPoint } from "../lib/api";
import { useStore } from "../state/store";

type BenchKind = "scaling" | "backends" | "throughput" | "memory" | "external" | "suite";

const KINDS: Array<{ value: BenchKind; label: string; blurb: string }> = [
  { value: "scaling", label: "scaling", blurb: "Runtime against qubit count, with the empirical growth fitted and extrapolations labelled." },
  { value: "backends", label: "engines", blurb: "The same circuit timed on the state-vector, density-matrix and trajectory engines." },
  { value: "throughput", label: "gate throughput", blurb: "Per-gate cost at a fixed register size, measured on the state vector." },
  { value: "memory", label: "memory", blurb: "What each engine needs per qubit count, against the budget QScope will not exceed." },
  { value: "external", label: "external", blurb: "A real side-by-side run against another simulator — only if one is actually installed." },
  { value: "suite", label: "full suite", blurb: "The whole observatory in one pass: environment, engines, scaling, memory, externals." },
];

function parseQubits(text: string): number[] {
  return text
    .split(/[,\s]+/)
    .map((token) => Number(token.trim()))
    .filter((value) => Number.isFinite(value) && value >= 1 && value <= 32)
    .slice(0, 12);
}

export function BenchmarkMode({ onNavigate }: { onNavigate: (mode: ModeKey) => void }) {
  const { benchmark, loading, errors, runBenchmark } = useStore();
  const [kind, setKind] = useState<BenchKind>("scaling");
  const [qubitsText, setQubitsText] = useState("6, 8, 10, 12");
  const [depth, setDepth] = useState(8);
  const [shots, setShots] = useState(1024);
  const [trials, setTrials] = useState(3);
  const [seed, setSeed] = useState(7);

  const payload = benchmark;
  const qubits = parseQubits(qubitsText);
  const active = KINDS.find((entry) => entry.value === kind) ?? KINDS[0];

  const run = () =>
    void runBenchmark({
      kind,
      qubits,
      depth,
      shots,
      trials,
      seed,
    });

  // ------------------------------------------------------------------ scaling
  const points = (payload?.points ?? []) as BenchmarkPoint[];
  const measured = points.filter((point) => point.status === "measured" && typeof point.median_seconds === "number");
  const notMeasured = points.filter((point) => point.status !== "measured");
  const extrapolations = payload?.fit?.extrapolations ?? [];

  const scalingChart = useMemo(() => {
    if (!measured.length) return null;
    const axis = Array.from(
      new Set([...measured.map((point) => point.qubits), ...extrapolations.map((entry) => entry.qubits)]),
    ).sort((a, b) => a - b);
    const measuredSeries = {
      key: "measured",
      label: "measured (median of trials)",
      y: axis.map((value) => measured.find((point) => point.qubits === value)?.median_seconds ?? null),
      colour: "var(--c-primary)",
    };
    const fittedSeries = payload?.fit?.available
      ? {
          key: "fitted",
          label: "fitted model t(n) = a·bⁿ",
          y: axis.map((value) => {
            const extrapolated = extrapolations.find((entry) => entry.qubits === value);
            if (extrapolated) return extrapolated.predicted_seconds;
            const sample = payload?.fit?.measurements?.find((entry) => entry.qubits === value);
            return sample ? sample.predicted_seconds : null;
          }),
          colour: "var(--c-accent)",
          dashed: true,
          span: "extrapolated" as const,
        }
      : null;
    return { axis, series: fittedSeries ? [measuredSeries, fittedSeries] : [measuredSeries] };
  }, [measured, extrapolations, payload?.fit]);

  // ----------------------------------------------------------------- backends
  const rows = (payload?.rows ?? []) as Array<Record<string, unknown>>;
  const engineChart = useMemo(() => {
    if (payload?.kind !== "backend_benchmark") return null;
    const engines = Array.from(new Set(rows.map((row) => String(row.backend))));
    const axis = Array.from(new Set(rows.map((row) => Number(row.qubits)))).sort((a, b) => a - b);
    const series = engines.map((engine, index) => ({
      key: engine,
      label: String(rows.find((row) => String(row.backend) === engine)?.backend_label ?? engine),
      y: axis.map((value) => {
        const row = rows.find((candidate) => String(candidate.backend) === engine && Number(candidate.qubits) === value);
        return row && typeof row.median_seconds === "number" ? row.median_seconds : null;
      }),
      colour: ["var(--c-primary)", "var(--c-secondary)", "var(--c-accent)", "var(--c-warn)"][index % 4],
    }));
    return { axis, series };
  }, [payload?.kind, rows]);

  // ------------------------------------------------------------------ memory
  const memoryTables = payload?.backend_tables ?? {};
  const memoryEngines = Object.keys(memoryTables);
  const memoryAxis = useMemo(
    () => Array.from(new Set(Object.values(memoryTables).flatMap((table) => table.map((entry) => entry.qubits)))).sort((a, b) => a - b),
    [memoryTables],
  );
  const engineSpecs = Array.isArray(payload?.backends) ? (payload?.backends as Array<Record<string, unknown>>) : [];

  return (
    <div className="space-y-4">
      <div className="grid gap-4 xl:grid-cols-[360px_1fr]">
        {/* ---------------------------------------------------------- controls */}
        <div className="space-y-3">
          <Panel title="What to measure" subtitle={active.blurb} dense>
            <div className="space-y-3">
              <div className="grid grid-cols-3 gap-1.5">
                {KINDS.map((entry) => (
                  <button
                    key={entry.value}
                    type="button"
                    title={entry.blurb}
                    onClick={() => setKind(entry.value)}
                    className={`focus-ring rounded-lg border px-2 py-1.5 text-[11px] transition-colors ${
                      kind === entry.value
                        ? "border-[var(--c-primary)] bg-[color-mix(in_oklab,var(--c-primary)_10%,transparent)] text-[var(--c-primary)]"
                        : "border-[var(--c-line)] text-[var(--c-muted)] hover:text-[var(--c-text)]"
                    }`}
                  >
                    {entry.label}
                  </button>
                ))}
              </div>

              <Field
                label="qubit counts"
                hint={
                  kind === "throughput"
                    ? "Only the largest value is used: throughput is measured at one register size."
                    : "Each value becomes one timed measurement (median of the trials)."
                }
              >
                <TextInput value={qubitsText} onChange={setQubitsText} placeholder="6, 8, 10, 12" />
              </Field>

              <Field
                label={kind === "throughput" ? "gate repetitions" : "circuit depth"}
                hint={kind === "external" ? "Depth of the comparison circuit." : undefined}
              >
                <NumberInput value={depth} min={1} max={64} onChange={setDepth} />
              </Field>

              <div className="grid grid-cols-3 gap-2">
                <Field label="shots">
                  <NumberInput value={shots} min={1} max={1000000} onChange={setShots} />
                </Field>
                <Field label="trials">
                  <NumberInput value={trials} min={1} max={20} onChange={setTrials} />
                </Field>
                <Field label="seed">
                  <NumberInput value={seed} step={1} onChange={setSeed} />
                </Field>
              </div>

              <div className="flex flex-wrap gap-2">
                <Button variant="primary" disabled={loading.benchmark} onClick={run}>
                  {loading.benchmark ? "measuring…" : "run benchmark"}
                </Button>
                <Button variant="outline" onClick={() => onNavigate("research")}>
                  ask about the numbers →
                </Button>
              </div>

              {errors.benchmark && <Notice tone="danger" title="Benchmark refused">{errors.benchmark}</Notice>}

              <Notice tone="warn" title="What a benchmark here can and cannot say">
                These are wall-clock measurements of a NumPy engine in one Python process on this machine. They are
                repeatable, and they are not a claim about quantum hardware, about another simulator's correctness, or
                about quantum advantage.
              </Notice>
            </div>
          </Panel>

          {payload?.request && (
            <Panel title="Request as recorded" subtitle="Echoed back by the server with the measurements." dense>
              <KeyValueList
                columns={2}
                items={Object.entries(payload.request as Record<string, unknown>).map(([label, value]) => ({
                  label: label.replace(/_/g, " "),
                  value: Array.isArray(value) ? (value as unknown[]).join(", ") : String(value),
                }))}
              />
            </Panel>
          )}
        </div>

        {/* ----------------------------------------------------------- results */}
        <div className="space-y-3">
          {!payload && (
            <Panel title="Nothing measured yet" subtitle="Choose a benchmark and run it.">
              <Empty>
                The observatory measures; it does not estimate. Scaling fits, memory tables and external comparisons are
                all derived from runs performed here, and every extrapolated number is labelled as model output.
              </Empty>
            </Panel>
          )}

          {payload && (
            <Panel
              title={titleCase(String(payload.kind ?? kind))}
              subtitle={`${points.length || rows.length || memoryEngines.length || 0} measured entries · method: ${
                payload.method ?? "median of repeated timed runs, warm-up discarded, GC disabled during timing"
              }`}
              actions={<Tag colour="var(--c-ok)">{String(payload.mode_label ?? "SIMULATED")}</Tag>}
            >
              {payload.disclaimer && <p className="text-[11px] leading-relaxed text-[var(--c-muted)]">{payload.disclaimer}</p>}
              {payload.notes && payload.notes.length > 0 && (
                <div className="mt-2 space-y-1.5">
                  {payload.notes.map((line, index) => (
                    <div key={index} className="flex items-start gap-2 text-[11px] text-[var(--c-muted)]">
                      <span className="mt-[5px] h-1.5 w-1.5 shrink-0 rounded-full bg-[var(--c-secondary)]" />
                      {line}
                    </div>
                  ))}
                </div>
              )}
            </Panel>
          )}

          {/* -------------------------------------------------------- scaling */}
          {payload?.kind === "scaling_benchmark" && (
            <>
              {scalingChart && (
                <InView>
                  <Panel
                    title="Runtime against qubit count"
                    subtitle="Solid line: measured medians. Dashed line: the fitted exponential, including its extrapolations."
                    dense
                  >
                    <LineChart
                      x={scalingChart.axis.map((value) => value)}
                      series={scalingChart.series}
                      xLabel="qubits"
                      yLabel="seconds"
                      height={260}
                      formatY={(value) => formatSeconds(value, 2)}
                    />
                  </Panel>
                </InView>
              )}

              <Panel title="The fit, and what it does not mean" subtitle="An empirical exponent for this machine, not a law of nature." dense>
                {payload.fit?.available ? (
                  <>
                    <div className="grid gap-2 sm:grid-cols-4">
                      <StatTile
                        label="runtime multiplier"
                        value={<AnimatedNumber value={payload.fit.multiplier_per_added_qubit ?? 0} digits={3} />}
                        unit="× per qubit"
                        hint="fitted base of the exponential"
                      />
                      <StatTile
                        label="doubles every"
                        value={payload.fit.doubling_qubits === null || payload.fit.doubling_qubits === undefined ? "—" : <AnimatedNumber value={payload.fit.doubling_qubits} digits={2} />}
                        unit="qubits"
                        hint="where the fitted runtime doubles"
                      />
                      <StatTile
                        label="fit quality"
                        value={<AnimatedNumber value={payload.fit.r_squared ?? 0} digits={4} />}
                        unit="R²"
                        progress={payload.fit.r_squared}
                        hint="on log runtime"
                      />
                      <StatTile label="measured points" value={payload.fit.measurements?.length ?? 0} hint="used in the fit" />
                    </div>
                    <p className="mt-2 text-[11px] leading-relaxed text-[var(--c-text)]">{payload.fit.note}</p>
                    <p className="mt-1 text-[10px] text-[var(--c-faint)]">{payload.fit.model}</p>
                  </>
                ) : (
                  <Notice tone="warn" title="No fit attempted">{payload.fit?.reason ?? "the fit was not available"}</Notice>
                )}
              </Panel>

              <Panel title="Points" subtitle="Refusals are shown as refusals: the engine will not attempt an allocation it cannot complete.">
                <DataTable
                  columns={[
                    { key: "qubits", label: "qubits", align: "right" },
                    { key: "status", label: "status", render: (row) => <Tag colour={row.status === "measured" ? "var(--c-ok)" : "var(--c-warn)"}>{String(row.status)}</Tag> },
                    { key: "gates", label: "gates", align: "right" },
                    { key: "depth", label: "depth", align: "right" },
                    { key: "median_seconds", label: "median", align: "right", render: (row) => formatSeconds(row.median_seconds, 4) },
                    { key: "spread_seconds", label: "spread", align: "right", render: (row) => formatSeconds(row.spread_seconds, 4) },
                    { key: "memory_mb", label: "state memory", align: "right", render: (row) => formatMegabytes(row.memory_mb) },
                    {
                      key: "ops_per_second",
                      label: "ops / s",
                      align: "right",
                      render: (row) => (typeof row.ops_per_second === "number" ? row.ops_per_second.toExponential(3) : "—"),
                    },
                    { key: "reason", label: "reason", render: (row) => <span className="text-[10px] text-[var(--c-muted)]">{String(row.reason ?? "")}</span> },
                  ]}
                  rows={points as unknown as Array<Record<string, unknown>>}
                />
                {notMeasured.length > 0 && (
                  <div className="mt-3 space-y-1.5">
                    {notMeasured.map((point) => (
                      <Notice key={point.qubits} tone="warn" title={`${point.qubits} qubits — ${point.status}`}>
                        {point.reason ?? "not measured"}
                      </Notice>
                    ))}
                  </div>
                )}
              </Panel>

              {extrapolations.length > 0 && (
                <Panel title="Extrapolated points" subtitle="Computed from the fit above. Nothing in this table was executed." dense>
                  <DataTable
                    columns={[
                      { key: "qubits", label: "qubits", align: "right" },
                      { key: "predicted_seconds", label: "predicted runtime", align: "right", render: (row) => formatSeconds(row.predicted_seconds, 2) },
                      { key: "predicted_memory_mb", label: "state memory", align: "right", render: (row) => formatMegabytes(row.predicted_memory_mb) },
                      { key: "label", label: "status", render: (row) => <span className="text-[10px] text-[var(--c-warn)]">{String(row.label)}</span> },
                    ]}
                    rows={extrapolations as unknown as Array<Record<string, unknown>>}
                  />
                </Panel>
              )}
            </>
          )}

          {/* ------------------------------------------------------- backends */}
          {payload?.kind === "backend_benchmark" && (
            <>
              {engineChart && engineChart.series.length > 0 && (
                <InView>
                  <Panel title="Engines timed at each size" subtitle="A refused engine is a missing line, not a zero." dense>
                    <LineChart
                      x={engineChart.axis.map((value) => value)}
                      series={engineChart.series}
                      xLabel="qubits"
                      yLabel="seconds"
                      height={250}
                      formatY={(value) => formatSeconds(value, 2)}
                    />
                    {typeof payload.noise === "object" && payload.noise !== null && (
                      <p className="mt-1 text-[10px] text-[var(--c-faint)]">
                        Error model used: {String((payload.noise as Record<string, unknown>).name ?? "ideal")}
                      </p>
                    )}
                  </Panel>
                </InView>
              )}
              <Panel title="Engine rows" subtitle="Exactness is a property of the representation, not a score. A state vector cannot be mixed.">
                <DataTable
                  columns={[
                    { key: "qubits", label: "qubits", align: "right" },
                    { key: "backend_label", label: "engine" },
                    { key: "exact", label: "exact", render: (row) => (row.exact ? "yes" : "sampled / approximate") },
                    { key: "gates", label: "gates", align: "right" },
                    { key: "depth", label: "depth", align: "right" },
                    { key: "estimated_mb", label: "estimated state", align: "right", render: (row) => formatMegabytes(row.estimated_mb) },
                    { key: "status", label: "result", render: (row) => <Tag colour={row.status === "measured" ? "var(--c-ok)" : "var(--c-warn)"}>{String(row.status)}</Tag> },
                    { key: "median_seconds", label: "median", align: "right", render: (row) => formatSeconds(row.median_seconds, 4) },
                    { key: "spread_seconds", label: "spread", align: "right", render: (row) => formatSeconds(row.spread_seconds, 4) },
                    { key: "memory_mb", label: "actual memory", align: "right", render: (row) => formatMegabytes(row.memory_mb) },
                    {
                      key: "ops_per_second",
                      label: "ops / s",
                      align: "right",
                      render: (row) => (typeof row.ops_per_second === "number" ? row.ops_per_second.toExponential(3) : "—"),
                    },
                  ]}
                  rows={rows}
                  highlight={(row) => row.status !== "measured"}
                />
              </Panel>
            </>
          )}

          {/* ----------------------------------------------------- throughput */}
          {payload?.kind === "gate_throughput" && (
            <>
              <Panel title={`Gate cost at ${String(payload.num_qubits ?? "—")} qubits`} subtitle="Per-gate time excludes state allocation; the repetition count is in the request." dense>
                <LineChart
                  x={rows.map((row) => String(row.label))}
                  series={[
                    {
                      key: "per_gate",
                      label: "seconds per gate",
                      kind: "bar",
                      y: rows.map((row) => (typeof row.per_shot_seconds === "number" ? row.per_shot_seconds : null)),
                    },
                    {
                      key: "ops",
                      label: "operations per second (line)",
                      y: rows.map((row) => (typeof row.operations_per_second === "number" ? row.operations_per_second : null)),
                      colour: "var(--c-accent)",
                    },
                  ]}
                  xLabel="gate"
                  yLabel="per gate / throughput"
                  height={250}
                />
              </Panel>
              <Panel title="Throughput rows" dense>
                <DataTable
                  columns={[
                    { key: "label", label: "gate" },
                    { key: "trials", label: "trials", align: "right" },
                    { key: "median_seconds", label: "median (all gates)", align: "right", render: (row) => formatSeconds(row.median_seconds, 5) },
                    { key: "per_shot_seconds", label: "per gate", align: "right", render: (row) => formatSeconds(row.per_shot_seconds, 6) },
                    { key: "spread_seconds", label: "spread", align: "right", render: (row) => formatSeconds(row.spread_seconds, 5) },
                    {
                      key: "operations_per_second",
                      label: "ops / s",
                      align: "right",
                      render: (row) => (typeof row.operations_per_second === "number" ? row.operations_per_second.toExponential(3) : "—"),
                    },
                    { key: "notes", label: "notes", render: (row) => <span className="text-[10px] text-[var(--c-muted)]">{(row.notes as string[])?.join("; ")}</span> },
                  ]}
                  rows={rows}
                />
              </Panel>
            </>
          )}

          {/* --------------------------------------------------------- memory */}
          {payload?.kind === "memory_observatory" && (
            <>
              <Panel title="Budget" subtitle="QScope refuses a run rather than attempting an allocation it cannot complete." dense>
                <div className="grid gap-2 sm:grid-cols-4">
                  <StatTile label="budget" value={formatMegabytes(payload.budget_mb)} hint="per simulation" />
                  {Object.entries(payload.safe_max_qubits ?? {}).map(([engine, qubits]) => (
                    <StatTile key={engine} label={`${engine} ceiling`} value={qubits} unit="qubits" hint="largest peak footprint that fits the budget" />
                  ))}
                </div>
              </Panel>

              <Panel title="Memory per engine" subtitle="Each cell is the state footprint at that size; over-budget sizes are marked.">
                <div className="overflow-x-auto">
                  <table className="w-full border-collapse text-[11px]">
                    <thead>
                      <tr className="border-b border-[var(--c-line)]">
                        <th className="label-xs px-2 py-1.5 text-left">qubits</th>
                        {memoryEngines.map((engine) => (
                          <th key={engine} className="label-xs px-2 py-1.5 text-right">
                            {engine}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {memoryAxis.map((qubits) => (
                        <tr key={qubits} className="border-b border-[color-mix(in_oklab,var(--c-line)_50%,transparent)]">
                          <td className="mono-num px-2 py-1.5">{qubits}</td>
                          {memoryEngines.map((engine) => {
                            const entry = (memoryTables[engine] ?? []).find((candidate) => candidate.qubits === qubits);
                            return (
                              <td key={engine} className="mono-num px-2 py-1.5 text-right">
                                {entry ? (
                                  <span style={{ color: entry.fits_budget ? undefined : "var(--c-warn)" }}>
                                    {entry.human ?? formatMegabytes(entry.mb)}
                                    {entry.fits_budget ? "" : " ✗"}
                                  </span>
                                ) : (
                                  "—"
                                )}
                              </td>
                            );
                          })}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <p className="mt-2 text-[10px] text-[var(--c-faint)]">
                  ✗ marks a size whose peak footprint exceeds the budget — the same test the planner applies before a run.
                </p>
              </Panel>

              {engineSpecs.length > 0 && (
                <Panel title="Engines" subtitle="What each representation costs and what it can represent." dense>
                  <DataTable
                    columns={[
                      { key: "label", label: "engine" },
                      { key: "expression", label: "bytes per qubit", render: (row) => <span className="mono-num text-[10px]">{String(row.expression)}</span> },
                      { key: "exact", label: "exact", render: (row) => (row.exact ? "yes" : "no") },
                      { key: "supports_noise", label: "noise", render: (row) => (row.supports_noise ? "supported" : "—") },
                      { key: "max_practical_qubits", label: "practical max", align: "right" },
                      { key: "tradeoff", label: "trade-off", render: (row) => <span className="text-[10px] text-[var(--c-muted)]">{String(row.tradeoff ?? "")}</span> },
                    ]}
                    rows={engineSpecs}
                  />
                </Panel>
              )}
            </>
          )}

          {/* ------------------------------------------------------- external */}
          {payload?.kind === "external_comparison" && (
            <>
              {payload.available === false ? (
                <Panel title="No external comparison was run" subtitle="QScope will not publish a comparison it cannot measure.">
                  <Notice tone="warn" title="Nothing comparable is installed">{String(payload.reason ?? "")}</Notice>
                  {payload.detected && payload.detected.length > 0 && (
                    <div className="mt-3">
                      <SectionTitle hint="probed on the server, right now">detected in this environment</SectionTitle>
                      <DataTable
                        columns={[
                          { key: "name", label: "package" },
                          { key: "module", label: "import name", render: (row) => <span className="mono-num text-[10px]">{String(row.module)}</span> },
                          { key: "available", label: "available", render: (row) => <Tag colour={row.available ? "var(--c-ok)" : "var(--c-muted)"}>{row.available ? "installed" : "not installed"}</Tag> },
                          { key: "version", label: "version" },
                        ]}
                        rows={payload.detected as unknown as Array<Record<string, unknown>>}
                      />
                    </div>
                  )}
                </Panel>
              ) : (
                <>
                  <Panel title="Measured, side by side" subtitle={`Circuit ${String(payload.circuit ?? "")} · ${String(payload.gates ?? "—")} gates · ${String(payload.num_qubits ?? "—")} qubits`} dense>
                    <LineChart
                      x={(payload.results ?? []).map((entry) => entry.backend)}
                      series={[
                        {
                          key: "median",
                          label: "median seconds",
                          kind: "bar",
                          y: (payload.results ?? []).map((entry) => (typeof entry.median_seconds === "number" ? entry.median_seconds : null)),
                        },
                      ]}
                      xLabel="engine"
                      yLabel="seconds"
                      height={230}
                    />
                  </Panel>
                  <Panel title="Comparison rows" dense>
                    <DataTable
                      columns={[
                        { key: "backend", label: "engine" },
                        { key: "available", label: "ran", render: (row) => <Tag colour={row.available ? "var(--c-ok)" : "var(--c-warn)"}>{row.available ? "yes" : "no"}</Tag> },
                        { key: "median_seconds", label: "median", align: "right", render: (row) => formatSeconds(row.median_seconds, 4) },
                        { key: "spread_seconds", label: "spread", align: "right", render: (row) => formatSeconds(row.spread_seconds, 4) },
                        { key: "shots", label: "shots", align: "right" },
                        {
                          key: "agreement_with_qscope",
                          label: "histogram agreement",
                          align: "right",
                          render: (row) => {
                            const agreement = row.agreement_with_qscope as { total_variation: number; sampling_floor: number; consistent: boolean } | undefined;
                            if (!agreement) return "—";
                            return (
                              <span style={{ color: agreement.consistent ? "var(--c-ok)" : "var(--c-warn)" }}>
                                TV {agreement.total_variation.toPrecision(3)} (floor {agreement.sampling_floor.toPrecision(3)})
                              </span>
                            );
                          },
                        },
                        { key: "note", label: "note", render: (row) => <span className="text-[10px] text-[var(--c-muted)]">{String(row.note ?? row.reason ?? "")}</span> },
                      ]}
                      rows={(payload.results ?? []) as unknown as Array<Record<string, unknown>>}
                    />
                  </Panel>
                </>
              )}
            </>
          )}

          {/* ---------------------------------------------------------- suite */}
          {payload?.kind === "benchmark_suite" && (
            <>
              {payload.environment && (
                <Panel title="Environment" subtitle="Recorded with the measurements so they can be judged in context." dense>
                  <KeyValueList
                    columns={3}
                    items={Object.entries(payload.environment).map(([label, value]) => ({ label: label.replace(/_/g, " "), value }))}
                  />
                </Panel>
              )}
              <div className="grid gap-3 lg:grid-cols-2">
                <Panel title="Engines" subtitle="Timed at each requested size." dense>
                  {(() => {
                    const section = payload.backends as BenchmarkPayload | undefined;
                    const sectionRows = (section?.rows ?? []) as Array<Record<string, unknown>>;
                    if (!section || sectionRows.length === 0) return <Empty>Not included.</Empty>;
                    return (
                      <>
                        <DataTable
                          columns={[
                            { key: "qubits", label: "qubits", align: "right" },
                            { key: "backend_label", label: "engine" },
                            { key: "status", label: "status", render: (row) => <Tag colour={row.status === "measured" ? "var(--c-ok)" : "var(--c-warn)"}>{String(row.status)}</Tag> },
                            { key: "median_seconds", label: "median", align: "right", render: (row) => formatSeconds(row.median_seconds, 4) },
                            { key: "memory_mb", label: "memory", align: "right", render: (row) => formatMegabytes(row.memory_mb) },
                          ]}
                          rows={sectionRows}
                        />
                        <Button size="sm" variant="ghost" className="mt-2" onClick={() => setKind("backends")}>
                          open the engine benchmark →
                        </Button>
                      </>
                    );
                  })()}
                </Panel>

                <Panel title="Scaling" subtitle="Measured points and the fitted growth." dense>
                  {payload.scaling ? (
                    <>
                      <KeyValueList
                        columns={2}
                        items={[
                          { label: "points", value: payload.scaling.points?.length ?? 0 },
                          { label: "fit available", value: payload.scaling.fit?.available ? "yes" : "no" },
                          {
                            label: "multiplier per qubit",
                            value: payload.scaling.fit?.multiplier_per_added_qubit?.toPrecision(3) ?? "—",
                          },
                          { label: "R²", value: payload.scaling.fit?.r_squared?.toPrecision(4) ?? "—" },
                        ]}
                      />
                      <Button size="sm" variant="ghost" className="mt-2" onClick={() => setKind("scaling")}>
                        open the scaling benchmark →
                      </Button>
                    </>
                  ) : (
                    <Empty>Not included.</Empty>
                  )}
                </Panel>

                <Panel title="Memory" subtitle="Budgets and ceilings per engine." dense>
                  {payload.memory ? (
                    <>
                      <KeyValueList
                        columns={2}
                        items={[
                          { label: "budget", value: formatMegabytes((payload.memory as Record<string, unknown>).budget_mb) },
                          ...Object.entries(((payload.memory as Record<string, unknown>).safe_max_qubits ?? {}) as Record<string, number>).map(
                            ([engine, qubits]) => ({ label: `${engine} ceiling`, value: `${qubits} qubits` }),
                          ),
                        ]}
                      />
                      <Button size="sm" variant="ghost" className="mt-2" onClick={() => setKind("memory")}>
                        open the memory observatory →
                      </Button>
                    </>
                  ) : (
                    <Empty>Not included.</Empty>
                  )}
                </Panel>

                <Panel title="External simulators" subtitle="Only reported when actually installable and runnable." dense>
                  {payload.external && payload.external.length > 0 ? (
                    <>
                      <DataTable
                        columns={[
                          { key: "name", label: "package" },
                          { key: "module", label: "module", render: (row) => <span className="mono-num text-[10px]">{String(row.module)}</span> },
                          { key: "available", label: "installed", render: (row) => <Tag colour={row.available ? "var(--c-ok)" : "var(--c-muted)"}>{row.available ? "yes" : "no"}</Tag> },
                          { key: "version", label: "version" },
                        ]}
                        rows={payload.external as Array<Record<string, unknown>>}
                      />
                      <Button size="sm" variant="ghost" className="mt-2" onClick={() => setKind("external")}>
                        run the comparison →
                      </Button>
                    </>
                  ) : (
                    <Empty>Not probed.</Empty>
                  )}
                </Panel>
              </div>
            </>
          )}

          {/* --------------------------------------------------------- caveats */}
          {payload?.caveats && payload.caveats.length > 0 && (
            <Panel title="Caveats attached to these numbers" subtitle="Shipped with the payload so no figure can be quoted without them." dense>
              <ul className="space-y-1.5 text-[11px] leading-relaxed text-[var(--c-muted)]">
                {payload.caveats.map((caveat, index) => (
                  <li key={index} className="flex items-start gap-2">
                    <span className="mt-[5px] h-1.5 w-1.5 shrink-0 rounded-full bg-[var(--c-warn)]" />
                    {caveat}
                  </li>
                ))}
              </ul>
            </Panel>
          )}
        </div>
      </div>
    </div>
  );
}
