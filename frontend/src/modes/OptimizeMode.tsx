/**
 * Optimize — verified rewrites, circuit evolution and hardware mapping.
 *
 * The rule this view enforces: an optimisation is only reported together with the
 * proof that produced it.  A saving that could not be verified is shown as failed,
 * not as an improvement.
 */

import { useState } from "react";
import { AnimatedNumber } from "../components/motion";
import type { ModeKey } from "../components/Shell";
import { Button, CodeBlock, Field, Notice, Panel, SectionTitle, Segmented, Select, StatTile, Tag } from "../components/ui";
import { CompareBars, LineChart } from "../components/viz/charts";
import { CircuitCanvas } from "../components/viz/quantum";
import { formatSeconds } from "../lib/format";
import { useStore } from "../state/store";
import { FieldGuide } from "../components/Guide";

const PROOF_LABELS: Record<string, { label: string; colour: string; note: string }> = {
  PROVEN_EQUIVALENT: {
    label: "proven equivalent",
    colour: "var(--c-ok)",
    note: "every segment's unitary matches the original up to a global phase",
  },
  VERIFIED_ON_RANDOM_INPUTS: {
    label: "verified on random inputs",
    colour: "var(--c-warn)",
    note: "the circuits were compared on sampled states — strong evidence, not a proof",
  },
  VERIFICATION_FAILED: {
    label: "verification failed",
    colour: "var(--c-danger)",
    note: "this rewrite did not reproduce the original and was rolled back",
  },
  NOT_VERIFIED: { label: "not verified", colour: "var(--c-muted)", note: "verification was switched off" },
};

