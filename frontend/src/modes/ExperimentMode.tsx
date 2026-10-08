/**
 * Experiment — the laboratory.
 *
 * A sweep is not a chart generator: every point is a real run, recorded with its
 * seed, shot count, engine and error model, and stored so it can be reproduced
 * later.  This view designs the sweep, streams its progress point by point, reads
 * the measured trend, and keeps the stored-runs ledger with reproduction checks
 * next to the design so "which run produced this point?" is always answerable.
 */

import { useEffect, useMemo, useRef, useState } from "react";
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
  Segmented,
  Select,
  StatTile,
  Tag,
  TextInput,
  Toggle,
  WarningList,
} from "../components/ui";
import { InspectBars, LineChart } from "../components/viz/charts";
import { formatMegabytes, formatSeconds, sortedProbabilities, titleCase } from "../lib/format";
import { api, type ExperimentRow, type StoredExperiment } from "../lib/api";
import { useStore } from "../state/store";

type Kind =
  | "algorithm_scaling"
  | "noise_sweep"
  | "backend_comparison"
  | "optimizer_comparison"
  | "shots_convergence"
  | "parameter_sweep"
  | "custom";

const KINDS: Array<{ value: Kind; label: string }> = [
  { value: "algorithm_scaling", label: "algorithm scaling" },
  { value: "noise_sweep", label: "noise sweep" },
  { value: "backend_comparison", label: "engine comparison" },
  { value: "optimizer_comparison", label: "optimization study" },
  { value: "shots_convergence", label: "shot convergence" },
  { value: "parameter_sweep", label: "parameter sweep" },
  { value: "custom", label: "custom cartesian sweep" },
];

interface AxisDraft {
  name: string;
  values: string;
}

interface SeriesBlock {
  x?: Array<string | number>;
  x_label?: string;
  series?: Array<{ key: string; label: string; y: Array<number | null> }>;
}

interface AggregateBlock {
  rows?: number;
  summary?: Record<string, { min: number; max: number; mean: number }>;
  best_success?: ExperimentRow;
  fastest?: ExperimentRow;
  largest_circuit?: ExperimentRow;
  growth?: { qubit_delta: number; runtime_ratio: number; seconds_per_added_qubit: number | null; note: string } | null;
}

/** Numbers stay numbers, everything else (levels, engine names) stays a label. */
function parseToken(token: string): number | string {
  const text = token.trim();
  if (!text) return "";
  const numeric = Number(text);
  return Number.isFinite(numeric) ? numeric : text;
}

function parseList(text: string): Array<number | string> {
  return text
    .split(/[,\s]+/)
    .map(parseToken)
    .filter((value) => value !== "");
}

/** Shot counts as bars. InspectBars scales to the largest value, so counts are fine. */
function countBars(counts: Record<string, number>, limit = 10): Array<{ label: string; value: number }> {
  return Object.entries(counts)
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .slice(0, limit)
    .map(([basis, count]) => ({ label: `|${basis}⟩`, value: count }));
}

function parsePairs(text: string): Record<string, unknown> {
  const pairs: Record<string, unknown> = {};
  for (const chunk of text.split(/[\n;,]+/)) {
    const [rawKey, rawValue] = chunk.split("=");
    const key = (rawKey ?? "").trim();
    if (!key) continue;
    pairs[key] = parseToken(rawValue ?? "");
  }
  return pairs;
}

const GAMMA_AXIS = Array.from({ length: 9 }, (_, index) => ((Math.PI * index) / 8).toFixed(4)).join(", ");

/** The axes a kind needs, derived from the catalogue defaults. */
function axesFor(kind: Kind, defaults: Record<string, unknown>): AxisDraft[] {
  const qubits = Array.isArray(defaults.qubits) ? (defaults.qubits as number[]).join(", ") : String(defaults.num_qubits ?? 4);
  switch (kind) {
    case "algorithm_scaling":
      return [{ name: "num_qubits", values: qubits }];
    case "noise_sweep":
      return [{ name: "noise", values: "0, 0.01, 0.02, 0.05, 0.1, 0.2" }];
    case "backend_comparison":
      return [];
    case "optimizer_comparison":
      return [{ name: "level", values: "safe, standard, aggressive" }];
    case "shots_convergence":
      return [{ name: "shots", values: "64, 256, 1024, 4096, 16384" }];
    case "parameter_sweep":
      return [{ name: String(defaults.axis ?? "gamma"), values: GAMMA_AXIS }];
    default:
      return [{ name: "num_qubits", values: "2, 3, 4, 5" }];
  }
}

