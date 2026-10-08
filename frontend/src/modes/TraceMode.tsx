/**
 * Trace — the quantum time machine.
 *
 * This is the microscope. Every operation becomes a step you can stand on: the
 * state before it, the state after it, what changed, how long it took, where the
 * Bloch vectors moved and whether entanglement appeared. It can either be computed
 * in one call or streamed gate by gate from the engine, which is what makes it
 * feel like a debugger rather than a plot.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import { AnimatedNumber, MeterBar } from "../components/motion";
import type { ModeKey } from "../components/Shell";
import { Button, CodeBlock, Field, Notice, Panel, SectionTitle, Segmented, Slider, StatTile, Tag, WarningList } from "../components/ui";
import { Sparkline } from "../components/viz/charts";
import { AmplitudeBars, BlochSphere, CircuitCanvas, StateDiff } from "../components/viz/quantum";
import { formatSeconds } from "../lib/format";
import { useStore } from "../state/store";
import { FieldGuide } from "../components/Guide";

export function TraceMode({ onNavigate }: { onNavigate: (mode: ModeKey) => void }) {
  const { trace, liveStep, settings, setSettings, loading, errors, traceCircuit, streamTrace } = useStore();
  const [index, setIndex] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [delay, setDelay] = useState(240);
  const [diffBasis, setDiffBasis] = useState<string | null>(null);
  const streamRef = useRef<{ close: () => void } | null>(null);

  const current = useMemo(() => {
    if (liveStep && playing) return liveStep.step;
    if (trace) return trace.steps[Math.min(index, trace.steps.length - 1)] ?? null;
    return liveStep?.step ?? null;
  }, [index, liveStep, playing, trace]);

  // pause/play playback: advance through an already-computed trace
  useEffect(() => {
    if (!playing || !trace) return;
    if (index >= trace.steps.length - 1) {
      setPlaying(false);
      return;
    }
    const timer = window.setTimeout(() => setIndex((value) => Math.min(value + 1, trace.steps.length - 1)), Math.max(60, 900 - delay));
    return () => window.clearTimeout(timer);
  }, [playing, index, delay, trace]);

  useEffect(() => () => streamRef.current?.close(), []);

  const probabilities = useMemo(() => {
    if (!current) return [];
    return Object.entries(current.probabilities ?? {}).map(([basis, probability]) => ({ basis, probability }));
  }, [current]);

  const stepDeltas = useMemo(
    () =>
      (trace?.steps ?? []).map((step) => {
        const change = Number((step.diff as { total_variation?: number } | undefined)?.total_variation ?? NaN);
        if (Number.isFinite(change)) return change;
        const before = step.state_before?.probability_max ?? 0;
        return Math.abs((step.state?.probability_max ?? 0) - before);
      }),
    [trace],
  );

  return (
    <div className="space-y-4">
      <FieldGuide
        modeName="Trace"
        slides={[
          {
            heading: "What you are looking at",
            steps: [
              {
                title: "Left column is the debugger, right column is the stage",
                body: "The Debugger panel on the left is where you choose how much the engine measures at every step — analysis depth, how many amplitudes to report, the pace of a live stream. The Circuit panel on the right is the stage: the highlighted gate is the step you are standing on, and the diagram keeps its place as you step through.",
                pointer: "Debugger panel → analysis depth, amplitudes per step, compute full trace, stream live, stream pace; Circuit panel → highlighted gate",
              },
              {
                title: "The step panel is the gate you are standing on",
                body: "Each step opens a panel with the gate name, its layer and targets, the step and cumulative time, the norm and purity of the state, the measurement if there was one, the state amplitudes, and one Bloch sphere per qubit. Below that is the Quantum Diff, which tells you what that single gate changed.",
                pointer: "step panel → step time, cumulative, norm, purity, state amplitudes, Bloch vectors; Quantum Diff → probability moved, entanglement before → after",
              },
              {
                title: "The bottom tools are play, history and the boundaries",
                body: "The All steps list is the gate history — click any row to jump, and the bar beside it shows how much that step moved the state. The Probability distribution panel shows the state at the current step. The Not in the trace panel is honest about what a gate-by-gate trace cannot answer, and the Take it further panel points to the rest of the platform.",
                pointer: "All steps list → jump by clicking; Probability distribution → current step; Not in the trace → boundaries; Take it further → where to go next",
              },
            ],
          },
          {
            heading: "How to use this page",
            steps: [
              {
                title: "Choose your depth before you trace",
                body: "The analysis depth control is the one decision that changes cost. Fast gives you snapshots, diffs and cheap metrics only. Standard adds per-qubit entanglement entropy. Full adds pairwise concurrence, which costs more as the pair count grows. Set amplitudes per step separately — that is how many basis states the step panel shows.",
                pointer: "analysis depth → fast / standard / full; amplitudes reported per step → number input",
                highlight: 3,
                tip: "depth choices",
              },
              {
                title: "Compute the full trace to jump, stream live to watch",
                body: "Compute full trace builds the whole step list in one call, which is what lets you jump around and scrub. Stream live runs the engine gate by gate as it produces them, which is what makes it feel like a debugger. Both come from the same iter_trace path, so the numbers agree when a full trace is available.",
                pointer: "compute full trace → primary button; stream live → outline button; stop → ghost button while streaming",
              },
              {
                title: "Step through with the playback controls",
                body: "Use first, step, play, step, last to move through an already-computed trace. The slider below them scrubs directly. Measurements inside a trace collapse the state with a fixed seed, so a trace is reproducible — including the random outcomes — but a single trace is one possible branch.",
                pointer: "playback → first / step / play / step / last and the slider",
              },
            ],
          },
        ]}
      />
      <div className="grid gap-4 xl:grid-cols-[300px_1fr]">
        {/* --------------------------------------------------------- controls */}
        <div className="space-y-3">
          <Panel title="Debugger" subtitle="Choose how much the engine measures at every step." dense>
            <div className="space-y-3">
              <Field
                label="analysis depth"
                hint={
                  settings.traceDepth === "fast"
                    ? "snapshots, diffs and cheap metrics only — fastest"
                    : settings.traceDepth === "standard"
                      ? "adds per-qubit entanglement entropy"
                      : "adds pairwise concurrence (cost grows with the pair count)"
                }
              >
                <Segmented
                  value={settings.traceDepth}
                  options={[
                    { value: "fast", label: "fast" },
                    { value: "standard", label: "standard" },
                    { value: "full", label: "full" },
                  ]}
                  onChange={(value) => setSettings({ traceDepth: value })}
                  size="sm"
                />
              </Field>
              <Field label="amplitudes reported per step">
                <input
                  type="number"
                  min={1}
                  max={256}
                  className="mono-num w-full rounded-lg border border-[var(--c-line)] bg-[color-mix(in_oklab,var(--c-bg)_70%,transparent)] px-2 py-1.5 text-[12px]"
                  value={settings.termLimit}
                  onChange={(event) => setSettings({ termLimit: Math.max(1, Math.min(256, Number(event.target.value) || 1)) })}
                />
              </Field>
              <div className="flex flex-wrap gap-2">
                <Button variant="primary" disabled={loading.trace} onClick={() => void traceCircuit(null)}>
                  {loading.trace ? "tracing…" : "compute full trace"}
                </Button>
                <Button
                  variant="outline"
                  disabled={loading.stream}
                  onClick={() => {
                    streamRef.current?.close();
                    streamRef.current = streamTrace({ delayMs: delay, maxSteps: null });
                    setPlaying(true);
                  }}
                >
                  {loading.stream ? "streaming…" : "stream live"}
                </Button>
                {loading.stream && (
                  <Button
                    variant="ghost"
                    onClick={() => {
                      streamRef.current?.close();
                      streamRef.current = null;
                      setPlaying(false);
                    }}
                  >
                    stop
                  </Button>
                )}
              </div>
              {errors.trace && <Notice tone="danger" title="Trace failed">{errors.trace}</Notice>}
              {errors.stream && <Notice tone="danger" title="Stream failed">{errors.stream}</Notice>}
              <Field label={`stream pace — ${delay} ms per gate`}>
                <Slider value={delay} min={0} max={900} step={20} onChange={setDelay} format={(value) => `${value.toFixed(0)}`} />
              </Field>
            </div>
          </Panel>

          {trace && (
            <Panel title="Trace summary" subtitle="What the engine found across the whole circuit." dense>
              <div className="grid grid-cols-2 gap-2">
                <StatTile label="steps" value={trace.summary.steps} />
                <StatTile label="layers" value={trace.summary.layers} />
                <StatTile label="total" value={formatSeconds(trace.summary.total_seconds)} />
                <StatTile
                  label="entanglement"
                  value={String(trace.summary.final_entanglement_status ?? "—").slice(0, 12)}
                  colour={String(trace.summary.final_entanglement_status ?? "").startsWith("ENTANGLED") ? "var(--c-accent)" : undefined}
                />
              </div>
              <div className="mt-2 space-y-1.5 text-[11px]">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-[var(--c-muted)]">slowest operation</span>
                  <span className="mono-num truncate text-right">{trace.summary.slowest_operation ?? "—"}</span>
                </div>
                <div className="flex items-center justify-between gap-2">
                  <span className="text-[var(--c-muted)]">largest state change</span>
                  <span className="mono-num truncate text-right">{trace.summary.largest_state_change ?? "—"}</span>
                </div>
                <div className="flex items-center justify-between gap-2">
                  <span className="text-[var(--c-muted)]">entanglement created at</span>
                  <span className="mono-num truncate text-right">
                    {trace.summary.entanglement_created_at === null
                      ? "never"
                      : `step ${trace.summary.entanglement_created_at}`}
                  </span>
                </div>
              </div>
              <div className="mt-3">
                <SectionTitle hint="per step">state change</SectionTitle>
                <Sparkline values={stepDeltas.length ? stepDeltas : [0, 0]} colour="var(--c-accent)" />
                <p className="mt-1 text-[10px] text-[var(--c-faint)]">
                  Where the spikes are is where the computation actually happens.
                </p>
              </div>
              <WarningList warnings={trace.warnings} notes={trace.notes} />
            </Panel>
          )}

          <Panel title="Playback" subtitle="Step through, jump, or replay." dense>
            <div className="space-y-2">
              <div className="flex flex-wrap gap-1.5">
                <Button size="sm" variant="outline" disabled={!trace} onClick={() => setIndex(0)}>
                  ⏮ first
                </Button>
                <Button size="sm" variant="outline" disabled={!trace || index === 0} onClick={() => setIndex((value) => Math.max(0, value - 1))}>
                  ◀ step
                </Button>
                <Button size="sm" variant="primary" disabled={!trace} onClick={() => setPlaying((value) => !value)}>
                  {playing ? "⏸ pause" : "▶ play"}
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  disabled={!trace || index >= (trace?.steps.length ?? 1) - 1}
                  onClick={() => setIndex((value) => Math.min((trace?.steps.length ?? 1) - 1, value + 1))}
                >
                  step ▶
                </Button>
                <Button size="sm" variant="outline" disabled={!trace} onClick={() => setIndex((trace?.steps.length ?? 1) - 1)}>
                  last ⏭
                </Button>
              </div>
              <input
                type="range"
                min={0}
                max={Math.max(0, (trace?.steps.length ?? 1) - 1)}
                value={Math.min(index, Math.max(0, (trace?.steps.length ?? 1) - 1))}
                onChange={(event) => {
                  setPlaying(false);
                  setIndex(Number(event.target.value));
                }}
                className="w-full accent-[var(--c-primary)]"
                disabled={!trace}
              />
              <p className="text-[10px] text-[var(--c-faint)]">
                Measurements inside a trace collapse the state with a fixed seed, so a trace is reproducible — including
                the random outcomes.
              </p>
            </div>
          </Panel>
        </div>

        {/* ------------------------------------------------------------ stage */}
        <div className="space-y-3">
          <Panel
            title="Circuit"
            subtitle="The highlighted gate is the step you are standing on."
            actions={
              <Button size="sm" variant="ghost" onClick={() => onNavigate("execute")}>
                run instead
              </Button>
            }
          >
            <CircuitCanvas
              circuit={trace?.circuit ?? null}
              activeIndex={current?.index ?? null}
              onSelect={(stepIndex) => {
                if (trace) {
                  setPlaying(false);
                  setIndex(stepIndex);
                }
              }}
            />
          </Panel>

          {!current ? (
            <Panel title="Step" subtitle="No trace yet.">
              <Notice tone="info">
                Compute a full trace to jump around freely, or stream live to watch the state evolve gate by gate as
                the engine produces it. Both come from the same <span className="mono-num">iter_trace</span> path, so
                the numbers agree.
              </Notice>
            </Panel>
          ) : (
            <>
              <Panel
                title={`Step ${current.index} — ${current.name}${current.params.length ? `(${current.params.map((value) => value.toFixed(3)).join(", ")})` : ""}`}
                subtitle={`layer ${current.layer} · ${current.targets.length ? current.targets.map((wire) => `q${wire}`).join(", ") : "no targets"}${current.controls.length ? ` · controls ${current.controls.map((wire) => `q${wire}`).join(", ")}` : ""}`}
                actions={
                  <>
                    <Tag colour={String(current.state.entanglement_status).startsWith("ENTANGLED") ? "var(--c-accent)" : "var(--c-muted)"}>
                      {current.state.entanglement_status}
                    </Tag>
                    {current.measurement && <Tag colour="var(--c-warn)">measured</Tag>}
                  </>
                }
              >
                <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                  <StatTile label="step time" value={<AnimatedNumber value={current.seconds} digits={6} />} unit="s" />
                  <StatTile label="cumulative" value={<AnimatedNumber value={current.cumulative_seconds} digits={6} />} unit="s" />
                  <StatTile label="norm" value={current.state.norm.toFixed(10)} hint="must stay 1 — non-unitary steps excepted" />
                  <StatTile
                    label="purity"
                    value={<AnimatedNumber value={current.state.purity} digits={6} />}
                    hint={current.state.purity < 0.9999 ? "mixed state: noise or measurement" : "pure state"}
                  />
                </div>

                {current.measurement && (
                  <div className="mt-3">
                    <Notice tone="warn" title="This step measured a qubit">
                      {JSON.stringify(current.measurement)}
                    </Notice>
                  </div>
                )}

                <div className="mt-3 grid gap-3 lg:grid-cols-[1fr_260px]">
                  <div>
                    <SectionTitle hint="sorted by probability">state amplitudes</SectionTitle>
                    <AmplitudeBars
                      amplitudes={current.state.amplitudes}
                      selected={diffBasis}
                      onSelect={setDiffBasis}
                      limit={12}
                    />
                  </div>
                  <div>
                    <SectionTitle hint="one per qubit">Bloch vectors</SectionTitle>
                    <div className="flex flex-wrap gap-2">
                      {(current.state.bloch ?? []).map((vector) => (
                        <BlochSphere key={vector.qubit} x={vector.x} y={vector.y} z={vector.z} label={`q${vector.qubit}`} size={112} />
                      ))}
                    </div>
                    <p className="mt-1 text-[10px] text-[var(--c-faint)]">
                      A short vector means the qubit is entangled or mixed — it is not a rendering artefact.
                    </p>
                  </div>
                </div>
              </Panel>

              <div className="grid gap-3 lg:grid-cols-2">
                <Panel
                  title="Quantum Diff"
                  subtitle={`What step ${current.index} changed: ${current.display}`}
                  dense
                >
                  <StateDiff step={current} limit={10} />
                  <div className="mt-3 grid grid-cols-2 gap-2">
                    <StatTile
                      label="probability moved"
                      value={Object.values(current.probabilities ?? {}).length ? (
                        <AnimatedNumber
                          value={Number((current.diff as { total_variation?: number })?.total_variation ?? 0)}
                          digits={5}
                        />
                      ) : (
                        "—"
                      )}
                      hint="total variation between before and after"
                    />
                    <StatTile
                      label="entanglement"
                      value={`${String(current.state_before.entanglement_status).slice(0, 9)} → ${String(current.state.entanglement_status).slice(0, 9)}`}
                    />
                  </div>
                  <div className="mt-3">
                    <CodeBlock text={JSON.stringify(current.diff, null, 2).slice(0, 1800)} maxHeight={200} caption="raw diff record" />
                  </div>
                </Panel>

                <div className="space-y-3">
                  <Panel title="All steps" subtitle="Click to jump; bars show how much each step moved the state." dense>
                    <div className="max-h-[320px] space-y-1 overflow-y-auto pr-1">
                      {(trace?.steps ?? [current]).map((step, stepIndex) => {
                        const isCurrent = step.index === current.index;
                        const delta = stepDeltas[stepIndex] ?? 0;
                        const maxDelta = Math.max(...stepDeltas, 1e-9);
                        return (
                          <button
                            key={step.index}
                            type="button"
                            onClick={() => {
                              setPlaying(false);
                              setIndex(stepIndex);
                            }}
                            className={`flex w-full items-center gap-2 rounded-md border px-2 py-1 text-left text-[11px] transition-colors ${
                              isCurrent ? "border-[var(--c-primary)] bg-[color-mix(in_oklab,var(--c-primary)_10%,transparent)]" : "border-transparent hover:border-[var(--c-line)]"
                            }`}
                          >
                            <span className="mono-num w-6 shrink-0 text-[var(--c-faint)]">{step.index}</span>
                            <span className="mono-num w-24 shrink-0 truncate">{step.display || step.name}</span>
                            <span className="flex-1">
                              <MeterBar value={delta / maxDelta} height={3} colour={step.kind === "measure" ? "var(--c-warn)" : "var(--c-primary)"} />
                            </span>
                            <span className="mono-num w-16 shrink-0 text-right text-[10px] text-[var(--c-faint)]">
                              {formatSeconds(step.seconds)}
                            </span>
                            {String(step.state.entanglement_status).startsWith("ENTANGLED") && (
                              <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-[var(--c-accent)]" title="entangled at this step" />
                            )}
                          </button>
                        );
                      })}
                      {!trace && <p className="text-[10px] text-[var(--c-faint)]">Streaming — the full step list appears when the trace is computed in one call.</p>}
                    </div>
                  </Panel>

                  <Panel title="Probability distribution" subtitle="Of the state as it stands at this step." dense>
                    <div className="space-y-1">
                      {probabilities
                        .sort((a, b) => b.probability - a.probability)
                        .slice(0, 10)
                        .map((entry) => (
                          <div key={entry.basis} className="flex items-center gap-2">
                            <span className="mono-num w-14 shrink-0 text-[11px]">|{entry.basis}⟩</span>
                            <MeterBar value={entry.probability} height={6} />
                            <span className="mono-num w-20 shrink-0 text-right text-[10px]">{entry.probability.toFixed(5)}</span>
                          </div>
                        ))}
                    </div>
                    <p className="mt-2 text-[10px] text-[var(--c-faint)]">
                      probabilities sum to {Object.values(current.probabilities ?? {}).reduce((total, value) => total + value, 0).toFixed(10)}
                    </p>
                  </Panel>
                </div>
              </div>

              <div className="grid gap-3 lg:grid-cols-2">
                <Panel title="Not in the trace" subtitle="Honest boundaries of a gate-by-gate trace." dense>
                  <ul className="space-y-1.5 text-[11px] leading-relaxed text-[var(--c-muted)]">
                    <li>
                      Tracing samples a measurement outcome with a fixed seed. The trace is reproducible, but a single
                      trace is one possible branch — repeat it with a different seed to see the others.
                    </li>
                    <li>
                      Entanglement detection uses concurrence for pairs and bipartite entropy in general; it reports
                      “inconclusive” rather than “none” when a method cannot decide.
                    </li>
                    <li>
                      As the register grows the state grows as 2ⁿ: at 20 qubits that is 1,048,576 amplitudes per step, so
                      intermediate analysis falls back to the cheap metrics unless you ask for depth “full”.
                    </li>
                  </ul>
                </Panel>
                <Panel title="Take it further" subtitle="The trace feeds the rest of the platform." dense>
                  <div className="flex flex-wrap gap-2">
                    <Button size="sm" variant="outline" onClick={() => onNavigate("analyze")}>
                      analyse the final state
                    </Button>
                    <Button size="sm" variant="outline" onClick={() => onNavigate("optimize")}>
                      optimise the same circuit
                    </Button>
                    <Button size="sm" variant="outline" onClick={() => onNavigate("noise")}>
                      add noise and re-trace
                    </Button>
                    <Button size="sm" variant="outline" onClick={() => onNavigate("research")}>
                      ask about this trace
                    </Button>
                  </div>
                </Panel>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
