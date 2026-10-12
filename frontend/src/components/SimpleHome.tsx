import { useState } from "react";
import type { ModeKey } from "./Shell";
import { Button, Panel, Tag } from "./ui";
import { useStore } from "../state/store";

const starters = [
  { key: "bell_state", title: "See entanglement", detail: "Build a Bell state and watch two qubits become connected.", colour: "var(--c-primary)" },
  { key: "ghz_state", title: "Explore a GHZ state", detail: "Create a three-qubit state with one simple idea.", colour: "var(--c-secondary)" },
  { key: "grover", title: "Search with Grover", detail: "See how amplitude amplification finds a marked answer.", colour: "var(--c-accent)" },
];

export function SimpleHome({ onNavigate }: { onNavigate: (mode: ModeKey) => void }) {
  const { health, document: circuit, result, loadAlgorithm } = useStore();
  const [question, setQuestion] = useState("");

  const ask = () => {
    const text = question.toLowerCase();
    if (text.includes("grover")) void loadAlgorithm("grover");
    else if (text.includes("ghz")) void loadAlgorithm("ghz_state", { num_qubits: 3 });
    else void loadAlgorithm("bell_state");
    onNavigate("build");
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
