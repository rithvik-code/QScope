import { useState } from "react";
import type { ModeKey } from "./Shell";
import { Button, Panel, Tag } from "./ui";
import { useStore } from "../state/store";
import { CircuitCanvas, PhaseDial, type Amplitude } from "./viz/quantum";
import { sortedProbabilities } from "../lib/format";
import { api } from "../lib/api";

const starters = [
  { key: "bell_state", title: "See entanglement", detail: "Build a Bell state and watch two qubits become connected.", colour: "var(--c-primary)" },
  { key: "ghz_state", title: "Explore a GHZ state", detail: "Create a three-qubit state with one simple idea.", colour: "var(--c-secondary)" },
  { key: "grover", title: "Search with Grover", detail: "See how amplitude amplification finds a marked answer.", colour: "var(--c-accent)" },
];

export function SimpleHome({ onNavigate }: { onNavigate: (mode: ModeKey) => void }) {
  const { health, document: circuit, result, trace, settings, answer, loading, ask: askAssistant, loadAlgorithm, history, setSource, runPanic, note } = useStore();
  const [question, setQuestion] = useState("");
  const amplitudes = result?.statevector?.amplitudes as unknown as Amplitude[] | undefined;

  const ask = () => {
    const text = question.toLowerCase();
    if (!question.trim()) return;
    if (text.includes("grover")) { void loadAlgorithm("grover"); onNavigate("build"); return; }
    if (text.includes("ghz")) { void loadAlgorithm("ghz_state", { num_qubits: 3 }); onNavigate("build"); return; }
    if (text.includes("bell state") || text.includes("entangle")) { void loadAlgorithm("bell_state"); onNavigate("build"); return; }
    const source = circuit ? { circuit } : undefined;
    const body: Record<string, unknown> = { question: question.trim(), use_llm: false };
    if (source) body.source = source;
    if (source && result) body.simulate = { source, shots: settings.shots, seed: settings.seed, backend: settings.backend, noise: settings.noise, compare_ideal: true, store: false };
    void askAssistant(body);
  };

  return (
    <div className="mx-auto max-w-6xl space-y-8 py-6 lg:py-14">
      <section className="grid gap-8 lg:grid-cols-[1.1fr_.9fr] lg:items-end">
        <div>
          <Tag colour="var(--c-primary)">local quantum workspace</Tag>
          <h1 className="mt-5 max-w-[12ch] text-5xl font-semibold tracking-[-0.05em] sm:text-6xl">
            What do you want to understand?
          </h1>
          <p className="mt-5 max-w-xl text-base leading-relaxed text-[var(--c-muted)]">
            Ask a question, choose an experiment, or start with a blank circuit. QScope runs on your laptop and shows
            the reasoning behind every result.
          </p>
          <div className="mt-7 flex max-w-2xl items-center gap-2 rounded-2xl border border-[var(--c-line-strong)] bg-[var(--c-panel)] p-2 shadow-2xl shadow-black/10">
            <input
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              onKeyDown={(event) => { if (event.key === "Enter") ask(); }}
              placeholder="Try: show me how entanglement works"
              className="min-w-0 flex-1 bg-transparent px-3 py-3 text-sm outline-none placeholder:text-[var(--c-faint)]"
              aria-label="Ask QScope what to explore"
            />
            <Button variant="primary" onClick={ask}>Explore →</Button>
          </div>
          <p className="mt-3 text-[11px] text-[var(--c-faint)]">No cloud account required · simulations are clearly labelled</p>
          {loading.ask && <div className="mt-4 rounded-xl border border-[var(--c-line)] bg-[var(--c-panel)] p-4 text-xs text-[var(--c-muted)]">Checking the current QScope data…</div>}
          {answer && !loading.ask && <Panel title={answer.title} subtitle={`${answer.grounding} · ${answer.confidence}`} dense><p className="whitespace-pre-wrap text-xs leading-relaxed text-[var(--c-muted)]">{answer.body}</p>{answer.bullets.length > 0 && <ul className="mt-3 list-disc space-y-1 pl-4 text-xs text-[var(--c-muted)]">{answer.bullets.map((bullet) => <li key={bullet}>{bullet}</li>)}</ul>}</Panel>}
        </div>

        <Panel title="Your workspace" subtitle="A quiet place to experiment." dense>
          <div className="grid grid-cols-2 gap-2">
            <div className="rounded-xl bg-[var(--c-panel-2)] p-3"><div className="label-xs">engine</div><div className="mt-1 text-sm">{health ? "ready" : "connecting"}</div></div>
            <div className="rounded-xl bg-[var(--c-panel-2)] p-3"><div className="label-xs">mode</div><div className="mt-1 text-sm">offline</div></div>
            <div className="rounded-xl bg-[var(--c-panel-2)] p-3"><div className="label-xs">circuit</div><div className="mt-1 text-sm">{circuit ? `${circuit.num_qubits} qubits` : "none yet"}</div></div>
            <div className="rounded-xl bg-[var(--c-panel-2)] p-3"><div className="label-xs">last run</div><div className="mt-1 text-sm">{result ? "available" : "not yet"}</div></div>
          </div>
          <div className="mt-4 flex items-center justify-between border-t border-[var(--c-line)] pt-3 text-[11px] text-[var(--c-muted)]">
            <span>QScope {health?.version ?? "0.1.0"}</span><span>{health?.numpy ? `NumPy ${health.numpy}` : "local engine"}</span>
          </div>
        </Panel>
      </section>

      <section className="grid gap-3 lg:grid-cols-[1.2fr_.8fr]">
        <Panel title="Circuit workspace" subtitle={circuit?.name ?? "Your circuit will appear here."} dense>
          {circuit ? <CircuitCanvas circuit={circuit} compact /> : <button onClick={() => onNavigate("build")} className="w-full rounded-xl border border-dashed border-[var(--c-line-strong)] p-8 text-sm text-[var(--c-muted)] hover:border-[var(--c-primary)]">Start with a circuit →</button>}
          {circuit && <div className="mt-3 flex items-center justify-between text-[11px] text-[var(--c-faint)]"><span>{circuit.num_qubits} qubits · {circuit.resources.gates} gates</span><Button size="sm" variant="ghost" onClick={() => onNavigate("build")}>Edit circuit →</Button></div>}
        </Panel>
        <Panel title="Quantum state" subtitle={result ? `${result.mode} · measured by QScope` : "Run a circuit to see its state."} dense>
          {amplitudes?.length ? <div className="flex items-center gap-3"><PhaseDial amplitudes={amplitudes} size={150} limit={12} /><div className="min-w-0 flex-1 space-y-2">{sortedProbabilities(result!.ideal_probabilities, 4).map(({ basis, probability }) => <div key={basis}><div className="mb-1 flex justify-between text-[10px]"><span>|{basis}⟩</span><span>{(probability * 100).toFixed(1)}%</span></div><div className="h-1.5 overflow-hidden rounded-full bg-[var(--c-line)]"><div className="h-full rounded-full bg-gradient-to-r from-[var(--c-primary)] to-[var(--c-secondary)] transition-all duration-700" style={{ width: `${probability * 100}%` }} /></div></div>)}</div></div> : trace?.final_state?.amplitudes?.length ? <div className="flex items-center gap-3"><PhaseDial amplitudes={trace.final_state.amplitudes} size={150} limit={12} /><p className="text-xs text-[var(--c-muted)]">Trace state · {trace.final_state.entanglement_status}</p></div> : <div className="flex h-36 items-center justify-center rounded-xl border border-dashed border-[var(--c-line)] text-center text-xs text-[var(--c-faint)]">Your probability map and phase view<br/>will appear after a run.</div>}
          <div className="research-only mt-3 border-t border-[var(--c-line)] pt-2 text-[10px] text-[var(--c-faint)]">Probabilities and phases are returned by the local simulation engine.</div>
        </Panel>
      </section>

      <section>
          <div className="mb-3 flex items-end justify-between"><div><div className="label-xs">Start with a question</div><h2 className="mt-1 text-xl font-medium">Guided experiments</h2></div><div className="flex gap-2"><Button variant="ghost" onClick={() => onNavigate("build")}>Import QASM</Button><Button variant="ghost" onClick={() => onNavigate("build")}>Blank circuit →</Button></div></div>
        <div className="grid gap-3 md:grid-cols-3">
          {starters.map((starter) => (
            <button key={starter.key} type="button" onClick={() => { void loadAlgorithm(starter.key, starter.key === "ghz_state" ? { num_qubits: 3 } : {}); onNavigate("build"); }} className="focus-ring panel-flat group p-5 text-left transition-transform hover:-translate-y-0.5 hover:border-[var(--c-primary)]">
              <span className="mb-8 block h-2 w-12 rounded-full" style={{ background: starter.colour }} />
              <div className="text-base font-medium">{starter.title}</div><p className="mt-2 text-sm leading-relaxed text-[var(--c-muted)]">{starter.detail}</p><div className="mt-5 text-xs text-[var(--c-primary)] opacity-0 transition-opacity group-hover:opacity-100">Open experiment →</div>
            </button>
          ))}
        </div>
      </section>

      <section>
        <div className="mb-3 flex flex-wrap items-end justify-between gap-2">
          <div><div className="label-xs">Pick up where you left off</div><h2 className="mt-1 text-xl font-medium">Recent builds</h2></div>
          <Button variant="ghost" onClick={() => onNavigate("history")}>Open full history →</Button>
        </div>
        {history.length ? (
          <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
            {history.slice(0, 4).map((entry) => (
              <button
                key={entry.experiment_id}
                type="button"
                onClick={() => void runPanic("restore build", async () => {
                  const saved = await api.historyGet(entry.experiment_id);
                  if (!saved.circuit) throw new Error("This saved run does not include a circuit snapshot.");
                  await setSource({ circuit: saved.circuit });
                  note("restore build", `${saved.circuit_name} · ${saved.num_qubits} qubits`);
                  onNavigate("build");
                })}
                className="focus-ring panel-flat p-3 text-left transition-colors hover:border-[var(--c-primary)]"
              >
                <div className="truncate text-sm font-medium">{entry.name || entry.circuit_name}</div>
                <div className="mt-1 text-[10px] text-[var(--c-muted)]">{entry.num_qubits} qubits · {entry.gate_count} gates · {entry.shots.toLocaleString()} shots</div>
                <div className="mt-2 text-[10px] text-[var(--c-primary)]">Restore this circuit →</div>
              </button>
            ))}
          </div>
        ) : (
          <div className="rounded-xl border border-dashed border-[var(--c-line-strong)] p-4 text-xs text-[var(--c-muted)]">Your saved runs will appear here. Run a circuit with history enabled to keep a restorable snapshot.</div>
        )}
      </section>

      <section className="grid gap-3 md:grid-cols-3">
        {[['Build', 'Create or import a circuit.', 'build'], ['Run', 'Simulate it safely on your laptop.', 'execute'], ['Understand', 'Trace every gate and explain the result.', 'trace']].map(([title, text, mode]) => (
          <button key={title} type="button" onClick={() => onNavigate(mode as ModeKey)} className="focus-ring rounded-xl border border-transparent p-4 text-left hover:border-[var(--c-line-strong)]">
            <div className="text-sm font-medium">{title}</div><p className="mt-1 text-xs text-[var(--c-muted)]">{text}</p>
          </button>
        ))}
      </section>
    </div>
  );
}