function fixedFor(kind: Kind, defaults: Record<string, unknown>): string {
  const algorithm = typeof defaults.algorithm === "string" ? defaults.algorithm : "grover";
  if (kind === "backend_comparison" || kind === "noise_sweep" || kind === "optimizer_comparison" || kind === "shots_convergence") {
    return `algorithm=${algorithm}, num_qubits=${defaults.num_qubits ?? 4}`;
  }
  if (kind === "custom") return "num_qubits=4";
  return "";
}

export function ExperimentMode({ onNavigate }: { onNavigate: (mode: ModeKey) => void }) {
  const {
    meta,
    settings,
    setSettings,
    setSource,
    loading,
    errors,
    experiment,
    experimentProgress,
    runExperiment,
    streamExperiment,
    buildReport,
    history,
    refreshHistory,
    deleteStored,
    reproduce,
  } = useStore();

  const [tab, setTab] = useState<"sweep" | "history">("sweep");
  const [catalogKey, setCatalogKey] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [kind, setKind] = useState<Kind>("algorithm_scaling");
  const [algorithm, setAlgorithm] = useState("grover");
  const [axes, setAxes] = useState<AxisDraft[]>([{ name: "num_qubits", values: "2, 3, 4, 5, 6" }]);
  const [fixedText, setFixedText] = useState("");
  const [shots, setShots] = useState(settings.shots);
  const [seed, setSeed] = useState(12345);
  const [maxCombinations, setMaxCombinations] = useState(64);
  const [storeRuns, setStoreRuns] = useState(true);
  const [formError, setFormError] = useState("");
  const [selectedRow, setSelectedRow] = useState<number | null>(null);
  const [stream, setStream] = useState<{ close: () => void } | null>(null);
  const streamRef = useRef<{ close: () => void } | null>(null);

  // history lab
  const [search, setSearch] = useState("");
  const [marks, setMarks] = useState<string[]>([]);
  const [comparison, setComparison] = useState<{
    experiments: StoredExperiment[];
    rows?: Array<{ metric: string; key: string; values: unknown[]; delta: number | null }>;
    verdict?: string[];
  } | null>(null);
  const [historyError, setHistoryError] = useState("");
  const [reproduction, setReproduction] = useState<Awaited<ReturnType<typeof api.historyReproduce>> | null>(null);

  const currentNoise = () => {
    if (settings.noiseStrength > 0) {
      const base =
        settings.noise.name && settings.noise.name !== "ideal"
          ? settings.noise
          : { name: "depolarizing", params: { p: 0.05 } };
      return { ...base, scale: settings.noiseStrength };
    }
    return settings.noise;
  };

  const buildRequest = (): Record<string, unknown> | null => {
    setFormError("");
    const axisMap: Record<string, Array<number | string>> = {};
    for (const axis of axes) {
      const axisName = axis.name.trim();
      const values = parseList(axis.values);
      if (axisName && values.length) axisMap[axisName] = values;
    }
    if (kind === "custom" && Object.keys(axisMap).length === 0) {
      setFormError("A custom experiment needs at least one axis with at least one value.");
      return null;
    }
    const fixed = parsePairs(fixedText);
    const request: Record<string, unknown> = {
      key: catalogKey ?? `${algorithm}_${kind}`,
      kind,
      axes: axisMap,
      fixed,
      shots,
      seed,
      backend: settings.backend,
      noise: currentNoise(),
      optimizer_level: settings.optimizerLevel,
      store: storeRuns,
      max_combinations: maxCombinations,
    };
    if (name.trim()) request.name = name.trim();
    if (kind !== "custom") request.algorithm = algorithm;
    return request;
  };

  const applyCatalog = (entry: { key: string; name: string; kind: string; defaults: Record<string, unknown> }) => {
    const entryKind = (KINDS.some((option) => option.value === entry.kind) ? entry.kind : "custom") as Kind;
    setCatalogKey(entry.key);
    setName(entry.name);
    setKind(entryKind);
    const defaults = entry.defaults ?? {};
    if (typeof defaults.algorithm === "string") setAlgorithm(defaults.algorithm);
    setAxes(axesFor(entryKind, defaults));
    setFixedText(fixedFor(entryKind, defaults));
  };

  const seriesBlock = (experiment?.series ?? {}) as SeriesBlock;
  const aggregates = useMemo(() => (experiment?.aggregates ?? {}) as AggregateBlock, [experiment]);
  const chartX = useMemo(() => (seriesBlock.x ?? []).map((value) => value), [seriesBlock.x]);
  const chartSeries = (seriesBlock.series ?? []).map((entry) => ({ ...entry, y: entry.y ?? [] }));
  const hasChart = chartSeries.length > 0 && chartSeries.some((entry) => entry.y.some((value) => typeof value === "number"));
  const rows = experiment?.rows ?? [];
  const detail = selectedRow !== null ? rows[selectedRow] : undefined;

  const startStream = () => {
    const request = buildRequest();
    if (!request) return;
    const handle = streamExperiment(request as Record<string, unknown>);
    streamRef.current = handle;
    setStream(handle);
  };

  // The server closes the socket when the sweep finishes, so the "stop" control has to
  // follow the run rather than stay on screen next to a finished sweep.
  useEffect(() => {
    if (stream && !loading.experiment) {
      streamRef.current?.close();
      streamRef.current = null;
      setStream(null);
    }
  }, [stream, loading.experiment]);

  // Navigating away mid-sweep must not leave the stream open.
  useEffect(() => () => streamRef.current?.close(), []);

  const filteredHistory = useMemo(() => {
    const needle = search.trim().toLowerCase();
    if (!needle) return history;
    return history.filter((entry) =>
      [entry.name, entry.circuit_name, entry.algorithm, entry.experiment_id, entry.backend, entry.tags.join(" ")]
        .join(" ")
        .toLowerCase()
        .includes(needle),
    );
  }, [history, search]);

  const compareMarks = async (ids: string[]) => {
    setHistoryError("");
    try {
      const payload = await api.historyCompare(ids);
      setComparison(payload as typeof comparison);
    } catch (error) {
      setHistoryError((error as Error).message);
    }
  };

  const loadPoint = async (experimentId: string | null) => {
    if (!experimentId) return;
    setHistoryError("");
    try {
      const stored = await api.historyGet(experimentId);
      if (stored.circuit) {
        await setSource({ circuit: stored.circuit });
        onNavigate("build");
      }
    } catch (error) {
      setHistoryError((error as Error).message);
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <Segmented
          value={tab}
          options={[
            { value: "sweep", label: "sweep laboratory" },
            { value: "history", label: `stored runs (${history.length})` },
          ]}
          onChange={setTab}
        />
        <span className="text-[11px] text-[var(--c-muted)]">
          {tab === "sweep"
            ? "Design a parameter sweep, run it, and read the trend from measured points."
            : "Every stored run keeps its seed and error model, so it can be reproduced and compared."}
        </span>
      </div>

      {tab === "sweep" ? (
        <div className="grid gap-4 xl:grid-cols-[360px_1fr]">
          {/* ------------------------------------------------------- designer */}
          <div className="space-y-3">
            <Panel title="Ready-made experiments" subtitle="Catalogue entries, loaded into the designer." dense>
              <div className="space-y-1.5">
                {(meta?.experiments ?? []).map((entry) => (
                  <button
                    key={entry.key}
                    type="button"
                    onClick={() => applyCatalog(entry as { key: string; name: string; kind: string; defaults: Record<string, unknown> })}
                    className={`focus-ring w-full rounded-lg border px-2.5 py-1.5 text-left transition-colors ${
                      catalogKey === entry.key
                        ? "border-[var(--c-primary)] bg-[color-mix(in_oklab,var(--c-primary)_9%,transparent)]"
                        : "border-[var(--c-line)] hover:border-[var(--c-line-strong)]"
                    }`}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="truncate text-[11px] font-medium">{entry.name}</span>
                      <span className="mono-num shrink-0 text-[10px] text-[var(--c-faint)]">{entry.kind.replace(/_/g, " ")}</span>
                    </div>
                    <p className="mt-0.5 text-[10px] leading-snug text-[var(--c-muted)]">{entry.description}</p>
                  </button>
                ))}
              </div>
            </Panel>

            <Panel title="Sweep design" subtitle="Cartesian product of the axes below; each point is one real run." dense>
              <div className="space-y-3">
                <Field label="kind">
                  <Select value={kind} options={KINDS} onChange={(value) => setKind(value)} />
                </Field>

                <Field label="name" hint="Used for the stored record and the report title.">
                  <TextInput value={name} onChange={setName} placeholder="mysweep" />
                </Field>

                {kind !== "custom" && (
                  <Field label="algorithm">
                    <Select
                      value={algorithm}
                      options={(meta?.algorithms ?? []).map((entry) => ({ value: entry.key, label: entry.name }))}
                      onChange={setAlgorithm}
                    />
                  </Field>
                )}

                <div className="space-y-2">
                  <SectionTitle hint="name → comma-separated values">axes</SectionTitle>
                  {axes.map((axis, index) => (
                    <div key={index} className="space-y-1">
                      <div className="flex items-center gap-1.5">
                        <TextInput
                          value={axis.name}
                          onChange={(value) => setAxes((current) => current.map((entry, position) => (position === index ? { ...entry, name: value } : entry)))}
                          placeholder="num_qubits"
                        />
                        <Button
                          size="sm"
                          variant="danger"
                          onClick={() => setAxes((current) => current.filter((_, position) => position !== index))}
                        >
                          ×
                        </Button>
                      </div>
                      <TextInput
                        value={axis.values}
                        onChange={(value) => setAxes((current) => current.map((entry, position) => (position === index ? { ...entry, values: value } : entry)))}
                        placeholder="2, 3, 4, 5"
                      />
                    </div>
                  ))}
                  <Button size="sm" variant="outline" onClick={() => setAxes((current) => [...current, { name: "", values: "" }])}>
                    add axis
                  </Button>
                </div>

                <Field label="fixed parameters" hint="key=value pairs, comma separated. Applied to every point.">
                  <textarea
                    className="mono-num focus-ring w-full rounded-lg border border-[var(--c-line)] bg-[color-mix(in_oklab,var(--c-bg)_70%,transparent)] px-2.5 py-1.5 text-[12px] text-[var(--c-text)]"
                    rows={2}
                    value={fixedText}
                    placeholder="num_qubits=4"
                    onChange={(event) => setFixedText(event.target.value)}
                  />
                </Field>

                <div className="grid grid-cols-3 gap-2">
                  <Field label="shots">
                    <NumberInput value={shots} min={1} max={1000000} onChange={setShots} />
                  </Field>
                  <Field label="seed">
                    <NumberInput value={seed} step={1} onChange={setSeed} />
                  </Field>
                  <Field label="max points">
                    <NumberInput value={maxCombinations} min={1} max={512} onChange={setMaxCombinations} />
                  </Field>
                </div>

                <Field label="engine">
                  <Segmented
                    value={settings.backend}
                    size="sm"
                    options={[
                      { value: "auto", label: "auto" },
                      { value: "statevector", label: "statevector" },
                      { value: "density_matrix", label: "density" },
                      { value: "trajectory", label: "trajectory" },
                    ]}
                    onChange={(value) => setSettings({ backend: value })}
                  />
                </Field>

                <Toggle checked={storeRuns} onChange={setStoreRuns} label="record every run in the history database" />

                <div className="flex flex-wrap gap-2">
                  <Button
                    variant="primary"
                    disabled={loading.experiment}
                    onClick={() => {
                      const request = buildRequest();
                      if (request) void runExperiment(request);
                    }}
                  >
                    {loading.experiment && !experimentProgress ? "running…" : "run sweep"}
                  </Button>
                  {stream ? (
                    <Button
                      variant="danger"
                      onClick={() => {
                        stream.close();
                        setStream(null);
                      }}
                    >
                      stop stream
                    </Button>
                  ) : (
                    <Button variant="outline" disabled={loading.experiment} onClick={startStream}>
                      run live
                    </Button>
                  )}
                </div>

                {formError && <Notice tone="danger">{formError}</Notice>}
                {errors.experiment && <Notice tone="danger" title="Sweep refused">{errors.experiment}</Notice>}

                {experimentProgress && (
                  <div className="space-y-1.5">
                    <div className="flex items-center justify-between text-[10px]">
                      <span className="text-[var(--c-muted)]">
                        point {experimentProgress.index + 1} of {experimentProgress.total}
                      </span>
                      <span className="mono-num truncate text-[var(--c-faint)]">{experimentProgress.label}</span>
                    </div>
                    <div className="h-1.5 overflow-hidden rounded-full bg-[var(--c-line)]/50">
                      <div
                        className="h-full rounded-full bg-[var(--c-primary)] transition-all duration-300"
                        style={{ width: `${experimentProgress.total ? ((experimentProgress.index + 1) / experimentProgress.total) * 100 : 0}%` }}
                      />
                    </div>
                  </div>
                )}

                <p className="text-[10px] leading-relaxed text-[var(--c-faint)]">
                  Axes are swept as a cartesian product. Values are parsed as numbers when they look like numbers, so
                  optimization levels (“safe”, “standard”) and engine names work as axes too.
                </p>
              </div>
            </Panel>
          </div>

          {/* -------------------------------------------------------- results */}
          <div className="space-y-3">
            {experiment ? (
              <>
                <Panel
                  title={experiment.spec?.name ?? "sweep"}
                  subtitle={`${String(experiment.spec?.kind ?? "").replace(/_/g, " ")} · ${experiment.rows.length} measured points · ${experiment.seconds.toFixed(2)} s total`}
                  actions={
                    <>
                      <Button size="sm" variant="outline" onClick={() => onNavigate("trace")}>
                        trace this circuit →
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => {
                          const request = buildRequest();
                          if (request) void buildReport("experiment", request, `${experiment.spec?.name ?? "sweep"} report`, name || undefined);
                        }}
                      >
                        build report
                      </Button>
                    </>
                  }
                >
                  <p className="text-[12px] leading-relaxed text-[var(--c-text)]">{experiment.headline}</p>
                  {experiment.plan_note && <p className="mt-1 text-[10px] text-[var(--c-faint)]">{experiment.plan_note}</p>}
                  <div className="mt-3 grid gap-2 sm:grid-cols-4">
                    <StatTile label="points measured" value={<AnimatedNumber value={experiment.rows.length} digits={0} />} hint="every row is a completed run" />
                    <StatTile
                      label="best success"
                      value={aggregates.best_success?.success_probability !== null && aggregates.best_success?.success_probability !== undefined ? (
                        <AnimatedNumber value={aggregates.best_success.success_probability} digits={4} />
                      ) : (
                        "n/a"
                      )}
                      hint={aggregates.best_success?.label ?? "no success measure for this kind"}
                      progress={aggregates.best_success?.success_probability ?? undefined}
                    />
                    <StatTile
                      label="fastest point"
                      value={formatSeconds(aggregates.fastest?.runtime_seconds)}
                      hint={aggregates.fastest?.label ?? "—"}
                    />
                    <StatTile
                      label="largest circuit"
                      value={`${aggregates.largest_circuit?.qubits ?? "—"}q`}
                      hint={`${aggregates.largest_circuit?.gates ?? "—"} gates`}
                    />
                  </div>
                  {aggregates.growth && (
                    <div className="mt-3">
                      <KeyValueList
                        columns={3}
                        items={[
                          { label: "qubit span", value: aggregates.growth.qubit_delta },
                          { label: "runtime ratio", value: `${aggregates.growth.runtime_ratio.toPrecision(3)}×` },
                          {
                            label: "seconds / added qubit",
                            value:
                              aggregates.growth.seconds_per_added_qubit === null
                                ? "—"
                                : aggregates.growth.seconds_per_added_qubit.toPrecision(3),
                          },
                        ]}
                      />
                      <p className="mt-1 text-[10px] text-[var(--c-faint)]">{aggregates.growth.note}</p>
                    </div>
                  )}
                  <div className="mt-3 space-y-1.5">
                    {experiment.observations.map((observation, index) => (
                      <div key={index} className="flex items-start gap-2 text-[11px] text-[var(--c-muted)]">
                        <span className="mt-[5px] h-1.5 w-1.5 shrink-0 rounded-full bg-[var(--c-primary)]" />
                        {observation}
                      </div>
                    ))}
                  </div>
                  <div className="mt-3">
                    <WarningList warnings={experiment.warnings} notes={[]} />
                  </div>
                </Panel>

                {hasChart && (
                  <InView>
                    <Panel
                      title="Measured trend"
                      subtitle={`x axis: ${seriesBlock.x_label ?? "run index"}. One line per recorded metric.`}
                      dense
                    >
                      <LineChart
                        x={chartX}
                        series={chartSeries.map((entry) => ({ key: entry.key, label: entry.label, y: entry.y }))}
                        xLabel={seriesBlock.x_label}
                        yLabel="value"
                        height={250}
                      />
                      <p className="mt-1 text-[10px] text-[var(--c-faint)]">
                        Lines are drawn only between measured points. Nothing here is interpolated or fitted unless a
                        benchmark says so explicitly.
                      </p>
                    </Panel>
                  </InView>
                )}

                <Panel title="Every measured point" subtitle="Select a row to inspect it." actions={<Tag>{experiment.rows.length} rows</Tag>}>
                  <DataTable
                    columns={[
                      { key: "index", label: "#", align: "right", width: "34px" },
                      { key: "label", label: "point" },
                      { key: "qubits", label: "qubits", align: "right" },
                      { key: "gates", label: "gates", align: "right" },
                      { key: "depth", label: "depth", align: "right" },
                      {
                        key: "runtime_seconds",
                        label: "runtime",
                        align: "right",
                        render: (row) => formatSeconds(row.runtime_seconds),
                      },
                      {
                        key: "distribution_distance",
                        label: "TV distance",
                        align: "right",
                        render: (row) =>
                          typeof row.distribution_distance === "number" ? row.distribution_distance.toPrecision(3) : "—",
                      },
                      {
                        key: "success_probability",
                        label: "success",
                        align: "right",
                        render: (row) =>
                          typeof row.success_probability === "number" ? row.success_probability.toFixed(4) : "—",
                      },
                      {
                        key: "fidelity_vs_ideal",
                        label: "fidelity",
                        align: "right",
                        render: (row) =>
                          typeof row.fidelity_vs_ideal === "number" ? row.fidelity_vs_ideal.toFixed(5) : "—",
                      },
                      {
                        key: "entanglement_status",
                        label: "entanglement",
                        render: (row) => (
                          <span className="text-[10px] text-[var(--c-muted)]">{String(row.entanglement_status ?? "—")}</span>
                        ),
                      },
                      {
                        key: "mode",
                        label: "mode",
                        render: (row) => (
                          <Tag colour={row.mode === "NOISY SIMULATION" ? "var(--c-warn)" : "var(--c-ok)"}>{String(row.mode)}</Tag>
                        ),
                      },
                    ]}
                    rows={experiment.rows as unknown as Array<Record<string, unknown>>}
                    onRowClick={(row) => setSelectedRow(Number(row.index))}
                    selected={(row) => Number(row.index) === selectedRow}
                  />
                </Panel>

                {detail && (
                  <InView>
                    <Panel
                      title={`Point ${detail.label}`}
                      subtitle={`${detail.backend} · ${detail.mode} · seed recorded with the run`}
                      actions={
                        <Button size="sm" variant="outline" disabled={!detail.experiment_id} onClick={() => void loadPoint(detail.experiment_id)}>
                          open circuit in builder →
                        </Button>
                      }
                    >
                      <p className="text-[11px] leading-relaxed text-[var(--c-text)]">{detail.observation}</p>
                      <div className="mt-3 grid gap-3 lg:grid-cols-2">
                        <div>
                          <SectionTitle hint="born distribution of this point">exact probabilities</SectionTitle>
                          <InspectBars
                            items={sortedProbabilities(detail.ideal_probabilities, 10).map((entry) => ({
                              label: `|${entry.basis}⟩`,
                              value: entry.probability,
                            }))}
                          />
                        </div>
                        <div>
                          <SectionTitle hint="sampled vs exact">histogram against the exact distribution</SectionTitle>
                          <InspectBars
                            items={sortedProbabilities(detail.ideal_probabilities, 10).map((entry) => ({
                              label: `|${entry.basis}⟩`,
                              value: detail.sampled_probabilities[entry.basis] ?? 0,
                              secondary: entry.probability,
                            }))}
                            colour="var(--c-secondary)"
                            overlay="var(--c-primary)"
                          />
                          <p className="mt-2 text-[10px] text-[var(--c-faint)]">
                            Total variation between the two: {detail.distribution_distance.toPrecision(3)} — that gap is
                            shot noise, not an error model.
                          </p>
                        </div>
                      </div>
                      <div className="mt-3">
                        <KeyValueList
                          columns={3}
                          items={[
                            { label: "top outcome", value: detail.top_outcome ?? "—" },
                            { label: "top count", value: detail.top_count ?? "—" },
                            { label: "success definition", value: detail.success_definition },
                            { label: "purity", value: detail.purity?.toFixed(5) ?? "—" },
                            { label: "entropy (bits)", value: detail.entropy?.toFixed(5) ?? "—" },
                            { label: "max concurrence", value: detail.max_concurrence?.toFixed(5) ?? "—" },
                            { label: "analytic success", value: detail.analytic_success?.toFixed(5) ?? "—" },
                            { label: "analytic deviation", value: detail.analytic_deviation?.toFixed(5) ?? "—" },
                            { label: "model error budget", value: detail.estimated_error_budget?.toFixed(5) ?? "—" },
                            { label: "memory", value: formatMegabytes(detail.memory_mb) },
                            { label: "two-qubit gates", value: detail.two_qubit_gates },
                            { label: "stored id", value: detail.experiment_id ?? "not stored" },
                          ]}
                        />
                      </div>
                      {Object.keys(detail.extra ?? {}).length > 0 && (
                        <div className="mt-3">
                          <SectionTitle hint="whatever the runner recorded for this kind">extra data</SectionTitle>
                          <pre className="mono-num max-h-52 overflow-auto rounded-lg border border-[var(--c-line)] p-2 text-[10px] leading-relaxed text-[var(--c-muted)]">
                            {JSON.stringify(detail.extra, null, 2)}
                          </pre>
                        </div>
                      )}
                    </Panel>
                  </InView>
                )}

                {aggregates.summary && (
                  <Panel title="Aggregates" subtitle="Min, mean and max over the measured points — computed by the runner, not the browser." dense>
                    <DataTable
                      columns={[
                        { key: "metric", label: "metric" },
                        { key: "min", label: "min", align: "right", render: (row) => Number(row.min).toPrecision(4) },
                        { key: "mean", label: "mean", align: "right", render: (row) => Number(row.mean).toPrecision(4) },
                        { key: "max", label: "max", align: "right", render: (row) => Number(row.max).toPrecision(4) },
                      ]}
                      rows={Object.entries(aggregates.summary).map(([metric, values]) => ({ metric: titleCase(metric), ...values }))}
                    />
                  </Panel>
                )}
              </>
            ) : (
              <Panel title="Nothing measured yet" subtitle="Design a sweep on the left and run it.">
                <Empty>
                  Pick one of the ready-made experiments, adjust its axes, and run it. Every point becomes a stored run
                  with its own seed, so a chart can always be traced back to the inputs that produced it.
                </Empty>
              </Panel>
            )}
          </div>
        </div>
      ) : (
        /* ------------------------------------------------------- history lab */
        <div className="space-y-3">
          <Panel
            title="Stored runs"
            subtitle={`${history.length} most recent runs in the history database. Nothing is recomputed here: the numbers are the ones recorded at run time.`}
            actions={
              <>
                <Button size="sm" variant="outline" disabled={loading.history} onClick={() => void refreshHistory({ limit: 50 })}>
                  {loading.history ? "refreshing…" : "refresh"}
                </Button>
                <a
                  className="focus-ring rounded-lg border border-[var(--c-line)] px-2.5 py-1 text-[11px] text-[var(--c-text)] hover:border-[var(--c-primary)]"
                  href="/api/history/export?format=csv"
                >
                  export csv
                </a>
                <a
                  className="focus-ring rounded-lg border border-[var(--c-line)] px-2.5 py-1 text-[11px] text-[var(--c-text)] hover:border-[var(--c-primary)]"
                  href="/api/history/export?format=json"
                >
                  export json
                </a>
              </>
            }
          >
            <div className="space-y-3">
              <Field label="search" hint="Matching happens in the browser over the loaded page; the server has a full search too.">
                <TextInput value={search} onChange={setSearch} placeholder="circuit name, algorithm, tag, id…" />
              </Field>

              {historyError && <Notice tone="danger">{historyError}</Notice>}

              <DataTable
                columns={[
                  { key: "created_at", label: "when", render: (row) => String(row.created_at).replace("T", " ").slice(0, 19) },
                  { key: "name", label: "run" },
                  { key: "num_qubits", label: "qubits", align: "right" },
                  { key: "gate_count", label: "gates", align: "right" },
                  { key: "depth", label: "depth", align: "right" },
                  { key: "backend", label: "engine" },
                  {
                    key: "shots",
                    label: "shots",
                    align: "right",
                    render: (row) => Number(row.shots).toLocaleString(),
                  },
                  { key: "seed", label: "seed", align: "right" },
                  {
                    key: "runtime_seconds",
                    label: "runtime",
                    align: "right",
                    render: (row) => formatSeconds(row.runtime_seconds),
                  },
                  {
                    key: "mode",
                    label: "mode",
                    render: (row) => <Tag colour={row.mode === "NOISY SIMULATION" ? "var(--c-warn)" : "var(--c-ok)"}>{String(row.mode)}</Tag>,
                  },
                  {
                    key: "reproducibility",
                    label: "reproduce",
                    render: (row) => (
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => {
                          void (async () => {
                            const outcome = await reproduce(String(row.experiment_id));
                            if (outcome) setReproduction(outcome);
                          })();
                        }}
                      >
                        re-run
                      </Button>
                    ),
                  },
                ]}
                rows={filteredHistory as unknown as Array<Record<string, unknown>>}
                onRowClick={(row) => {
                  const id = String(row.experiment_id);
                  setMarks((current) => (current.includes(id) ? current.filter((entry) => entry !== id) : [...current, id].slice(-4)));
                }}
                selected={(row) => marks.includes(String(row.experiment_id))}
              />

              <div className="flex flex-wrap items-center gap-2">
                <Tag colour={marks.length >= 2 ? "var(--c-primary)" : undefined}>
                  {marks.length} selected — click rows to select 2 or more
                </Tag>
                <Button size="sm" variant="primary" disabled={marks.length < 2} onClick={() => void compareMarks(marks)}>
                  compare selected
                </Button>
                <Button size="sm" variant="ghost" onClick={() => setMarks([])}>
                  clear selection
                </Button>
                {marks.length >= 1 && (
                  <Button
                    size="sm"
                    variant="danger"
                    onClick={() => {
                      void (async () => {
                        for (const id of marks) await deleteStored(id);
                        setMarks([]);
                        setComparison(null);
                      })();
                    }}
                  >
                    delete selected
                  </Button>
                )}
              </div>
            </div>
          </Panel>

          {comparison && (
            <Panel
              title="Stored-run comparison"
              subtitle={`${comparison.experiments.length} runs compared on the numbers recorded at run time.`}
              actions={
                <Button size="sm" variant="ghost" onClick={() => setComparison(null)}>
                  close
                </Button>
              }
            >
              <div className="grid gap-3 lg:grid-cols-2">
                {comparison.experiments.map((entry) => (
                  <div key={entry.experiment_id} className="space-y-2">
                    <SectionTitle hint={`${entry.backend} · seed ${entry.seed} · ${entry.shots} shots`}>{entry.name}</SectionTitle>
                    <InspectBars
                      items={sortedProbabilities(
                        Object.fromEntries(
                          Object.entries(entry.counts).map(([basis, count]) => [basis, count / Math.max(entry.shots, 1)]),
                        ),
                        10,
                      ).map((bucket) => ({ label: `|${bucket.basis}⟩`, value: bucket.probability }))}
                      colour="var(--c-secondary)"
                    />
                    <KeyValueList
                      columns={2}
                      items={[
                        { label: "qubits", value: entry.num_qubits },
                        { label: "gates", value: entry.gate_count },
                        { label: "depth", value: entry.depth },
                        { label: "purity", value: entry.metrics?.purity?.toFixed(5) ?? "—" },
                        { label: "entropy", value: entry.metrics?.entropy?.toFixed(5) ?? "—" },
                        { label: "entanglement", value: entry.metrics?.entanglement_status ?? "—" },
                        { label: "runtime", value: formatSeconds(entry.runtime_seconds) },
                        { label: "mode", value: entry.mode },
                      ]}
                    />
                  </div>
                ))}
              </div>

              {comparison.rows && comparison.rows.length > 0 && (
                <div className="mt-3">
                  <SectionTitle hint="first selected → last selected">deltas</SectionTitle>
                  <DataTable
                    columns={[
                      { key: "metric", label: "metric" },
                      ...comparison.experiments.map((entry, index) => ({
                        key: entry.experiment_id,
                        label: `run ${index + 1}`,
                        align: "right" as const,
                        render: (row: Record<string, unknown>) => {
                          const values = row.values as unknown[];
                          const value = values[index];
                          return typeof value === "number" ? value.toPrecision(4) : String(value ?? "—");
                        },
                      })),
                      {
                        key: "delta",
                        label: "Δ (last − first)",
                        align: "right",
                        render: (row) =>
                          typeof row.delta === "number" ? (
                            <span style={{ color: row.delta < 0 ? "var(--c-ok)" : row.delta > 0 ? "var(--c-warn)" : undefined }}>
                              {row.delta.toPrecision(4)}
                            </span>
                          ) : (
                            "—"
                          ),
                      },
                    ]}
                    rows={comparison.rows as unknown as Array<Record<string, unknown>>}
                  />
                </div>
              )}

              {comparison.verdict && comparison.verdict.length > 0 && (
                <div className="mt-3 space-y-1.5">
                  {comparison.verdict.map((line, index) => (
                    <div key={index} className="flex items-start gap-2 text-[11px] text-[var(--c-muted)]">
                      <span className="mt-[5px] h-1.5 w-1.5 shrink-0 rounded-full bg-[var(--c-secondary)]" />
                      {line}
                    </div>
                  ))}
                </div>
              )}
            </Panel>
          )}

          {reproduction && (
            <Panel
              title={`Reproduction of ${reproduction.experiment_id}`}
              subtitle="The stored circuit, engine, shots, seed and error model were re-run exactly as recorded."
              actions={
                <Button size="sm" variant="ghost" onClick={() => setReproduction(null)}>
                  close
                </Button>
              }
            >
              <p className="text-[12px] leading-relaxed text-[var(--c-text)]">{reproduction.verdict}</p>
              <div className="mt-3 grid gap-2 sm:grid-cols-4">
                <StatTile label="distribution distance" value={<AnimatedNumber value={reproduction.distribution_distance} digits={5} />} hint="TV between the two histograms" />
                <StatTile label="expected shot noise" value={<AnimatedNumber value={reproduction.expected_shot_noise} digits={5} />} hint="what re-sampling alone would produce" />
                <StatTile label="original runtime" value={formatSeconds(reproduction.original.runtime_seconds)} hint={reproduction.original.backend} />
                <StatTile label="re-run runtime" value={formatSeconds(reproduction.rerun.runtime_seconds)} hint={reproduction.rerun.backend} />
              </div>
              <div className="mt-3 grid gap-3 lg:grid-cols-2">
                <div>
                  <SectionTitle hint="recorded counts, scaled to the largest">original histogram</SectionTitle>
                  <InspectBars items={countBars(reproduction.original.counts)} />
                </div>
                <div>
                  <SectionTitle hint="just re-run counts">re-run histogram</SectionTitle>
                  <InspectBars items={countBars(reproduction.rerun.counts)} colour="var(--c-secondary)" />
                </div>
              </div>
              <p className="mt-2 text-[10px] leading-relaxed text-[var(--c-faint)]">{reproduction.note}</p>
            </Panel>
          )}

          {history.length === 0 && (
            <Panel title="No stored runs" subtitle="Nothing has been recorded in the history database yet.">
              <Empty>
                Run a sweep, or execute a circuit with “store” enabled. Stored runs carry their circuit, seed and error
                model, which is what makes them reproducible rather than merely recalled.
              </Empty>
            </Panel>
          )}
        </div>
      )}
    </div>
  );
}
