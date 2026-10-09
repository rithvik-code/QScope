/**
 * Mission Control.
 *
 * The front page answers one question: *what is this environment, and what can I
 * do right now?*  It shows the live state of the running system, the workflow as a
 * navigable map, and real numbers from the last run — never placeholder figures.
 */

import { useMemo } from "react";
import { HeroBackdrop } from "../components/backgrounds";
import { FieldGuide } from "../components/Guide";
import { AnimatedNumber, InView, Spotlight, StaggerItem, TextEffect } from "../components/motion";
import { MODES, type ModeKey } from "../components/Shell";
import { Button, Notice, Panel, SectionTitle, StatTile, Tag } from "../components/ui";
import { formatMegabytes, formatSeconds, sortedProbabilities } from "../lib/format";
import { useStore } from "../state/store";

export function MissionControl({ onNavigate }: { onNavigate: (mode: ModeKey) => void }) {
  const { meta, health, log, result, document: circuit, trace, optimization, selection, loadAlgorithm, history } = useStore();
  const distributions = useMemo(() => (result ? sortedProbabilities(result.ideal_probabilities, 6) : []), [result]);

  return (
    <div className="space-y-4">
      {/* ------------------------------------------------------------ welcome guide */}
      <FieldGuide
        modeName="Mission Control"
        slides={[
          {
            heading: "What you are looking at",
            steps: [
              {
                title: "This page answers one question: what can I do right now?",
                body: "Mission Control is the front page. The hero on the left opens the environment — what it is, the six questions it is built to answer, and the three doors in: the circuit IDE, the quantum time machine, and the assistant. The environment panel on the right reads the live state of the running system from the engine, with real numbers from the last run when there is one.",
                pointer: "hero — title, lede, open buttons, six questions; This environment — version, python, numpy, stored runs, history database, reports directory, assistant status",
              },
              {
                title: "The workflow map is the whole platform as one instrument",
                body: "The middle band is a navigable map of the stages: Build, Execute, Trace, Analyse, Optimise, and the ones after them. Each card states what that stage does in one line and links straight to it. The point is that each stage uses the output of the previous one — nothing here is a separate toy.",
                pointer: "The workflow, as one instrument — the mode cards",
                tip: "one map, every mode",
              },
              {
                title: "The lower panels are the real numbers behind the welcome",
                body: "Last executed run shows shots, runtime, state memory and fidelity versus ideal from the most recent run, plus the dominant outcomes from the final state. Loaded circuit shows what the next run would use. Ready-made experiments loads algorithms straight into the IDE. Session activity and stored history keep the recent footprint visible.",
                pointer: "Last executed run; Loaded circuit; Ready-made experiments; Session activity; Stored history",
              },
            ],
          },
          {
            heading: "How to use this page",
            steps: [
              {
                title: "Start from the door that matches the question you have",
                body: "If you are here to compose something, open the circuit IDE. If you want to watch the state evolve gate by gate, open the quantum time machine. If you have data already and want an explanation, ask the assistant. The six questions under the lede are the fastest way to pick: each one maps to a stage deeper in the platform.",
                pointer: "hero — Open the circuit IDE / Open the quantum time machine / Ask the assistant; the six question bullets",
                highlight: 6,
                tip: "three doors on this page",
              },
              {
                title: "Use the workflow map as your table of contents",
                body: "The card for each mode is a button. Click it to jump straight there. The cards are in workflow order, and each blurb says what that stage takes from the previous one, so the map is also a short explanation of how the pieces fit together.",
                pointer: "The workflow, as one instrument — the mode cards",
              },
              {
                title: "Use the environment panel to check the session is live",
                body: "Before you start a longer task, glance at This environment — version, python, numpy and the assistant status tell you what the backend can do right now. Stored runs and the history database path tell you whether earlier work is available to quote. If the last run is empty, the notice tells you to load a circuit in Build and execute it in Execute.",
                pointer: "This environment; Last executed run — the empty-state notice",
              },
            ],
          },
        ]}
      />

      {/* ------------------------------------------------------------ hero */}
      <section className="panel relative overflow-hidden p-0">
        <HeroBackdrop className="absolute inset-0" />
        <div className="relative grid gap-6 p-6 lg:grid-cols-[1.35fr_1fr] lg:p-8">
          <div>
            <TextEffect
              text="See inside quantum computing"
              className="block text-[30px] font-semibold leading-tight tracking-tight lg:text-[38px]"
            />
            <p className="mt-3 max-w-[62ch] text-[13px] leading-relaxed text-[var(--c-muted)]">
              QScope is a research environment, not a run button. Compose a circuit, execute it, then walk the state
              through every gate, diff what each one moved, optimise it with proofs, add noise, run parameter sweeps,
              measure how the engine scales — and write the whole thing up from the same data.
            </p>
            <div className="mt-5 flex flex-wrap items-center gap-2">
              <Button variant="primary" onClick={() => onNavigate("build")}>
                Open the circuit IDE
              </Button>
              <Button variant="outline" onClick={() => onNavigate("trace")}>
                Open the quantum time machine
              </Button>
              <Button variant="ghost" onClick={() => onNavigate("research")}>
                Ask the assistant
              </Button>
            </div>
            <div className="mt-5 grid gap-2 sm:grid-cols-2">
              {[
                "What happens to the state after every gate?",
                "Which gate caused the biggest change?",
                "Where does entanglement appear?",
                "How close is the noisy result to the ideal one?",
                "How much did optimisation really improve?",
                "How does runtime scale with qubits?",
              ].map((question) => (
                <div key={question} className="flex items-start gap-2 text-[11px] text-[var(--c-muted)]">
                  <span className="mt-[5px] h-1.5 w-1.5 shrink-0 rounded-full bg-[var(--c-primary)]" />
                  {question}
                </div>
              ))}
            </div>
          </div>

          <div className="space-y-3">
            <Panel title="This environment" subtitle="Read from the running engine." dense>
              <div className="grid grid-cols-2 gap-2">
                <StatTile label="version" value={health?.version ?? "—"} hint="qscope" />
                <StatTile label="python" value={health?.python ?? "—"} hint="interpreter" />
                <StatTile label="numpy" value={health?.numpy ?? "—"} hint="compute backend" />
                <StatTile
                  label="stored runs"
                  value={<AnimatedNumber value={health?.experiments_stored ?? 0} digits={0} />}
                  hint="sqlite history"
                />
              </div>
              <div className="mt-2 space-y-1.5">
                <div className="flex items-center justify-between text-[10px]">
                  <span className="text-[var(--c-faint)]">history database</span>
                  <span className="mono-num truncate text-[var(--c-muted)]" title={health?.database}>
                    {health?.database ?? "—"}
                  </span>
                </div>
                <div className="flex items-center justify-between text-[10px]">
                  <span className="text-[var(--c-faint)]">reports directory</span>
                  <span className="mono-num truncate text-[var(--c-muted)]" title={health?.reports_dir}>
                    {health?.reports_dir ?? "—"}
                  </span>
                </div>
                <div className="flex items-center justify-between text-[10px]">
                  <span className="text-[var(--c-faint)]">research assistant</span>
                  <Tag colour={health?.llm_configured ? "var(--c-accent)" : "var(--c-ok)"}>
                    {health?.llm_configured ? "grounded + LLM narration" : "grounded, fully offline"}
                  </Tag>
                </div>
              </div>
            </Panel>

            <Panel title="Loaded circuit" subtitle="What the next run would use." dense>
              {circuit ? (
                <div className="grid grid-cols-3 gap-2">
                  <StatTile label="qubits" value={circuit.num_qubits} />
                  <StatTile label="gates" value={circuit.resources.gates} />
                  <StatTile label="depth" value={circuit.resources.depth} />
                  <StatTile label="2-qubit" value={circuit.resources.two_qubit_gates} />
                  <StatTile label="classical" value={circuit.num_clbits} />
                  <StatTile label="clifford" value={circuit.resources.is_clifford ? "yes" : "no"} />
                </div>
              ) : (
                <p className="text-[11px] text-[var(--c-faint)]">Loading…</p>
              )}
              <p className="mt-2 truncate text-[10px] text-[var(--c-faint)]">
                source: {selection.algorithm ? `algorithm ${selection.algorithm}` : "circuit document"}
              </p>
            </Panel>
          </div>
        </div>
      </section>

      {/* --------------------------------------------------- workflow map */}
      <InView>
        <Panel
          title="The workflow, as one instrument"
          subtitle="Each stage uses the output of the previous one; nothing is a separate toy."
        >
          <div className="grid gap-2.5 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
            {MODES.slice(1).map((entry, index) => (
              <StaggerItem key={entry.key}>
                <Spotlight className="h-full rounded-xl">
                  <button
                    type="button"
                    onClick={() => onNavigate(entry.key)}
                    className="panel-flat focus-ring h-full w-full p-3 text-left transition-colors hover:border-[var(--c-primary)]"
                  >
                    <div className="flex items-center justify-between">
                      <span className="label-xs">{entry.stage}</span>
                      <span className="text-[10px] text-[var(--c-faint)]">0{index + 1}</span>
                    </div>
                    <div className="mt-1 text-[13px] font-medium">{entry.label}</div>
                    <p className="mt-1 text-[11px] leading-snug text-[var(--c-muted)]">{entry.blurb}</p>
                  </button>
                </Spotlight>
              </StaggerItem>
            ))}
          </div>
        </Panel>
      </InView>

      {/* ------------------------------------------------------- live state */}
      <div className="grid gap-4 lg:grid-cols-3">
        <InView className="lg:col-span-2">
          <Panel
            title="Last executed run"
            subtitle={result ? result.circuit_name : "Nothing executed yet in this session."}
            actions={
              result ? (
                <Tag colour={result.mode === "NOISY SIMULATION" ? "var(--c-warn)" : "var(--c-ok)"}>{result.mode}</Tag>
              ) : undefined
            }
          >
            {result ? (
              <div className="space-y-3">
                <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                  <StatTile
                    label="shots"
                    value={result.shots.toLocaleString()}
                    hint={`seed ${result.seed}`}
                  />
                  <StatTile
                    label="runtime"
                    value={formatSeconds(result.timing?.total_seconds)}
                    hint={result.backend}
                  />
                  <StatTile
                    label="state memory"
                    value={formatMegabytes(result.memory?.state_mb)}
                    hint={result.plan?.representation ?? ""}
                  />
                  <StatTile
                    label="fidelity vs ideal"
                    value={
                      result.fidelity_vs_ideal === null ? (
                        "n/a"
                      ) : (
                        <AnimatedNumber value={result.fidelity_vs_ideal} digits={4} />
                      )
                    }
                    hint={result.fidelity_vs_ideal === null ? "ideal run — nothing to compare" : "measured against the exact state"}
                    progress={result.fidelity_vs_ideal ?? undefined}
                    colour={result.fidelity_vs_ideal !== null && result.fidelity_vs_ideal < 0.95 ? "var(--c-warn)" : undefined}
                  />
                </div>
                {distributions.length > 0 && (
                  <div>
                    <SectionTitle hint="born distribution of the final state">most probable outcomes</SectionTitle>
                    <div className="flex flex-wrap gap-2">
                      {distributions.map((entry) => (
                        <Tag key={entry.basis} colour="var(--c-secondary)">
                          |{entry.basis}⟩ {entry.probability.toFixed(4)}
                        </Tag>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            ) : (
              <Notice tone="info">
                Load a circuit in <strong>Build</strong> and execute it in <strong>Execute</strong>. Every later stage —
                trace, metrics, optimisation, sweeps, benchmarks and reports — reads the result from here.
              </Notice>
            )}
          </Panel>
        </InView>

        <InView>
          <Panel title="Ready-made experiments" subtitle="Loaded straight into the IDE." dense>
            <div className="space-y-1.5">
              {(meta?.algorithms ?? []).slice(0, 7).map((algorithm) => (
                <button
                  key={algorithm.key}
                  type="button"
                  onClick={() => {
                    void loadAlgorithm(algorithm.key);
                    onNavigate("build");
                  }}
                  className="focus-ring w-full rounded-lg border border-[var(--c-line)] px-2.5 py-1.5 text-left transition-colors hover:border-[var(--c-primary)]"
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="truncate text-[11px] font-medium">{algorithm.name}</span>
                    <span className="mono-num shrink-0 text-[10px] text-[var(--c-faint)]">
                      {algorithm.qubits}q · {algorithm.gates}g
                    </span>
                  </div>
                  <p className="mt-0.5 line-clamp-2 text-[10px] leading-snug text-[var(--c-muted)]">
                    {algorithm.description}
                  </p>
                </button>
              ))}
            </div>
          </Panel>
        </InView>
      </div>

      {/* --------------------------------------------------- session + history */}
      <div className="grid gap-4 lg:grid-cols-2">
        <Panel title="Session activity" subtitle="Actions taken in this browser session." dense>
          <div className="grid grid-cols-3 gap-2">
            <StatTile label="actions" value={<AnimatedNumber value={log.length} digits={0} />} />
            <StatTile label="trace steps" value={trace ? trace.steps.length : 0} hint={trace ? trace.depth_mode : "not traced"} />
            <StatTile
              label="optimisation"
              value={optimization ? `${optimization.improvements.gates_saved ?? 0}` : "0"}
              hint="gates saved"
            />
          </div>
          <div className="mt-2 space-y-1">
            {log.slice(0, 5).map((entry, index) => (
              <div key={index} className="flex items-center gap-2 text-[10px]">
                <span className="mono-num text-[var(--c-faint)]">{entry.at}</span>
                <span style={{ color: entry.ok ? "var(--c-text)" : "var(--c-danger)" }}>{entry.action}</span>
                <span className="truncate text-[var(--c-muted)]">{entry.detail}</span>
              </div>
            ))}
          </div>
        </Panel>

        <Panel title="Stored history" subtitle={`${history.length} most recent runs, newest first.`} dense>
          {history.length === 0 ? (
            <Notice tone="info">No stored runs yet. Executing with “store result” on records one.</Notice>
          ) : (
            <div className="space-y-1">
              {history.slice(0, 8).map((entry) => (
                <div key={entry.experiment_id} className="flex items-center gap-2 border-b border-[color-mix(in_oklab,var(--c-line)_40%,transparent)] pb-1">
                  <span className="mono-num shrink-0 text-[10px] text-[var(--c-faint)]">{entry.created_at.slice(11)}</span>
                  <span className="truncate text-[11px]">{entry.circuit_name}</span>
                  <Tag colour={entry.mode === "NOISY SIMULATION" ? "var(--c-warn)" : "var(--c-ok)"}>{entry.mode}</Tag>
                  <span className="mono-num ml-auto shrink-0 text-[10px] text-[var(--c-muted)]">
                    {entry.num_qubits}q · {formatSeconds(entry.runtime_seconds)}
                  </span>
                </div>
              ))}
            </div>
          )}
        </Panel>
      </div>
    </div>
  );
}