export function OptimizeMode({ onNavigate }: { onNavigate: (mode: ModeKey) => void }) {
  const {
    meta,
    document: circuit,
    optimization,
    evolution,
    hardware,
    settings,
    setSettings,
    loading,
    errors,
    optimize,
    evolve,
    analyseHardware,
    setSource,
    buildReport,
  } = useStore();
  const [tab, setTab] = useState<"optimize" | "evolve" | "hardware">("optimize");
  const [device, setDevice] = useState("linear_5");
  const [generations, setGenerations] = useState(4);
  const [population, setPopulation] = useState(8);

  const verification = optimization ? PROOF_LABELS[optimization.verification.status] : null;

  return (
    <div className="space-y-4">
      <FieldGuide
        modeName="Optimize"
        slides={[
          {
            heading: "What you are looking at",
            steps: [
              {
                title: "The optimiser tab is the one you will use first",
                body: "The Verified optimisation panel is where you pick a level and whether to verify every rewrite, then press optimise. The result panel reports passes applied, the before → after gate count, depth, two-qubit gates, and the gate reduction fraction, all with the verification status attached. A saving that could not be verified is shown as failed, not as an improvement.",
                pointer: "Verified optimisation panel → level, verify / parse only, optimise; Result panel → passes, gates, depth, 2-qubit gates, reduction, verification tag",
              },
              {
                title: "Circuit evolution is a search, not a single rewrite",
                body: "The evolution tab runs a population of candidate circuits for a number of generations and reports the best one it found, with the verification status of the final result. The hardware mapping tab is a different question: it estimates how the current circuit would sit on a specific device topology.",
                pointer: "segmented control — optimiser / circuit evolution / hardware mapping; evolution panel → generations, population, evolve; hardware panel → device, analyse hardware",
              },
              {
                title: "The proof is part of the result, not an footnote",
                body: "Every optimisation result carries a verification label — proven equivalent, verified on random inputs, verification failed, or not verified. If verification is on and a rewrite did not reproduce the original, it is rolled back. If verification is off, the result is reported as NOT_VERIFIED so you can see the difference.",
                pointer: "Result panel → verification tag and method; the proof line under the result",
                tip: "verification is optional but the label is always shown",
              },
            ],
          },
          {
            heading: "How to use this page",
            steps: [
              {
                title: "Start from a circuit you can compare against",
                body: "The optimiser reads the circuit that is currently loaded. If you have not built or executed one yet the panels will still render, but the before → after comparison you care about needs a circuit to begin with. Load one from Build, or execute one from Execute and come back.",
                pointer: "top bar — the loaded circuit name, gates and depth; if it says no circuit, go load one first",
                highlight: 1,
                tip: "one loaded circuit is enough to start",
              },
              {
                title: "Pick a level, decide on verification, then optimise",
                body: "The level selector chooses how aggressive the rewrites are — the hint under it says what each level does. Verification compares segment unitaries, so it is slower but gives you a proof. With it off you get a faster parse-only pass that is reported as NOT_VERIFIED. The first time, the safe choice is verify every rewrite.",
                pointer: "level → select; verify every rewrite / parse only → segmented; optimise → primary button",
              },
              {
                title: "Load the optimised circuit when you want to keep it",
                body: "If the result has an optimised circuit, the load optimised circuit button puts it back into the editor so you can run it again, trace it, or optimise it further. The optimiser itself does not replace the circuit you started with — you choose when to take the result.",
                pointer: "Result panel actions → load optimised circuit; then run it from Execute or trace it from Trace",
              },
            ],
          },
        ]}
      />
      <div className="flex flex-wrap items-center gap-2">
        <Segmented
          value={tab}
          options={[
            { value: "optimize", label: "optimiser" },
            { value: "evolve", label: "circuit evolution" },
            { value: "hardware", label: "hardware mapping" },
          ]}
          onChange={setTab}
        />
        <span className="text-[11px] text-[var(--c-muted)]">
          {circuit ? `${circuit.name} · ${circuit.resources.gates} gates · depth ${circuit.resources.depth}` : "no circuit"}
        </span>
      </div>

      {tab === "optimize" && (
        <>
          <Panel
            title="Verified optimisation"
            subtitle="Every rewrite is checked against the original; a failed check is rolled back."
          >
            <div className="grid gap-3 sm:grid-cols-[220px_1fr_auto] sm:items-end">
              <Field
                label="level"
                hint={(meta?.optimizer_levels ?? []).find((level) => level.key === settings.optimizerLevel)?.description ?? ""}
              >
                <Select
                  value={settings.optimizerLevel}
                  options={(meta?.optimizer_levels ?? []).map((level) => ({ value: level.key, label: level.label }))}
                  onChange={(value) => setSettings({ optimizerLevel: value as typeof settings.optimizerLevel })}
                />
              </Field>
              <div className="flex flex-wrap items-center gap-3">
                <Segmented
                  value={settings.verify ? "verify" : "fast"}
                  options={[
                    { value: "verify", label: "verify every rewrite" },
                    { value: "fast", label: "parse only (unsafe)" },
                  ]}
                  onChange={(value) => setSettings({ verify: value === "verify" })}
                  size="sm"
                />
                <span className="text-[10px] text-[var(--c-faint)]">
                  Verification compares segment unitaries; with it off, a rewrite is reported as NOT_VERIFIED.
                </span>
              </div>
              <Button variant="primary" disabled={loading.optimize} onClick={() => void optimize()}>
                {loading.optimize ? "optimising…" : "optimise"}
              </Button>
            </div>
            {errors.optimize && (
              <div className="mt-2">
                <Notice tone="danger" title="Optimisation failed">{errors.optimize}</Notice>
              </div>
            )}
          </Panel>

          {optimization && (
            <>
              <Panel
                title={optimization.headline || "Result"}
                subtitle={`${optimization.passes_applied.length} passes applied in ${formatSeconds(optimization.seconds)}`}
                actions={
                  <>
                    {verification && <Tag colour={verification.colour} title={verification.note}>{verification.label}</Tag>}
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => {
                        if (optimization.optimized) void setSource({ circuit: optimization.optimized });
                      }}
                    >
                      load optimised circuit
                    </Button>
                  </>
                }
              >
                <div className="grid gap-2 sm:grid-cols-4">
                  <StatTile label="gates" value={`${optimization.before.gates} → ${optimization.after.gates}`} hint={`${optimization.improvements.gates_saved ?? 0} saved`} />
                  <StatTile label="depth" value={`${optimization.before.depth} → ${optimization.after.depth}`} hint={`${optimization.improvements.depth_saved ?? 0} layers saved`} />
                  <StatTile
                    label="two-qubit gates"
                    value={`${optimization.before.two_qubit_gates} → ${optimization.after.two_qubit_gates}`}
                    hint="the expensive ones on real hardware"
                  />
                  <StatTile
                    label="gate reduction"
                    value={
                      <AnimatedNumber
                        value={
                          optimization.before.gates > 0
                            ? (optimization.improvements.gates_saved ?? 0) / optimization.before.gates
                            : 0
                        }
                        digits={4}
                        suffix=""
                      />
                    }
                    hint="fraction of the original gate count"
                    progress={optimization.before.gates > 0 ? (optimization.improvements.gates_saved ?? 0) / optimization.before.gates : 0}
                  />
                </div>

                {optimization.verification.method && (
                  <div className="mt-3">
                    <Notice tone={optimization.verification.status === "PROVEN_EQUIVALENT" ? "ok" : "warn"} title={`Verification: ${optimization.verification.status}`}>
                      method: {optimization.verification.method}
                      {optimization.verification.max_deviation !== undefined && (
                        <> · largest deviation {optimization.verification.max_deviation.toExponential(3)}</>
                      )}
                      {optimization.verification.reason && <> · {optimization.verification.reason}</>}
                    </Notice>
                  </div>
                )}

                <div className="mt-3 grid gap-3 lg:grid-cols-2">
                  <div>
                    <SectionTitle hint="before">original circuit</SectionTitle>
                    <div className="rounded-lg border border-[var(--c-line)] p-1.5">
                      <CircuitCanvas circuit={optimization.circuit} compact />
                    </div>
                  </div>
                  <div>
                    <SectionTitle hint="after">optimised circuit</SectionTitle>
                    <div className="rounded-lg border border-[var(--c-line)] p-1.5">
                      <CircuitCanvas circuit={optimization.optimized ?? null} compact />
                    </div>
                  </div>
                </div>
              </Panel>

              <div className="grid gap-3 lg:grid-cols-[1fr_360px]">
                <Panel title="Rewrites, in order" subtitle="Each row is one attempt; a rejected attempt says why." dense>
                  <div className="space-y-1">
                    {optimization.steps.length === 0 && (
                      <p className="text-[11px] text-[var(--c-faint)]">
                        No rewrites were available at this level — the circuit is already in the chosen normal form.
                      </p>
                    )}
                    {optimization.steps.map((step, index) => (
                      <div key={index} className="rounded-md border border-[var(--c-line)] px-2 py-1.5">
                        <div className="flex items-center gap-2">
                          <span className="mono-num w-6 shrink-0 text-[10px] text-[var(--c-faint)]">{index}</span>
                          <span className="mono-num text-[11px] text-[var(--c-primary)]">{step.rule}</span>
                          <span className="truncate text-[10px] text-[var(--c-muted)]">{step.description}</span>
                          <Tag colour={step.verified ? "var(--c-ok)" : "var(--c-warn)"} title={step.reason ?? ""}>
                            {step.verified ? "verified" : "rejected"}
                          </Tag>
                        </div>
                        {(step.removed.length > 0 || step.added.length > 0) && (
                          <div className="mono-num mt-0.5 text-[10px] text-[var(--c-faint)]">
                            {step.removed.length > 0 && <span className="text-[var(--c-accent)]">− {step.removed.join(" ")} </span>}
                            {step.added.length > 0 && <span className="text-[var(--c-primary)]">+ {step.added.join(" ")}</span>}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                </Panel>

                <div className="space-y-3">
                  <Panel title="Opportunity audit" subtitle="Read-only: what could be simplified, before touching anything." dense>
                    {optimization.opportunities.length === 0 ? (
                      <p className="text-[11px] text-[var(--c-faint)]">No patterns found.</p>
                    ) : (
                      <div className="space-y-1">
                        {optimization.opportunities.map((finding, index) => (
                          <div key={index} className="text-[11px]">
                            <span className="mono-num text-[var(--c-primary)]">{String(finding.rule ?? finding.kind)}</span>
                            <span className="ml-2 text-[var(--c-muted)]">{String(finding.description ?? "")}</span>
                          </div>
                        ))}
                      </div>
                    )}
                  </Panel>
                  <Panel title="Comparison" subtitle="Measured counts, not estimates." dense>
                    <CompareBars
                      rows={[
                        { metric: "gates", a: optimization.before.gates, b: optimization.after.gates, delta: optimization.after.gates - optimization.before.gates },
                        { metric: "depth", a: optimization.before.depth, b: optimization.after.depth, delta: optimization.after.depth - optimization.before.depth },
                        {
                          metric: "2-qubit gates",
                          a: optimization.before.two_qubit_gates,
                          b: optimization.after.two_qubit_gates,
                          delta: optimization.after.two_qubit_gates - optimization.before.two_qubit_gates,
                        },
                      ]}
                    />
                    {optimization.notes.length > 0 && (
                      <ul className="mt-2 space-y-1 text-[10px] text-[var(--c-faint)]">
                        {optimization.notes.map((note, index) => (
                          <li key={index}>• {note}</li>
                        ))}
                      </ul>
                    )}
                  </Panel>
                  <Panel title="Write it up" dense>
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => void buildReport("optimization", { source: { circuit }, level: settings.optimizerLevel, verify: settings.verify })}
                    >
                      optimisation report
                    </Button>
                  </Panel>
                </div>
              </div>

              {optimization.qubit_map && (
                <Panel title="Qubit map" subtitle="Compaction removed unused wires; this says where each logical wire went." dense>
                  <div className="flex flex-wrap gap-2">
                    {Object.entries(optimization.qubit_map).map(([from, to]) => (
                      <Tag key={from} colour="var(--c-secondary)">
                        q{from} → q{to}
                      </Tag>
                    ))}
                  </div>
                </Panel>
              )}
            </>
          )}
        </>
      )}

      {tab === "evolve" && (
        <div className="space-y-4">
          <Panel
            title="Circuit evolution"
            subtitle="Search for alternative implementations of the same task, ranked by fidelity first and cost second."
          >
            <div className="grid gap-3 sm:grid-cols-4 sm:items-end">
              <Field label="generations">
                <input
                  type="number"
                  min={0}
                  max={60}
                  className="mono-num w-full rounded-lg border border-[var(--c-line)] bg-[color-mix(in_oklab,var(--c-bg)_70%,transparent)] px-2 py-1.5 text-[12px]"
                  value={generations}
                  onChange={(event) => setGenerations(Math.max(0, Math.min(60, Number(event.target.value) || 0)))}
                />
              </Field>
              <Field label="population">
                <input
                  type="number"
                  min={2}
                  max={64}
                  className="mono-num w-full rounded-lg border border-[var(--c-line)] bg-[color-mix(in_oklab,var(--c-bg)_70%,transparent)] px-2 py-1.5 text-[12px]"
                  value={population}
                  onChange={(event) => setPopulation(Math.max(2, Math.min(64, Number(event.target.value) || 2)))}
                />
              </Field>
              <div className="text-[10px] leading-relaxed text-[var(--c-faint)]">
                Fitness is the process fidelity against the target unitary minus a cost penalty; candidates below 50 %
                fidelity are reported as search debris rather than offered as implementations.
              </div>
              <Button variant="primary" disabled={loading.evolve} onClick={() => void evolve(generations, population)}>
                {loading.evolve ? "evolving…" : "evolve"}
              </Button>
            </div>
            {errors.evolve && (
              <div className="mt-2">
                <Notice tone="danger" title="Evolution failed">{errors.evolve}</Notice>
              </div>
            )}
          </Panel>

          {evolution && (
            <>
              <Panel title={evolution.headline || "Candidates"} subtitle={`${evolution.candidates.length} distinct candidates · seed ${evolution.seed}`}>
                {evolution.generations.length > 0 && (
                  <LineChart
                    x={evolution.generations.map((generation) => generation.generation)}
                    series={[
                      {
                        key: "best",
                        label: "best fitness",
                        y: evolution.generations.map((generation) => generation.best_fitness),
                        kind: "line",
                        colour: "var(--c-primary)",
                      },
                      {
                        key: "mean",
                        label: "mean fitness",
                        y: evolution.generations.map((generation) => generation.mean_fitness),
                        kind: "line",
                        colour: "var(--c-secondary)",
                        dashed: true,
                      },
                    ]}
                    xLabel="generation"
                    yLabel="fitness"
                    height={200}
                  />
                )}
                {evolution.best && (
                  <div className="mt-3 grid gap-2 sm:grid-cols-4">
                    <StatTile label="best candidate" value={evolution.best.label} />
                    <StatTile label="process fidelity" value={evolution.best.process_fidelity.toFixed(6)} progress={evolution.best.process_fidelity} />
                    <StatTile label="gates / depth" value={`${evolution.best.gate_count} / ${evolution.best.depth}`} />
                    <StatTile
                      label="verified"
                      value={evolution.best.verified ? "yes" : "no"}
                      colour={evolution.best.verified ? "var(--c-ok)" : "var(--c-warn)"}
                    />
                  </div>
                )}
                {evolution.best?.circuit && (
                  <div className="mt-3 rounded-lg border border-[var(--c-line)] p-1.5">
                    <CircuitCanvas circuit={evolution.best.circuit} compact />
                  </div>
                )}
              </Panel>

              <Panel title="All candidates" subtitle="Ranked; the reference circuit is the target." dense>
                <div className="space-y-1">
                  {evolution.candidates.slice(0, 12).map((candidate) => (
                    <div key={candidate.label} className="flex items-center gap-2 rounded-md border border-[var(--c-line)] px-2 py-1.5">
                      <span className="mono-num w-40 shrink-0 truncate text-[11px]">{candidate.label}</span>
                      <Tag>{candidate.source}</Tag>
                      <span className="mono-num text-[10px] text-[var(--c-muted)]">
                        {candidate.gate_count}g · depth {candidate.depth} · 2q {candidate.two_qubit_gates}
                      </span>
                      <span className="mono-num ml-auto text-[11px]" style={{ color: candidate.fidelity > 0.999 ? "var(--c-ok)" : "var(--c-warn)" }}>
                        F = {candidate.fidelity.toFixed(6)}
                      </span>
                      <Tag colour={candidate.verified ? "var(--c-ok)" : "var(--c-muted)"}>{candidate.verified ? "verified" : "unverified"}</Tag>
                      <Button size="sm" variant="ghost" onClick={() => candidate.circuit && void setSource({ circuit: candidate.circuit })}>
                        load
                      </Button>
                    </div>
                  ))}
                </div>
                {evolution.search_log.length > 0 && (
                  <div className="mt-3">
                    <CodeBlock text={evolution.search_log.slice(-30).join("\n")} maxHeight={180} caption="search log" />
                  </div>
                )}
              </Panel>
            </>
          )}
        </div>
      )}

      {tab === "hardware" && (
        <div className="space-y-4">
          <Panel
            title="Hardware-aware mapping"
            subtitle="Compare the circuit against a device topology, and estimate what routing would cost. These are ESTIMATES from a device model — not measurements."
          >
            <div className="grid gap-3 sm:grid-cols-[1fr_1fr_auto] sm:items-end">
              <Field label="device">
                <Select
                  value={device}
                  options={(meta?.hardware ?? []).map((entry) => ({
                    value: entry.key,
                    label: `${entry.name} (${entry.num_qubits}q, ${entry.topology})`,
                  }))}
                  onChange={setDevice}
                />
              </Field>
              <div className="text-[10px] leading-relaxed text-[var(--c-faint)]">
                {(meta?.hardware ?? []).find((entry) => entry.key === device)?.notes ?? ""}
              </div>
              <Button variant="primary" disabled={loading.hardware} onClick={() => void analyseHardware(device, true)}>
                {loading.hardware ? "analysing…" : "map onto device"}
              </Button>
            </div>
            {errors.hardware && (
              <div className="mt-2">
                <Notice tone="danger" title="Device analysis failed">{errors.hardware}</Notice>
              </div>
            )}
          </Panel>

          {hardware && (
            <>
              <div className="grid gap-3 lg:grid-cols-3">
                <Panel title="Fit" subtitle={hardware.hardware.name} dense>
                  <div className="grid grid-cols-2 gap-2">
                    <StatTile label="circuit qubits" value={hardware.required_qubits} />
                    <StatTile label="device qubits" value={hardware.available_qubits} />
                    <StatTile label="fits" value={hardware.fits ? "yes" : "no"} colour={hardware.fits ? "var(--c-ok)" : "var(--c-danger)"} />
                    <StatTile label="connectivity" value={hardware.hardware.topology.connected ? "connected" : "no"} />
                  </div>
                  <div className="mt-2">
                    <SectionTitle>unsupported native gates</SectionTitle>
                    {hardware.unsupported_gates.length ? (
                      <div className="flex flex-wrap gap-1.5">
                        {hardware.unsupported_gates.map((gate) => (
                          <Tag key={gate.name} colour="var(--c-warn)">
                            {gate.name} ×{gate.count}
                          </Tag>
                        ))}
                      </div>
                    ) : (
                      <p className="text-[10px] text-[var(--c-faint)]">Every gate in the circuit has a native equivalent.</p>
                    )}
                  </div>
                </Panel>

                <Panel title="Estimated success" subtitle="From the device model's error rates." dense>
                  <div className="grid grid-cols-2 gap-2">
                    <StatTile
                      label="success probability"
                      value={hardware.estimate_before_routing.estimated_success_probability.toFixed(5)}
                      progress={hardware.estimate_before_routing.estimated_success_probability}
                    />
                    <StatTile label="error rate" value={hardware.estimate_before_routing.estimated_error_rate.toFixed(5)} colour="var(--c-warn)" />
                    <StatTile label="dominant contributor" value={hardware.estimate_before_routing.dominant_contributor} />
                    <StatTile label="circuit duration" value={`${hardware.estimate_before_routing.circuit_duration_us.toFixed(2)} µs`} />
                  </div>
                  <div className="mt-2 space-y-1">
                    {Object.entries(hardware.estimate_before_routing.contributors).map(([name, value]) => (
                      <div key={name} className="flex items-center justify-between text-[10px]">
                        <span className="text-[var(--c-muted)]">{name}</span>
                        <span className="mono-num">{Number(value).toExponential(3)}</span>
                      </div>
                    ))}
                  </div>
                </Panel>

                <Panel title="Routing" subtitle="What the topology forces the compiler to add." dense>
                  {hardware.routing ? (
                    <>
                      <div className="grid grid-cols-2 gap-2">
                        <StatTile label="violations before" value={hardware.routing.violations_before.length} />
                        <StatTile label="violations after" value={hardware.routing.violations_after.length} />
                        <StatTile label="SWAPs inserted" value={hardware.routing.swaps_inserted} />
                        <StatTile label="depth overhead" value={`${hardware.routing.depth_overhead_percent.toFixed(1)}%`} />
                        <StatTile label="gates" value={`${hardware.routing.gates_before} → ${hardware.routing.gates_after}`} />
                        <StatTile label="depth" value={`${hardware.routing.depth_before} → ${hardware.routing.depth_after}`} />
                      </div>
                      {hardware.estimate_after_routing && (
                        <p className="mt-2 text-[10px] text-[var(--c-muted)]">
                          after routing: success {hardware.estimate_after_routing.estimated_success_probability.toFixed(5)} ·
                          error {hardware.estimate_after_routing.estimated_error_rate.toFixed(5)}
                        </p>
                      )}
                      <div className="mt-2 flex flex-wrap gap-1.5">
                        {Object.entries(hardware.routing.logical_to_physical).map(([logical, physical]) => (
                          <Tag key={logical} colour="var(--c-secondary)">
                            q{logical} → p{physical}
                          </Tag>
                        ))}
                      </div>
                    </>
                  ) : (
                    <p className="text-[11px] text-[var(--c-faint)]">Routing was not requested for this analysis.</p>
                  )}
                </Panel>
              </div>

              {hardware.connectivity_violations.length > 0 && (
                <Panel title="Connectivity violations" subtitle="Two-qubit gates with no physical edge." dense>
                  <div className="space-y-1">
                    {hardware.connectivity_violations.map((violation, index) => (
                      <div key={index} className="flex items-center gap-2 text-[11px]">
                        <span className="mono-num w-8 shrink-0 text-[var(--c-faint)]">#{violation.index}</span>
                        <span className="mono-num w-20 shrink-0">{violation.gate}</span>
                        <span className="mono-num">{violation.wires.map((wire) => `q${wire}`).join(" ↔ ")}</span>
                        <Tag colour="var(--c-warn)">{violation.issue}</Tag>
                        {violation.distance !== undefined && (
                          <span className="mono-num text-[10px] text-[var(--c-faint)]">distance {violation.distance}</span>
                        )}
                      </div>
                    ))}
                  </div>
                </Panel>
              )}

              <Panel title="Assumptions and limits" subtitle="What this estimate does and does not include." dense>
                <ul className="space-y-1.5 text-[11px] leading-relaxed text-[var(--c-muted)]">
                  {hardware.limitations.map((limitation, index) => (
                    <li key={index}>• {limitation}</li>
                  ))}
                  {hardware.estimate_before_routing.assumptions.map((assumption, index) => (
                    <li key={`a-${index}`} className="text-[var(--c-faint)]">• {assumption}</li>
                  ))}
                </ul>
                <div className="mt-2 flex gap-2">
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() =>
                      void buildReport(
                        "hardware",
                        { source: { circuit }, device, route: true },
                        `${hardware.hardware.name} mapping report`,
                      )
                    }
                  >
                    hardware report
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => onNavigate("noise")}>
                    simulate that noise instead →
                  </Button>
                </div>
              </Panel>
            </>
          )}
        </div>
      )}
    </div>
  );
}
