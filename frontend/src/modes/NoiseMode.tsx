/**
 * Noise — the observatory.
 *
 * Noise is not a slider that makes numbers worse: it is an explicit set of channels
 * with parameters, applied at a defined scope, and every result built on it is
 * labelled NOISY SIMULATION.  This view lets you build a model, sweep it, and see
 * exactly which channel is responsible for the degradation.
 */

import { useEffect, useMemo, useState } from "react";
import { AnimatedNumber, InView } from "../components/motion";
import type { ModeKey } from "../components/Shell";
import { Button, Field, Notice, Panel, SectionTitle, Segmented, Select, Slider, StatTile, Tag, WarningList } from "../components/ui";
import { CompareBars, InspectBars, LineChart } from "../components/viz/charts";
import { fidelityWords, formatPercent, sortedProbabilities } from "../lib/format";
import { api, type NoiseSpec } from "../lib/api";
import { useStore } from "../state/store";

interface SweepPoint {
  strength: number;
  fidelity: number | null;
  purity: number | null;
  entropy: number | null;
  dominant: number | null;
  status: string;
}

export function NoiseMode({ onNavigate }: { onNavigate: (mode: ModeKey) => void }) {
  const { meta, document: circuit, result, settings, setSettings, loading, errors, simulate, buildReport } = useStore();
  const [channels, setChannels] = useState<Array<{ kind: string; params: Record<string, number>; scope: string }>>([
    { kind: "depolarizing", params: { p: 0.02 }, scope: "gate" },
  ]);
  const [channelKind, setChannelKind] = useState("depolarizing");
  const [sweep, setSweep] = useState<SweepPoint[]>([]);
  const [sweeping, setSweeping] = useState(false);
  const [sweepError, setSweepError] = useState("");

  const noiseSpec = useMemo<NoiseSpec>(
    () => ({
      name: "custom",
      channels: channels.map((channel) => ({ ...channel })),
      readout_error: settings.noise.readout_error ?? 0,
      description: channels.map((channel) => `${channel.kind}(${JSON.stringify(channel.params)})`).join(" + "),
    }),
    [channels, settings.noise.readout_error],
  );

  // keep the store's noise model in step with what this view shows
  useEffect(() => {
    setSettings({ noise: noiseSpec, noiseStrength: 0 });
  }, [noiseSpec, setSettings]);

  const runSweep = async () => {
    if (!circuit) return;
    setSweeping(true);
    setSweepError("");
    const points: SweepPoint[] = [];
    try {
      for (const strength of [0, 0.01, 0.02, 0.05, 0.1, 0.2, 0.4]) {
        const response = await api.simulate({
          source: { circuit },
          shots: Math.min(settings.shots, 4096),
          seed: settings.seed,
          noise: {
            name: "custom",
            channels: channels.map((channel) => ({
              ...channel,
              params: Object.fromEntries(Object.entries(channel.params).map(([key, value]) => [key, value * (strength / 0.02 || (strength === 0 ? 0 : 1))])),
            })),
            readout_error: (settings.noise.readout_error ?? 0) * (strength / 0.02 || (strength === 0 ? 0 : 1)),
          },
          compare_ideal: true,
        });
        points.push({
          strength,
          fidelity: response.result.fidelity_vs_ideal,
          purity: response.result.metrics.purity ?? null,
          entropy: response.result.metrics.entropy ?? null,
          dominant: response.result.metrics.dominant_probability ?? null,
          status: response.result.mode,
        });
        setSweep([...points]);
      }
    } catch (error) {
      setSweepError((error as Error).message);
    } finally {
      setSweeping(false);
    }
  };

  const distribution = useMemo(
    () => sortedProbabilities(result?.ideal_probabilities ?? {}, 10),
    [result],
  );

  return (
    <div className="space-y-4">
      <div className="grid gap-4 xl:grid-cols-[340px_1fr]">
        {/* -------------------------------------------------------- models */}
        <div className="space-y-3">
          <Panel title="Error model" subtitle="Explicit channels, each with its own scope on the device." dense>
            <div className="space-y-3">
              <div className="space-y-2">
                {channels.map((channel, index) => {
                  const definition = (meta?.noise_models ?? []).find((entry) => entry.kind === channel.kind);
                  return (
                    <div key={index} className="panel-flat space-y-2 p-2">
                      <div className="flex items-center gap-2">
                        <Tag colour="var(--c-warn)">{channel.kind}</Tag>
                        <Select
                          value={channel.scope}
                          options={[
                            { value: "gate", label: "after each matching gate" },
                            { value: "idle", label: "while the qubit waits" },
                            { value: "global", label: "once at the end" },
                          ]}
                          onChange={(value) =>
                            setChannels((current) => current.map((entry, position) => (position === index ? { ...entry, scope: value } : entry)))
                          }
                        />
                        <Button size="sm" variant="danger" onClick={() => setChannels((current) => current.filter((_, position) => position !== index))}>
                          remove
                        </Button>
                      </div>
                      {(definition?.params ?? Object.keys(channel.params)).map((name) => (
                        <div key={name}>
                          <div className="flex items-center justify-between text-[10px]">
                            <span className="text-[var(--c-muted)]">{name}</span>
                            <span className="mono-num">{(channel.params[name] ?? 0).toFixed(4)}</span>
                          </div>
                          <Slider
                            value={channel.params[name] ?? 0}
                            min={0}
                            max={1}
                            step={0.001}
                            onChange={(value) =>
                              setChannels((current) =>
                                current.map((entry, position) =>
                                  position === index ? { ...entry, params: { ...entry.params, [name]: value } } : entry,
                                ),
                              )
                            }
                            format={(value) => value.toFixed(3)}
                          />
                        </div>
                      ))}
                      <p className="text-[10px] leading-snug text-[var(--c-faint)]">{definition?.description ?? ""}</p>
                    </div>
                  );
                })}
              </div>

              <div className="flex items-end gap-2">
                <Field label="add channel">
                  <Select
                    value={channelKind}
                    options={(meta?.noise_models ?? []).map((entry) => ({ value: entry.kind, label: entry.kind }))}
                    onChange={setChannelKind}
                  />
                </Field>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => {
                    const definition = (meta?.noise_models ?? []).find((entry) => entry.kind === channelKind);
                    setChannels((current) => [
                      ...current,
                      { kind: channelKind, params: { ...(definition?.defaults ?? { p: 0.01 }) }, scope: "gate" },
                    ]);
                  }}
                >
                  add
                </Button>
              </div>

              <Field label="readout error" hint="Symmetric flip probability applied to every measured qubit.">
                <Slider
                  value={settings.noise.readout_error ?? 0}
                  min={0}
                  max={0.3}
                  step={0.005}
                  onChange={(value) => setSettings({ noise: { ...noiseSpec, readout_error: value } })}
                  format={(value) => value.toFixed(3)}
                />
              </Field>

              <div className="flex flex-wrap gap-2">
                <Button variant="primary" disabled={loading.simulate || channels.length === 0} onClick={() => void simulate()}>
                  {loading.simulate ? "running…" : "run with this model"}
                </Button>
                <Button variant="outline" disabled={sweeping || !circuit} onClick={() => void runSweep()}>
                  {sweeping ? "sweeping…" : "sweep strength"}
                </Button>
              </div>
              {errors.simulate && <Notice tone="danger" title="Run refused">{errors.simulate}</Notice>}
              {sweepError && <Notice tone="danger" title="Sweep failed">{sweepError}</Notice>}
              <p className="text-[10px] leading-relaxed text-[var(--c-faint)]">
                A custom channel set forces the density-matrix or trajectory engine — a state vector cannot represent a
                mixed state, and the engine will not pretend otherwise.
              </p>
            </div>
          </Panel>

          <Panel title="Presets" subtitle="The engine's own constructors, with sensible parameters." dense>
            <div className="flex flex-wrap gap-1.5">
              {["bit_flip", "phase_flip", "depolarizing", "amplitude_damping", "phase_damping", "thermal", "readout", "uniform_gate"].map((preset) => (
                <Button
                  key={preset}
                  size="sm"
                  variant="outline"
                  onClick={() =>
                    setChannels((current) => {
                      const defaults: Record<string, { kind: string; params: Record<string, number> }> = {
                        bit_flip: { kind: "bit_flip", params: { p: 0.02 } },
                        phase_flip: { kind: "phase_flip", params: { p: 0.02 } },
                        depolarizing: { kind: "depolarizing", params: { p: 0.02 } },
                        amplitude_damping: { kind: "amplitude_damping", params: { gamma: 0.03 } },
                        phase_damping: { kind: "phase_damping", params: { lambda: 0.03 } },
                        thermal: { kind: "thermal_relaxation", params: { t1: 60, t2: 50, duration: 0.2 } },
                        readout: { kind: "bit_flip", params: { p: 0.015 } },
                        uniform_gate: { kind: "depolarizing", params: { p: 0.01 } },
                      };
                      const entry = defaults[preset];
                      return [...current.filter((channel) => channel.kind !== entry.kind), { ...entry, scope: "gate" }];
                    })
                  }
                >
                  {preset.replace(/_/g, " ")}
                </Button>
              ))}
            </div>
          </Panel>
        </div>

        {/* -------------------------------------------------------- results */}
        <div className="space-y-3">
          {sweep.length > 0 && (
            <Panel
              title="Degradation curve"
              subtitle="Every channel probability scaled from 0 upward; each point is a real run of this circuit."
              dense
            >
              <LineChart
                x={sweep.map((point) => point.strength.toFixed(3))}
                series={[
                  { key: "fidelity", label: "fidelity vs ideal", y: sweep.map((point) => point.fidelity), colour: "var(--c-primary)" },
                  { key: "purity", label: "purity", y: sweep.map((point) => point.purity), colour: "var(--c-secondary)" },
                  { key: "entropy", label: "entropy (bits)", y: sweep.map((point) => point.entropy), colour: "var(--c-warn)" },
                ]}
                xLabel="noise strength"
                yLabel="value"
                height={230}
              />
              <p className="mt-1 text-[10px] text-[var(--c-faint)]">
                Fidelity falls and purity drops: that is decoherence, not sampling noise — sampling appears as a
                difference between the sampled and exact distributions, not in fidelity.
              </p>
            </Panel>
          )}

          {result && (
            <Panel
              title={result.mode === "NOISY SIMULATION" ? "Noisy result" : "Result"}
              subtitle={`${result.backend} · ${result.shots.toLocaleString()} shots · seed ${result.seed}`}
              actions={
                <>
                  <Tag colour={result.mode === "NOISY SIMULATION" ? "var(--c-warn)" : "var(--c-ok)"}>{result.mode}</Tag>
                  <Button size="sm" variant="ghost" onClick={() => onNavigate("execute")}>
                    full inspector →
                  </Button>
                </>
              }
            >
              <div className="grid gap-2 sm:grid-cols-4">
                <StatTile
                  label="fidelity vs ideal"
                  value={result.fidelity_vs_ideal === null ? "n/a" : <AnimatedNumber value={result.fidelity_vs_ideal} digits={5} />}
                  progress={result.fidelity_vs_ideal ?? undefined}
                  colour={result.fidelity_vs_ideal !== null && result.fidelity_vs_ideal < 0.95 ? "var(--c-warn)" : undefined}
                  hint={fidelityWords(result.fidelity_vs_ideal)}
                />
                <StatTile
                  label="trace distance"
                  value={result.trace_distance_vs_ideal === null ? "n/a" : <AnimatedNumber value={result.trace_distance_vs_ideal} digits={5} />}
                  hint="1 means completely distinguishable"
                />
                <StatTile label="purity" value={<AnimatedNumber value={result.metrics?.purity ?? 0} digits={5} />} hint="below 1 is a mixed state" />
                <StatTile label="entropy" value={<AnimatedNumber value={result.metrics?.entropy ?? 0} digits={5} />} unit="bits" />
              </div>

              <div className="mt-3">
                <WarningList warnings={result.warnings} notes={result.notes} />
              </div>

              <div className="mt-3 grid gap-3 lg:grid-cols-2">
                <div>
                  <SectionTitle hint="of the reported state">distribution after noise</SectionTitle>
                  <InspectBars
                    items={distribution.map((entry) => ({ label: `|${entry.basis}⟩`, value: entry.probability }))}
                    colour="var(--c-warn)"
                  />
                </div>
                <div>
                  <SectionTitle hint="ideal vs this run">where the probability went</SectionTitle>
                  <InspectBars
                    items={distribution.map((entry) => ({
                      label: `|${entry.basis}⟩`,
                      value: entry.probability,
                      secondary: (result.ideal_metrics && result.reference_probabilities?.[entry.basis]) ?? result.ideal_probabilities[entry.basis],
                    }))}
                    colour="var(--c-warn)"
                    overlay="var(--c-primary)"
                  />
                  <p className="mt-2 text-[10px] text-[var(--c-faint)]">
                    The bright edge is the ideal probability: the distance between the two is the error this model
                    introduced, not a modelling assumption.
                  </p>
                </div>
              </div>

              {result.ideal_metrics && (
                <div className="mt-3">
                  <SectionTitle>ideal vs noisy metrics</SectionTitle>
                  <CompareBars
                    rows={[
                      { metric: "purity", a: result.ideal_metrics.purity ?? 0, b: result.metrics.purity ?? 0, delta: (result.metrics.purity ?? 0) - (result.ideal_metrics.purity ?? 0) },
                      { metric: "entropy", a: result.ideal_metrics.entropy ?? 0, b: result.metrics.entropy ?? 0, delta: (result.metrics.entropy ?? 0) - (result.ideal_metrics.entropy ?? 0) },
                      {
                        metric: "dominant probability",
                        a: result.ideal_metrics.dominant_probability ?? 0,
                        b: result.metrics.dominant_probability ?? 0,
                        delta: (result.metrics.dominant_probability ?? 0) - (result.ideal_metrics.dominant_probability ?? 0),
                      },
                    ]}
                  />
                </div>
              )}
            </Panel>
          )}

          {sweep.length > 0 && (
            <Panel title="Sweep table" subtitle="The same numbers, tabulated for a report." dense>
              <div className="overflow-x-auto">
                <table className="w-full text-[11px]">
                  <thead>
                    <tr className="label-xs border-b border-[var(--c-line)]">
                      <th className="px-2 py-1.5 text-left">strength</th>
                      <th className="px-2 py-1.5 text-right">fidelity</th>
                      <th className="px-2 py-1.5 text-right">purity</th>
                      <th className="px-2 py-1.5 text-right">entropy</th>
                      <th className="px-2 py-1.5 text-right">dominant p</th>
                      <th className="px-2 py-1.5 text-right">mode</th>
                    </tr>
                  </thead>
                  <tbody>
                    {sweep.map((point) => (
                      <tr key={point.strength} className="border-b border-[color-mix(in_oklab,var(--c-line)_50%,transparent)]">
                        <td className="mono-num px-2 py-1.5">{point.strength.toFixed(3)}</td>
                        <td className="mono-num px-2 py-1.5 text-right">{point.fidelity === null ? "n/a" : point.fidelity.toFixed(5)}</td>
                        <td className="mono-num px-2 py-1.5 text-right">{point.purity?.toFixed(5) ?? "—"}</td>
                        <td className="mono-num px-2 py-1.5 text-right">{point.entropy?.toFixed(5) ?? "—"}</td>
                        <td className="mono-num px-2 py-1.5 text-right">{point.dominant ? formatPercent(point.dominant, 2) : "—"}</td>
                        <td className="px-2 py-1.5 text-right">
                          <Tag colour={point.status === "NOISY SIMULATION" ? "var(--c-warn)" : "var(--c-ok)"}>{point.status}</Tag>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="mt-2">
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => void buildReport("simulation", { source: { circuit }, shots: settings.shots, noise: noiseSpec, compare_ideal: true }, "Noise report")}
                >
                  noise report
                </Button>
              </div>
            </Panel>
          )}

          {!result && sweep.length === 0 && (
            <InView>
              <Panel title="What to look for" subtitle="How to read a noise experiment honestly.">
                <div className="grid gap-2 sm:grid-cols-2">
                  {[
                    ["Fidelity", "State fidelity to the exact reference: the headline number, and the one to quote."],
                    ["Trace distance", "How distinguishable the two states are; complements fidelity, does not duplicate it."],
                    ["Purity", "Tr(ρ²) below 1 proves the state is mixed — something irreversible happened."],
                    ["Entropy", "Where the lost purity went. Entropy rises as coherence is destroyed."],
                    ["Dominant contributor", "On a device estimate, which error source dominates the budget."],
                    ["Readout error", "Separate from gate error: it corrupts the histogram, not the state."],
                  ].map(([title, text]) => (
                    <div key={title} className="panel-flat px-3 py-2">
                      <div className="text-[11px] font-medium">{title}</div>
                      <p className="mt-0.5 text-[10px] leading-relaxed text-[var(--c-muted)]">{text}</p>
                    </div>
                  ))}
                </div>
                <div className="mt-3">
                  <Notice tone="warn" title="What this view never claims">
                    Numbers here come from a model you configured, simulated on this machine. They are not measurements
                    of any physical device, and they are never presented as such.
                  </Notice>
                </div>
              </Panel>
            </InView>
          )}
        </div>
      </div>
    </div>
  );
}
