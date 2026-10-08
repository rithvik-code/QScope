/**
 * Execute — run the circuit and read the result properly.
 *
 * The point of this view is that a result is never just a histogram: the plan that
 * chose the engine, the mode it ran under, the exact-versus-sampled distinction,
 * the fidelity against the ideal reference when there is noise, and the timing and
 * memory it cost are all on screen together.
 */

import { useMemo, useState } from "react";
import { AnimatedNumber, InView, MeterBar } from "../components/motion";
import { Button, Field, Notice, Panel, Provenance, Segmented, Slider, StatTile, Tag, WarningList } from "../components/ui";
import { CompareBars, Heatmap, InspectBars, LineChart } from "../components/viz/charts";
import { AmplitudeBars, DensityView, PhaseDial } from "../components/viz/quantum";
import type { ModeKey } from "../components/Shell";
import { formatBytes, formatMegabytes, formatPercent, formatSeconds, sortedCounts, sortedProbabilities } from "../lib/format";
import { useStore } from "../state/store";

export function ExecuteMode({ onNavigate }: { onNavigate: (mode: ModeKey) => void }) {
  const {
    result,
    plan,
    document: circuit,
    settings,
    setSettings,
    loading,
    errors,
    simulate,
    planRun,
    traceCircuit,
  } = useStore();
  const [selectedBasis, setSelectedBasis] = useState<string | null>(null);
  const [distribution, setDistribution] = useState<"counts" | "ideal" | "state">("counts");

  const counts = useMemo(() => (result ? sortedCounts(result.counts, 18) : []), [result]);
  const ideal = useMemo(() => (result ? sortedProbabilities(result.ideal_probabilities, 18) : []), [result]);
  const amplitudes = useMemo(() => result?.statevector?.amplitudes ?? [], [result]) as Array<{
    basis: string;
    real: number;
    imag: number;
    magnitude: number;
    probability: number;
    phase: number;
  }>;

  const shotRecords = result?.shot_records ?? [];

  return (
    <div className="space-y-4">          <FieldGuide
            modeName="Execute"
            onDismiss={() => {}}
        slides={[
          {
            heading: "What you are looking at",
            steps: [
              {
                title: "Left column: the exact values recorded with the run",
                body: "The Run settings panel is where you choose shots, seed, engine, noise strength, and whether to keep this run in history. These are the values the engine will record — not a separate ‘confirm’ step. The Execution plan below it tells you which engine was chosen and what it will cost: state size, peak memory, budget, and a safe max qubit count.",
                pointer: "Run settings → shots, seed, engine, noise strength, memorise in history; Execution plan → state size, peak, budget, safe max",
              },
              {
                title: "Top-right: the result, with provenance baked in",
                body: "After you press execute, the Result panel shows the mode the run ran under (SIMULATED, NOISY SIMULATION, or REAL HARDWARE), the backend and representation the engine picked, the shot count and seed, and the provenance strip that says exactly what was computed. From there you can trace every gate, or jump to the analyse view.",
                pointer: "Result caption → mode, backend, shots, seed, noise; Provenance strip",
                tip: "provable provenance strip",
              },
              {
                title: "Right column: read the result three ways",
                body: "The Outcome distribution panel lets you switch between sampled counts (the histogram you actually measured), the exact Born distribution of the final state, and the full amplitude/phase list. The Phase structure panel gives every amplitude as a phasor and reports entanglement, purity, entropy, and the dominant basis. The Ideal vs noisy panel compares this run to the same circuit run with no error model — both are computed, not assumed.",
                pointer: "Outcome distribution → counts / exact / amplitudes toggle; Phase structure; Ideal vs noisy",
                highlight: 3,
                tip: "ways to read one result",
              },
            ],
          },
          {
            heading: "How to actually use this page",
            steps: [
              {
                title: "Run it once to see the shape of the answer",
                body: "Press execute with the default settings and watch the result appear. Then switch the distribution tab between counts, exact, and amplitudes to see the same final state from three angles. The thin white edge on the counts bars is the exact probability — differences of order √shots are sampling noise, not a bug.",
                pointer: "execute, then Outcome distribution → toggle the segmented control",
              },
              {
                title: "Turn on noise to see what breaks",
                body: "Drag the noise strength slider up and run again. The mode label switches to NOISY SIMULATION, a fidelity-vs-ideal and trace-distance appear, and the Ideal vs noisy panel lights up. Noise off is an exact unitary evolution; anything else is a simulation of an imperfect run.",
                pointer: "Run settings → noise strength; Result → fidelity vs ideal, trace distance, Ideal vs noisy",
              },
              {
                title: "When you want to see every gate, go to Trace",
                body: "Execute gives you the final state. Select ‘trace every gate’ on the result panel to open the debugger and watch the state evolve step by step — or just navigate to the Trace mode from the rail.",
                pointer: "Result → trace every gate →, or the rail → Trace",
              },
            ],
          },
        ]}
      />

      <div className="grid gap-4 xl:grid-cols-[320px_1fr]">
        {/* -------------------------------------------------------- controls */}
        <div className="space-y-3">
          <Panel title="Run settings" subtitle="These are the exact values recorded with the result." dense>
            <div className="space-y-3">
              <Field label="shots">
                <div className="space-y-1.5">
                  <input
                    type="number"
                    min={1}
                    max={1000000}
                    className="mono-num w-full rounded-lg border border-[var(--c-line)] bg-[color-mix(in_oklab,var(--c-bg)_70%,transparent)] px-2 py-1.5 text-[12px]"
                    value={settings.shots}
                    onChange={(event) => setSettings({ shots: Math.max(1, Number(event.target.value) || 1) })}
                  />
                  <div className="flex gap-1.5">
                    {[256, 2048, 16384, 65536].map((value) => (
                      <Button key={value} size="sm" variant="ghost" onClick={() => setSettings({ shots: value })}>
                        {value >= 1000 ? `${value / 1000}k` : value}
                      </Button>
                    ))}
                  </div>
                </div>
              </Field>

              <Field label="seed" hint="The same seed reproduces the same sampled histogram on the same engine.">
                <input
                  type="number"
                  className="mono-num w-full rounded-lg border border-[var(--c-line)] bg-[color-mix(in_oklab,var(--c-bg)_70%,transparent)] px-2 py-1.5 text-[12px]"
                  value={settings.seed}
                  onChange={(event) => setSettings({ seed: Number(event.target.value) || 0 })}
                />
              </Field>

              <Field label="engine">
                <Segmented
                  value={settings.backend}
                  options={[
                    { value: "auto", label: "auto" },
                    { value: "statevector", label: "statevector" },
                    { value: "density_matrix", label: "density" },
                    { value: "trajectory", label: "trajectory" },
                  ]}
                  onChange={(value) => setSettings({ backend: value })}
                  size="sm"
                />
              </Field>

              <Field
                label={`noise strength — ${settings.noiseStrength.toFixed(2)}`}
                hint={
                  settings.noiseStrength > 0
                    ? "Every channel probability is scaled to this value; the run becomes NOISY SIMULATION."
                    : "Noise off: the run is an exact unitary evolution."
                }
              >
                <Slider
                  value={settings.noiseStrength}
                  onChange={(value) => setSettings({ noiseStrength: value })}
                  format={(value) => value.toFixed(2)}
                />
              </Field>

              <Field label="memorise in history">
                <Segmented
                  value={settings.store ? "yes" : "no"}
                  options={[
                    { value: "yes", label: "store" },
                    { value: "no", label: "discard" },
                  ]}
                  onChange={(value) => setSettings({ store: value === "yes" })}
                  size="sm"
                />
              </Field>

              <div className="flex gap-2">
                <Button variant="primary" disabled={loading.simulate} onClick={() => void simulate()}>
                  {loading.simulate ? "running…" : "execute"}
                </Button>
                <Button variant="outline" disabled={loading.plan} onClick={() => void planRun()}>
                  plan only
                </Button>
              </div>
              {errors.simulate && <Notice tone="danger" title="The engine refused this run">{errors.simulate}</Notice>}
            </div>
          </Panel>

          {(plan || result?.plan) && (
            <Panel title="Execution plan" subtitle="Why this engine, and what it will cost." dense>
              <div className="space-y-2">
                <div className="flex flex-wrap gap-1.5">
                  <Tag colour="var(--c-secondary)">{(plan ?? result?.plan)!.backend_label}</Tag>
                  <Tag>{(plan ?? result?.plan)!.representation}</Tag>
                  {(plan ?? result?.plan)!.exact ? <Tag colour="var(--c-ok)">exact</Tag> : <Tag colour="var(--c-warn)">sampled / approximate</Tag>}
                  {(plan ?? result?.plan)!.auto_selected && <Tag>chosen automatically</Tag>}
                </div>
                <div className="grid grid-cols-2 gap-2">
                  <StatTile label="state size" value={formatMegabytes((plan ?? result?.plan)!.estimated_mb)} hint="one copy" />
                  <StatTile label="peak" value={formatMegabytes((plan ?? result?.plan)!.estimated_peak_mb)} hint="during the run" />
                  <StatTile label="budget" value={formatMegabytes((plan ?? result?.plan)!.budget_mb)} hint="QSCOPE_MEMORY_MB" />
                  <StatTile label="safe max" value={`${(plan ?? result?.plan)!.safe_max_qubits}q`} hint="within budget" />
                </div>
                {plan?.budget && <p className="text-[10px] text-[var(--c-faint)]">budget source: {plan.budget.source}</p>}
                <WarningList warnings={(plan ?? result?.plan)!.warnings} notes={(plan ?? result?.plan)!.notes} />
              </div>
            </Panel>
          )}
        </div>

        {/* ---------------------------------------------------------- result */}
        <div className="space-y-3">
          {!result ? (
            <Panel title="Result" subtitle="Nothing executed yet.">
              <Notice tone="info">
                Press <strong>execute</strong>. The engine decides the representation (a statevector cannot represent a
                mixed state, so noise forces the density-matrix or trajectory engine), runs the circuit, samples the
                shots and records everything above with the result.
              </Notice>
            </Panel>
          ) : (
            <>
              <Panel
                title={`${result.circuit_name} — ${result.mode}`}
                subtitle={`${result.backend} · ${result.shots.toLocaleString()} shots · seed ${result.seed}${result.noise.name ? ` · ${result.noise.name}` : ""}`}
                actions={
                  <>
                    <Button size="sm" variant="outline" onClick={() => void traceCircuit(null)}>
                      trace every gate →
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => onNavigate("analyze")}>
                      analyse
                    </Button>
                  </>
                }
              >
                <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                  <StatTile label="runtime" value={<AnimatedNumber value={result.timing?.total_seconds ?? 0} digits={4} />} unit="s" hint={result.timing?.per_shot_seconds ? `${(result.timing.per_shot_seconds * 1e6).toFixed(1)} µs / shot` : ""} />
                  <StatTile label="state memory" value={formatMegabytes(result.memory?.state_mb)} hint={result.plan?.representation} />
                  <StatTile
                    label="fidelity vs ideal"
                    value={result.fidelity_vs_ideal === null ? "n/a" : <AnimatedNumber value={result.fidelity_vs_ideal} digits={5} />}
                    progress={result.fidelity_vs_ideal ?? undefined}
                    colour={result.fidelity_vs_ideal !== null && result.fidelity_vs_ideal < 0.95 ? "var(--c-warn)" : undefined}
                    hint={result.fidelity_vs_ideal === null ? "ideal run — no reference to compare" : "state fidelity to the exact reference"}
                  />
                  <StatTile
                    label="trace distance"
                    value={result.trace_distance_vs_ideal === null ? "n/a" : <AnimatedNumber value={result.trace_distance_vs_ideal} digits={5} />}
                    hint="0 means indistinguishable"
                  />
                </div>

                <div className="mt-3">
                  <Provenance
                    mode={result.mode}
                    backend={result.backend}
                    representation={result.plan?.representation}
                    exact={result.plan?.exact}
                    seed={result.seed}
                    shots={result.shots}
                    noise={result.noise.name ?? "ideal"}
                    seconds={result.timing?.total_seconds}
                    memoryMb={result.memory?.state_mb}
                    extra={[
                      { label: "measured wires", value: result.measured_qubits.map((wire) => `q${wire}`).join(", ") || "—" },
                      { label: "recorded at", value: result.timestamp || "—" },
                    ]}
                  />
                </div>

                {(result.warnings.length > 0 || result.notes.length > 0) && (
                  <div className="mt-3">
                    <WarningList warnings={result.warnings} notes={result.notes} />
                  </div>
                )}
              </Panel>

              <div className="grid gap-3 lg:grid-cols-2">
                <Panel
                  title="Outcome distribution"
                  subtitle={
                    distribution === "counts"
                      ? `${result.shots.toLocaleString()} sampled shots`
                      : distribution === "ideal"
                        ? "exact Born distribution of the final state"
                        : "amplitudes and phases of the state vector"
                  }
                  actions={
                    <Segmented
                      value={distribution}
                      options={[
                        { value: "counts", label: "counts" },
                        { value: "ideal", label: "exact" },
                        { value: "state", label: "amplitudes" },
                      ]}
                      onChange={setDistribution}
                      size="sm"
                    />
                  }
                >
                  {distribution === "counts" && (
                    <>
                      <InspectBars
                        items={counts.map((entry) => ({
                          label: `|${entry.basis}⟩`,
                          value: entry.count,
                          secondary: result.ideal_probabilities[entry.basis] !== undefined ? result.ideal_probabilities[entry.basis] * result.shots : undefined,
                        }))}
                        onSelect={(label) => setSelectedBasis(label.replace(/[|⟩]/g, ""))}
                        selected={selectedBasis}
                        overlay="var(--c-text)"
                      />
                      <p className="mt-2 text-[10px] text-[var(--c-faint)]">
                        The thin white edge marks the exact probability scaled by the shot count. Differences of order
                        √shots are sampling, not physics.
                      </p>
                    </>
                  )}
                  {distribution === "ideal" && (
                    <>
                      <InspectBars
                        items={ideal.map((entry) => ({ label: `|${entry.basis}⟩`, value: entry.probability }))}
                        colour="var(--c-secondary)"
                        onSelect={(label) => setSelectedBasis(label.replace(/[|⟩]/g, ""))}
                        selected={selectedBasis}
                      />
                      <p className="mt-2 text-[10px] text-[var(--c-faint)]">
                        This is the Born distribution of the reported state — exact, not sampled.
                      </p>
                    </>
                  )}
                  {distribution === "state" &&
                    (amplitudes.length ? (
                      <AmplitudeBars amplitudes={amplitudes} selected={selectedBasis} onSelect={setSelectedBasis} />
                    ) : (
                      <Notice tone="info">
                        The engine did not return a state vector for this run (the density-matrix and trajectory engines
                        report a mixed state or per-shot records instead).
                      </Notice>
                    ))}
                </Panel>

                <Panel title="Phase structure" subtitle="Every amplitude as a phasor; colour is the phase." dense>
                  {amplitudes.length ? (
                    <div className="flex flex-col items-center gap-3 sm:flex-row">
                      <PhaseDial amplitudes={amplitudes} />
                      <div className="flex-1 space-y-2">
                        {result.metrics?.entanglement_status && (
                          <div className="flex items-center justify-between text-[11px]">
                            <span className="text-[var(--c-muted)]">entanglement</span>
                            <Tag colour={result.metrics.entanglement_status.startsWith("ENTANGLED") ? "var(--c-accent)" : "var(--c-muted)"}>
                              {result.metrics.entanglement_status}
                            </Tag>
                          </div>
                        )}
                        <div className="flex items-center justify-between text-[11px]">
                          <span className="text-[var(--c-muted)]">purity</span>
                          <span className="mono-num">{result.metrics?.purity?.toFixed(6) ?? "—"}</span>
                        </div>
                        <div className="flex items-center justify-between text-[11px]">
                          <span className="text-[var(--c-muted)]">entropy</span>
                          <span className="mono-num">{result.metrics?.entropy?.toFixed(6) ?? "—"} bits</span>
                        </div>
                        <div className="flex items-center justify-between text-[11px]">
                          <span className="text-[var(--c-muted)]">support</span>
                          <span className="mono-num">{result.metrics?.support_size ?? "—"} states</span>
                        </div>
                        {result.metrics?.dominant_basis && (
                          <div className="text-[10px] text-[var(--c-faint)]">
                            dominant basis |{result.metrics.dominant_basis}⟩ at{" "}
                            {formatPercent(result.metrics.dominant_probability, 2)}
                          </div>
                        )}
                      </div>
                    </div>
                  ) : (
                    <p className="text-[11px] text-[var(--c-faint)]">
                      Phase is only meaningful for a state vector. Run with the state-vector engine on an ideal circuit
                      to see it.
                    </p>
                  )}
                </Panel>
              </div>

              {result.ideal_metrics && (
                <Panel
                  title="Ideal vs noisy"
                  subtitle="The reference is the same circuit with no error model — computed, not assumed."
                >
                  <CompareBars
                    rows={[
                      { metric: "purity", a: result.ideal_metrics.purity ?? 0, b: result.metrics.purity ?? 0, delta: (result.metrics.purity ?? 0) - (result.ideal_metrics.purity ?? 0) },
                      { metric: "entropy (bits)", a: result.ideal_metrics.entropy ?? 0, b: result.metrics.entropy ?? 0, delta: (result.metrics.entropy ?? 0) - (result.ideal_metrics.entropy ?? 0) },
                      {
                        metric: "support size",
                        a: result.ideal_metrics.support_size ?? 0,
                        b: result.metrics.support_size ?? 0,
                        delta: (result.metrics.support_size ?? 0) - (result.ideal_metrics.support_size ?? 0),
                      },
                      {
                        metric: "dominant probability",
                        a: result.ideal_metrics.dominant_probability ?? 0,
                        b: result.metrics.dominant_probability ?? 0,
                        delta: (result.metrics.dominant_probability ?? 0) - (result.ideal_metrics.dominant_probability ?? 0),
                      },
                    ]}
                  />
                  <p className="mt-2 text-[10px] text-[var(--c-faint)]">
                    Left bar: ideal. Right bar: this run. Both were computed by the engine from the same circuit.
                  </p>
                </Panel>
              )}

              {result.density_matrix && (
                <Panel title="Density matrix" subtitle="Real part; red is negative." dense>
                  <DensityView matrix={result.density_matrix as never} qubits={circuit?.num_qubits ?? 0} />
                </Panel>
              )}

              {shotRecords.length > 0 && (
                <Panel
                  title="Per-shot records"
                  subtitle={`${shotRecords.length} shots kept${shotRecords.length > 24 ? " (first 24 shown)" : ""} — the evidence behind the histogram.`}
                  dense
                >
                  <div className="grid gap-1 sm:grid-cols-4 lg:grid-cols-6">
                    {shotRecords.slice(0, 24).map((record, index) => (
                      <div key={index} className="panel-flat px-2 py-1.5">
                        <div className="label-xs">shot {index}</div>
                        <div className="mono-num truncate text-[11px]">{JSON.stringify(record).slice(0, 32)}</div>
                      </div>
                    ))}
                  </div>
                </Panel>
              )}

              <InView>
                <Panel title="Timing breakdown" subtitle="Where the wall-clock time went." dense>
                  <div className="space-y-1.5">
                    {Object.entries(result.timing ?? {})
                      .filter(([, value]) => typeof value === "number")
                      .slice(0, 8)
                      .map(([key, value]) => (
                        <div key={key} className="flex items-center gap-3">
                          <span className="w-40 shrink-0 truncate text-[11px] text-[var(--c-muted)]">{key.replace(/_/g, " ")}</span>
                          <MeterBar
                            value={(value as number) / Math.max(result.timing.total_seconds ?? 1, 1e-9)}
                            height={4}
                          />
                          <span className="mono-num w-24 shrink-0 text-right text-[10px]">{formatSeconds(value as number)}</span>
                        </div>
                      ))}
                  </div>
                  <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-4">
                    {Object.entries(result.memory ?? {})
                      .slice(0, 4)
                      .map(([key, value]) => (
                        <StatTile key={key} label={key.replace(/_/g, " ")} value={formatBytes(value)} />
                      ))}
                  </div>
                </Panel>
              </InView>

              <Panel title="Summary digest" subtitle="The same numbers the assistant reads when you ask it about this run." dense>
                <div className="grid gap-2 sm:grid-cols-2">
                  <LineChart
                    x={ideal.slice(0, 10).map((entry) => entry.basis)}
                    series={[
                      {
                        key: "ideal",
                        label: "exact probability",
                        y: ideal.slice(0, 10).map((entry) => entry.probability),
                        kind: "bar",
                        colour: "var(--c-secondary)",
                      },
                      {
                        key: "sampled",
                        label: "sampled frequency",
                        y: ideal.slice(0, 10).map((entry) => (result.sampled_probabilities[entry.basis] ?? 0)),
                        kind: "scatter",
                        colour: "var(--c-primary)",
                      },
                    ]}
                    yLabel="probability"
                    xLabel="outcome"
                    height={200}
                  />
                  <div className="space-y-2">
                    {result.metrics?.pauli_expectations && Object.keys(result.metrics.pauli_expectations).length > 0 ? (
                      <Heatmap
                        data={Object.entries(result.metrics.pauli_expectations).map(([, value]) => [Number(value)])}
                        size={140}
                        caption="Pauli expectation values, each in [-1, 1]"
                      />
                    ) : (
                      <p className="text-[11px] text-[var(--c-faint)]">No Pauli expectations were reported for this run.</p>
                    )}
                    <p className="text-[10px] leading-relaxed text-[var(--c-faint)]">
                      Only measured quantities are shown. Where a metric does not apply to this engine or state, the
                      panel says so instead of printing a substitute.
                    </p>
                  </div>
                </div>
              </Panel>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
