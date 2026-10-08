/**
 * Analyze — the metrics engine, the entanglement observatory, the comparison
 * instrument and the what-if engine.
 *
 * All four answer different questions about the same objects, and each is explicit
 * about the limits of its method: a metric that does not apply says so, an
 * entanglement verdict names the test it used, and a comparison states its
 * sampling floor.
 */

import { useMemo, useState } from "react";
import { api } from "../lib/api";
import { AnimatedNumber, InView, MeterBar } from "../components/motion";
import type { ModeKey } from "../components/Shell";
import { Button, CodeBlock, Field, Notice, Panel, SectionTitle, Segmented, Select, StatTile, Tag, WarningList } from "../components/ui";
import { CompareBars, Heatmap, InspectBars, LineChart } from "../components/viz/charts";
import { BlochSphere } from "../components/viz/quantum";
import { formatPercent, formatSeconds, sortedProbabilities } from "../lib/format";
import { useStore } from "../state/store";

export function AnalyzeMode({ onNavigate }: { onNavigate: (mode: ModeKey) => void }) {
  const {
    meta,
    document: circuit,
    result,
    compareResult,
    whatIf,
    settings,
    loading,
    errors,
    compare,
    runWhatIf,
    loadAlgorithm,
    buildReport,
  } = useStore();
  const [otherCircuit, setOtherCircuit] = useState<string>("same-optimized");
  const [modification, setModification] = useState<Record<string, unknown>>({ kind: "set_noise", strength: 0.05 });
  const [tab, setTab] = useState<"metrics" | "entanglement" | "compare" | "whatif">("metrics");

  const entanglement = result?.metrics?.entanglement;
  const pairs = useMemo(() => entanglement?.pairs ?? [], [entanglement]);
  const perQubit = entanglement?.per_qubit_entropy ?? [];
  const bloch = useMemo(() => (result?.metrics?.bloch ?? []) as Array<{ qubit?: number; x: number; y: number; z: number }>, [result]);
  const deltas = whatIf?.deltas ?? {};

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <Segmented
          value={tab}
          options={[
            { value: "metrics", label: "metrics engine" },
            { value: "entanglement", label: "entanglement" },
            { value: "compare", label: "compare two circuits" },
            { value: "whatif", label: "what-if" },
          ]}
          onChange={setTab}
        />
        <span className="text-[11px] text-[var(--c-muted)]">
          {circuit ? `${circuit.name} · ${circuit.resources.gates} gates · depth ${circuit.resources.depth}` : "no circuit"}
        </span>
        {result ? (
          <Tag colour={result.mode === "NOISY SIMULATION" ? "var(--c-warn)" : "var(--c-ok)"}>analysing: {result.mode}</Tag>
        ) : (
          <Tag colour="var(--c-warn)">no executed run — metrics will fall back to the circuit only</Tag>
        )}
      </div>

      {tab === "metrics" && (
        <>
          {!result ? (
            <Notice tone="info">
              Execute the circuit first. Static circuit metrics (gate counts, depth, entangling ratio) are available
              either way, but state metrics — purity, entropy, coherence, Pauli expectations, entanglement — require a
              run.
            </Notice>
          ) : null}

          <div className="grid gap-4 lg:grid-cols-[1fr_340px]">
            <Panel title="State metrics" subtitle="Computed from the final state the engine reported.">
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                <StatTile label="purity" value={<AnimatedNumber value={result?.metrics?.purity ?? 0} digits={6} />} hint="Tr(ρ²) — 1 means pure" />
                <StatTile label="entropy" value={<AnimatedNumber value={result?.metrics?.entropy ?? 0} digits={6} />} unit="bits" hint="von Neumann" />
                <StatTile
                  label="linear entropy"
                  value={<AnimatedNumber value={result?.metrics?.linear_entropy ?? 0} digits={6} />}
                  hint="1 − Tr(ρ²)"
                />
                <StatTile
                  label="normalised entropy"
                  value={<AnimatedNumber value={result?.metrics?.normalized_entropy ?? 0} digits={4} />}
                  hint="entropy / log₂ d"
                />
                <StatTile label="support" value={result?.metrics?.support_size ?? "—"} hint="basis states with probability > 0" />
                <StatTile
                  label="participation ratio"
                  value={<AnimatedNumber value={result?.metrics?.participation_ratio ?? 0} digits={3} />}
                  hint="effective number of states"
                />
                <StatTile label="coherence ℓ₁" value={<AnimatedNumber value={result?.metrics?.coherence_l1 ?? 0} digits={4} />} hint="off-diagonal weight" />
                <StatTile
                  label="dominant outcome"
                  value={result?.metrics?.dominant_basis ? `|${result.metrics.dominant_basis}⟩` : "—"}
                  hint={result?.metrics?.dominant_probability !== undefined ? formatPercent(result.metrics.dominant_probability, 3) : ""}
                  progress={result?.metrics?.dominant_probability}
                />
              </div>

              {result?.metrics?.pauli_expectations && (
                <div className="mt-4">
                  <SectionTitle hint="⟨P⟩ ∈ [−1, 1]">Pauli expectation values</SectionTitle>
                  <Heatmap
                    data={Object.entries(result.metrics.pauli_expectations).map(([, value]) => [Number(value)])}
                    size={160}
                    caption="one column per Pauli string"
                  />
                </div>
              )}

              <div className="mt-4">
                <SectionTitle hint="exact Born distribution">probability profile</SectionTitle>
                <InspectBars
                  items={sortedProbabilities(result?.ideal_probabilities ?? {}, 12).map((entry) => ({
                    label: `|${entry.basis}⟩`,
                    value: entry.probability,
                  }))}
                  colour="var(--c-secondary)"
                />
              </div>
            </Panel>

            <div className="space-y-3">
              <Panel title="Circuit metrics" subtitle="Static properties, independent of any execution." dense>
                <div className="grid grid-cols-2 gap-2">
                  <StatTile label="gates" value={circuit?.resources.gates ?? "—"} />
                  <StatTile label="depth" value={circuit?.resources.depth ?? "—"} />
                  <StatTile label="2-qubit gates" value={circuit?.resources.two_qubit_gates ?? "—"} />
                  <StatTile label="measurements" value={circuit?.resources.measurements ?? "—"} />
                  <StatTile
                    label="gate density"
                    value={
                      circuit ? (circuit.resources.gates / Math.max(circuit.resources.depth, 1)).toFixed(2) : "—"
                    }
                    hint="gates per layer"
                  />
                  <StatTile
                    label="entangling ratio"
                    value={
                      circuit ? (circuit.resources.two_qubit_gates / Math.max(circuit.resources.gates, 1)).toFixed(3) : "—"
                    }
                    hint="fraction of gates that can create entanglement"
                  />
                </div>
                <div className="mt-3">
                  <SectionTitle hint="count per gate type">gate histogram</SectionTitle>
                  <InspectBars
                    items={Object.entries(circuit?.resources.histogram ?? {})
                      .sort(([, a], [, b]) => b - a)
                      .map(([gate, count]) => ({ label: gate, value: count }))}
                  />
                </div>
              </Panel>

              <Panel title="Bloch vectors" subtitle="Of the final state, one sphere per qubit." dense>
                {bloch.length ? (
                  <div className="flex flex-wrap gap-2">
                    {bloch.map((vector, index) => (
                      <BlochSphere key={index} x={vector.x} y={vector.y} z={vector.z} label={`q${vector.qubit ?? index}`} size={108} />
                    ))}
                  </div>
                ) : (
                  <p className="text-[11px] text-[var(--c-faint)]">No Bloch vectors reported for this run.</p>
                )}
              </Panel>
            </div>
          </div>

          <Panel
            title="What these numbers mean"
            subtitle="The metric glossary, straight from the engine."
            actions={
              <Button size="sm" variant="outline" onClick={() => void buildReport("simulation", { source: { circuit }, shots: settings.shots }, "Metrics report")}>
                write it up
              </Button>
            }
          >
            <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
              {[
                { key: "purity", text: "Tr(ρ²). One for a pure state; below one means the state is mixed — noise, or a subsystem." },
                { key: "entropy", text: "Von Neumann entropy in bits. Zero for a pure state, log₂d for the maximally mixed one." },
                { key: "participation_ratio", text: "(Σp)²/Σp² — the effective number of basis states carrying the state." },
                { key: "coherence_l1", text: "Sum of off-diagonal magnitudes: how much phase coherence survives in this basis." },
                { key: "fidelity_vs_ideal", text: "State fidelity between this run and the same circuit with no error model." },
                { key: "trace_distance", text: "Maximum distinguishing bias between the two states; zero means indistinguishable." },
              ].map((item) => (
                <div key={item.key} className="panel-flat px-3 py-2">
                  <div className="mono-num text-[11px] text-[var(--c-primary)]">{item.key}</div>
                  <p className="mt-1 text-[10px] leading-relaxed text-[var(--c-muted)]">{item.text}</p>
                </div>
              ))}
            </div>
          </Panel>
        </>
      )}

      {tab === "entanglement" && (
        <div className="grid gap-4 lg:grid-cols-[1fr_340px]">
          <Panel
            title="Entanglement observatory"
            subtitle={entanglement ? entanglement.summary : "Run the circuit to measure entanglement in the final state."}
          >
            {!entanglement ? (
              <Notice tone="info">
                Entanglement is measured from the reported state: concurrence for two-qubit pairs, negativity and
                bipartite entropy in general. Nothing is inferred from the gate list.
              </Notice>
            ) : (
              <>
                <div className="flex flex-wrap items-center gap-2">
                  <Tag
                    colour={entanglement.status.startsWith("ENTANGLED") ? "var(--c-accent)" : "var(--c-muted)"}
                  >
                    {entanglement.status}
                  </Tag>
                  <Tag>{entanglement.method}</Tag>
                  {entanglement.representation && <Tag>{entanglement.representation}</Tag>}
                </div>

                <div className="mt-3 grid gap-3 lg:grid-cols-2">
                  <div>
                    <SectionTitle hint="per qubit, in bits">entanglement entropy</SectionTitle>
                    <div className="space-y-1.5">
                      {perQubit.map((entry) => (
                        <div key={entry.qubit} className="flex items-center gap-2">
                          <span className="mono-num w-10 shrink-0 text-[11px]">q{entry.qubit}</span>
                          <MeterBar value={entry.entanglement_entropy} height={6} colour={entry.entangled_with_rest ? "var(--c-accent)" : "var(--c-line-strong)"} />
                          <span className="mono-num w-16 shrink-0 text-right text-[10px]">{entry.entanglement_entropy.toFixed(4)}</span>
                          <Tag colour={entry.entangled_with_rest ? "var(--c-accent)" : "var(--c-muted)"}>
                            {entry.entangled_with_rest ? "entangled" : "separable"}
                          </Tag>
                        </div>
                      ))}
                    </div>
                  </div>

                  <div>
                    <SectionTitle hint="concurrence and negativity">pairwise entanglement</SectionTitle>
                    {pairs.length ? (
                      <InspectBars
                        items={pairs.map((pair) => ({
                          label: `q${pair.a}·q${pair.b}`,
                          value: pair.concurrence,
                          secondary: pair.negativity * 2,
                        }))}
                        colour="var(--c-accent)"
                        overlay="var(--c-primary)"
                      />
                    ) : (
                      <p className="text-[11px] text-[var(--c-faint)]">
                        Pairwise concurrence was not computed for this state (it needs a two-qubit reduction per pair).
                      </p>
                    )}
                  </div>
                </div>

                {entanglement.pairwise_concurrence_matrix && (
                  <div className="mt-4">
                    <SectionTitle hint="symmetric, zero diagonal">concurrence matrix</SectionTitle>
                    <Heatmap data={entanglement.pairwise_concurrence_matrix} size={200} labels={perQubit.map((entry) => `q${entry.qubit}`)} />
                  </div>
                )}

                <div className="mt-4">
                  <Notice tone="info" title="What this method cannot see">
                    <ul className="mt-1 space-y-1">
                      {entanglement.limitations.map((limitation, index) => (
                        <li key={index}>• {limitation}</li>
                      ))}
                    </ul>
                  </Notice>
                </div>
              </>
            )}
          </Panel>

          <div className="space-y-3">
            <Panel title="Entanglement in time" subtitle="From the trace, if one exists." dense>
              <p className="text-[11px] text-[var(--c-muted)]">
                The trace view shows the entanglement status at every step and marks the step where it first appeared.
                That is the honest place to ask “where did this circuit become entangled?” — the final state alone
                cannot answer it.
              </p>
              <Button className="mt-2" size="sm" variant="outline" onClick={() => onNavigate("trace")}>
                open the trace
              </Button>
            </Panel>

            <Panel title="Max concurrence" subtitle="Largest pairwise entanglement anywhere in the state." dense>
              <div className="text-center">
                <div className="mono-num text-[28px] font-semibold text-[var(--c-accent)]">
                  {entanglement ? entanglement.max_concurrence.toFixed(6) : "—"}
                </div>
                <p className="mt-1 text-[10px] text-[var(--c-faint)]">
                  1 means a maximally entangled pair; 0 means no pair is entangled by this measure.
                </p>
              </div>
            </Panel>
          </div>
        </div>
      )}

      {tab === "compare" && (
        <div className="space-y-4">
          <Panel
            title="Compare two circuits"
            subtitle="Same shots, same seed, same error model — so a difference is a property of the circuits."
          >
            <div className="grid gap-3 sm:grid-cols-[1fr_1fr_auto] sm:items-end">
              <Field label="circuit A" hint={circuit ? circuit.name : "the loaded circuit"}>
                <div className="mono-num rounded-lg border border-[var(--c-line)] px-2.5 py-1.5 text-[11px] text-[var(--c-muted)]">
                  {circuit ? `${circuit.name} · ${circuit.resources.gates} gates` : "—"}
                </div>
              </Field>
              <Field label="circuit B">
                <Select
                  value={otherCircuit}
                  options={[
                    { value: "same-optimized", label: "this circuit, after optimisation" },
                    ...(meta?.algorithms ?? []).map((algorithm) => ({ value: algorithm.key, label: `algorithm: ${algorithm.name}` })),
                  ]}
                  onChange={setOtherCircuit}
                />
              </Field>
              <div className="flex gap-2">
                <Button
                  variant="primary"
                  disabled={loading.compare}
                  onClick={() => {
                    void (async () => {
                      if (otherCircuit === "same-optimized") {
                        const optimization = await api.optimize({ source: { circuit }, level: settings.optimizerLevel });
                        if (optimization.optimized) await compare({ circuit: optimization.optimized });
                      } else {
                        await compare({ algorithm: otherCircuit });
                        await loadAlgorithm(otherCircuit);
                      }
                    })();
                  }}
                >
                  {loading.compare ? "comparing…" : "compare"}
                </Button>
              </div>
            </div>
            {errors.compare && (
              <div className="mt-2">
                <Notice tone="danger" title="Comparison refused">{errors.compare}</Notice>
              </div>
            )}
          </Panel>

          {compareResult && (
            <>
              <div className="grid gap-3 lg:grid-cols-3">
                <Panel title="Verdict" subtitle="What the measurement supports." dense>
                  <ul className="space-y-1.5 text-[11px]">
                    {compareResult.verdict.map((line, index) => (
                      <li key={index} className="flex gap-2">
                        <span className="mt-[6px] h-1 w-1 shrink-0 rounded-full bg-[var(--c-primary)]" />
                        {line}
                      </li>
                    ))}
                  </ul>
                  <div className="mt-3">
                    <StatTile
                      label="output total variation"
                      value={<AnimatedNumber value={compareResult.output_total_variation} digits={5} />}
                      hint="distance between the exact distributions"
                      progress={compareResult.output_total_variation}
                    />
                  </div>
                </Panel>
                <Panel title="Resources" subtitle={`A: ${compareResult.circuit_a.name} · B: ${compareResult.circuit_b.name}`} dense>
                  <CompareBars rows={compareResult.resource_rows.map((row) => ({ ...row }))} />
                </Panel>
                <Panel title="State metrics" subtitle="Measured on both runs." dense>
                  <CompareBars
                    rows={compareResult.metric_rows.filter((row) => typeof row.a === "number" && typeof row.b === "number").map((row) => ({ ...row }))}
                  />
                </Panel>
              </div>

              <Panel title="Outcome distributions" subtitle="Both circuits sampled with the same seed and shot count." dense>
                <LineChart
                  x={Array.from(new Set([...Object.keys(compareResult.a.ideal_probabilities), ...Object.keys(compareResult.b.ideal_probabilities)]))
                    .sort()
                    .slice(0, 12)}
                  series={[
                    {
                      key: "a",
                      label: `A: ${compareResult.circuit_a.name}`,
                      y: Array.from(new Set([...Object.keys(compareResult.a.ideal_probabilities), ...Object.keys(compareResult.b.ideal_probabilities)]))
                        .sort()
                        .slice(0, 12)
                        .map((basis) => compareResult.a.ideal_probabilities[basis] ?? 0),
                      kind: "bar",
                      colour: "var(--c-secondary)",
                    },
                    {
                      key: "b",
                      label: `B: ${compareResult.circuit_b.name}`,
                      y: Array.from(new Set([...Object.keys(compareResult.a.ideal_probabilities), ...Object.keys(compareResult.b.ideal_probabilities)]))
                        .sort()
                        .slice(0, 12)
                        .map((basis) => compareResult.b.ideal_probabilities[basis] ?? 0),
                      kind: "scatter",
                      colour: "var(--c-primary)",
                    },
                  ]}
                  yLabel="probability"
                  xLabel="outcome"
                  height={200}
                />
                <Notice tone="info" title="Limits of this comparison">
                  <ul className="mt-1 space-y-1">
                    {compareResult.limitations.map((limitation, index) => (
                      <li key={index}>• {limitation}</li>
                    ))}
                  </ul>
                </Notice>
              </Panel>

              <Panel title="Side-by-side circuits" subtitle="A above, B below." dense>
                <div className="grid gap-2 lg:grid-cols-2">
                  <CodeBlock text={compareResult.diagram_a} maxHeight={200} caption={compareResult.circuit_a.name} />
                  <CodeBlock text={compareResult.diagram_b} maxHeight={200} caption={compareResult.circuit_b.name} />
                </div>
                <div className="mt-2 flex gap-2">
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() =>
                      void buildReport(
                        "comparison",
                        { a: { circuit: compareResult.a.circuit }, b: { circuit: compareResult.b.circuit }, shots: compareResult.shots, seed: compareResult.seed },
                        "Comparison report",
                      )
                    }
                  >
                    write comparison report
                  </Button>
                </div>
              </Panel>
            </>
          )}
        </div>
      )}

      {tab === "whatif" && (
        <div className="space-y-4">
          <Panel
            title="What-if engine"
            subtitle="Change one thing, measure the difference, and state the limits of the comparison."
          >
            <div className="grid gap-3 sm:grid-cols-[1fr_1fr_auto] sm:items-end">
              <Field label="modification">
                <Select
                  value={String(modification.kind)}
                  options={(meta?.whatif ?? []).map((entry) => ({ value: entry.kind, label: entry.label }))}
                  onChange={(value) => {
                    const shape = (meta?.whatif ?? []).find((entry) => entry.kind === value)?.shape ?? { kind: value };
                    setModification(shape);
                  }}
                />
              </Field>
              <Field label="shape" hint="Exactly what will be sent, from the engine's own catalogue.">
                <div className="mono-num truncate rounded-lg border border-[var(--c-line)] px-2.5 py-1.5 text-[11px] text-[var(--c-muted)]">
                  {JSON.stringify(modification)}
                </div>
              </Field>
              <div className="flex gap-2">
                <Button variant="primary" disabled={loading.whatif} onClick={() => void runWhatIf(modification)}>
                  {loading.whatif ? "measuring…" : "measure the difference"}
                </Button>
              </div>
            </div>
            {errors.whatif && (
              <div className="mt-2">
                <Notice tone="danger" title="That modification was refused">{errors.whatif}</Notice>
              </div>
            )}
          </Panel>

          {whatIf && (
            <>
              <Panel title={whatIf.headline || "Difference"} subtitle={whatIf.limitation}>
                <div className="grid gap-2 sm:grid-cols-3">
                  {Object.entries(deltas).map(([key, value]) => (
                    <StatTile
                      key={key}
                      label={key.replace(/_/g, " ")}
                      value={
                        typeof value.delta === "number" ? (
                          <span style={{ color: value.delta === 0 ? undefined : value.delta > 0 ? "var(--c-primary)" : "var(--c-accent)" }}>
                            {value.delta > 0 ? "+" : ""}
                            {value.delta.toPrecision(4)}
                          </span>
                        ) : (
                          "—"
                        )
                      }
                      hint={`${value.baseline ?? "—"} → ${value.variant ?? "—"}`}
                    />
                  ))}
                </div>
                {whatIf.observations.length > 0 && (
                  <div className="mt-3 space-y-1.5">
                    {whatIf.observations.map((observation, index) => (
                      <p key={index} className="text-[11px] text-[var(--c-muted)]">
                        • {observation}
                      </p>
                    ))}
                  </div>
                )}
                <WarningList warnings={whatIf.warnings} notes={[]} />
                <p className="mt-3 text-[10px] text-[var(--c-faint)]">
                  measured in {formatSeconds(whatIf.seconds)} · both sides ran the same engine with the same seed
                </p>
              </Panel>

              <div className="grid gap-3 lg:grid-cols-2">
                <Panel title="Baseline" subtitle="The circuit as it is." dense>
                  <div className="grid grid-cols-3 gap-2">
                    <StatTile label="gates" value={(whatIf.baseline.circuit as { gates?: number } | undefined)?.gates ?? "—"} />
                    <StatTile label="depth" value={(whatIf.baseline.circuit as { depth?: number } | undefined)?.depth ?? "—"} />
                    <StatTile label="shots" value={(whatIf.baseline as { shots?: number }).shots ?? "—"} />
                  </div>
                  <CodeBlock text={JSON.stringify(whatIf.baseline, null, 2).slice(0, 1200)} maxHeight={200} />
                </Panel>
                <Panel title="Variant" subtitle="After the modification." dense>
                  <div className="grid grid-cols-3 gap-2">
                    <StatTile label="gates" value={(whatIf.variant.circuit as { gates?: number } | undefined)?.gates ?? "—"} />
                    <StatTile label="depth" value={(whatIf.variant.circuit as { depth?: number } | undefined)?.depth ?? "—"} />
                    <StatTile label="shots" value={(whatIf.variant as { shots?: number }).shots ?? "—"} />
                  </div>
                  <CodeBlock text={JSON.stringify(whatIf.variant, null, 2).slice(0, 1200)} maxHeight={200} />
                </Panel>
              </div>
            </>
          )}
        </div>
      )}

      <InView>
        <Panel title="Report from this analysis" subtitle="Every report states its method, its limitations and how to reproduce it." dense>
          <div className="flex flex-wrap gap-2">
            <Button size="sm" variant="outline" onClick={() => void buildReport("simulation", { source: { circuit }, shots: settings.shots })}>
              simulation report
            </Button>
            <Button size="sm" variant="outline" onClick={() => void buildReport("trace", { source: { circuit }, depth: settings.traceDepth, term_limit: settings.termLimit })}>
              trace report
            </Button>
            <Button size="sm" variant="outline" onClick={() => void buildReport("optimization", { source: { circuit }, level: settings.optimizerLevel })}>
              optimisation report
            </Button>
            <Button size="sm" variant="ghost" onClick={() => onNavigate("research")}>
              open the report generator →
            </Button>
          </div>
        </Panel>
      </InView>
    </div>
  );
}
