# QScope — See Inside Quantum Computing

QScope is a **quantum computing research environment**, not a simulator with a run button.

It runs on a normal laptop, from one command, and it covers the whole loop a person
actually works in:

```
BUILD → EXECUTE → TRACE → ANALYZE → OPTIMIZE → EXPERIMENT → BENCHMARK → RESEARCH
```

Every stage consumes the output of the previous one. A circuit you build is executed,
walked gate by gate, measured, optimised with proofs, swept as an experiment, timed as a
benchmark, and written up as a report — from the same recorded data, with the provenance
attached to every number.

The simulator is the engine. The debugger is the microscope. The optimiser is the
laboratory instrument. The experiment engine is the research environment. The benchmark
observatory measures the instrument itself. The assistant is grounded in your data, and
the report generator is what you leave with.

---

## Quick start

```bash
# 1. the engine (Python 3.11+, NumPy, FastAPI)
python -m qscope                      # http://127.0.0.1:8000

# 2. the interface — build it once and it is served by the same process
cd frontend && npm install && npm run build && cd ..

python -m qscope                      # now http://127.0.0.1:8000 is the whole product
```

Useful switches:

```bash
python -m qscope --port 9000          # a different port
python -m qscope --host 0.0.0.0       # reachable from the local network
python -m qscope --reload             # reload on source changes (development)
python -m qscope --info               # environment report, then exit
python -m qscope --version
```

For frontend work, run the API and the Vite dev server side by side; Vite proxies `/api`
and `/ws` to the Python process:

```bash
python -m qscope &                    # API on :8000
cd frontend && npm run dev            # interface on :5173, hot reload
```

---

## The workflow, stage by stage

| Stage | What it is for | Where it lives |
| --- | --- | --- |
| **Mission Control** | The state of the environment, the workflow map, the last run, stored history | `frontend/src/modes/MissionControl.tsx` |
| **01 Build** | Circuit IDE: gates, parameters, algorithms, QASM import/export, JSON documents, resource counts | `modes/BuildMode.tsx` |
| **02 Execute** | Run it, and read the plan, mode, engine, exactness, histogram, amplitudes, density matrix, timing and memory | `modes/ExecuteMode.tsx` |
| **03 Trace** | The quantum time machine: state after every gate, Quantum Diff of what each gate moved, live streaming | `modes/TraceMode.tsx` |
| **04 Analyze** | Metrics, entanglement, two-circuit comparison, the what-if engine | `modes/AnalyzeMode.tsx` |
| **05 Optimize** | Verified rewrites with before/after proofs, opportunity audit, circuit evolution, hardware mapping | `modes/OptimizeMode.tsx` |
| **06 Noise** | Explicit error models, degradation curves, device estimates, fidelity accounting | `modes/NoiseMode.tsx` |
| **07 Experiment** | Parameter sweeps, live progress, per-point provenance, stored-run ledger, reproduction checks | `modes/ExperimentMode.tsx` |
| **08 Benchmark** | Measured runtime, memory ceilings, engine comparisons, fitted scaling with extrapolations labelled | `modes/BenchmarkMode.tsx` |
| **09 Research** | The grounded assistant and the report generator (HTML, PDF, JSON, CSV, Markdown) | `modes/ResearchMode.tsx` |

---

## What it does that a simulator does not

- **Gate-by-gate trace with a diff.** Every step carries the state before and after, the
  amplitudes that moved, the probability and phase changes, entanglement status, and the
  time the gate took. Streaming exists so a sweep can be watched as it happens.
- **Quantum Diff.** Probability changes per basis state, with the entanglement transition
  (`NONE → DETECTED`) shown next to them.
- **Optimisation that proves itself.** Rewrites are verified against the original — unitarily
  when the register is small enough, on random inputs otherwise — and the verification status
  (`PROVEN_EQUIVALENT`, `VERIFIED_ON_RANDOM_INPUTS`, `VERIFICATION_FAILED`, `NOT_VERIFIED`)
  is recorded with the result. A rewrite that fails verification is not applied.
- **Experiments that are reproducible, not decorative.** Each point is a real run stored with
  its seed, shots, engine and error model; a stored run can be re-executed from its own record
  and checked against the expected shot noise.
- **A performance observatory that measures.** Repeated trials, warm-up discarded, GC disabled
  during timing, medians with spread, and a fitted growth curve drawn dashed and labelled
  `EXTRAPOLATED` wherever it leaves the measured range.
- **A grounded assistant.** It classifies the question, reads the objects you attach, and
  answers from their numbers, citing the source of each value. With no LLM configured it still
  answers — entirely offline. An optional OpenAI-compatible endpoint may only rewrite the
  wording: every number in the narrative is checked against the grounded answer, and violations
  are reported rather than hidden.
- **One report generator, five exports.** The report re-runs the operation it describes, so it
  is reproducible by construction. The PDF writer is part of QScope — no LaTeX, no browser
  engine, no extra dependency.

---

## Honesty guarantees

These are properties of the code, not slogans:

- **Three modes, never blended.** `SIMULATED`, `NOISY SIMULATION` and `REAL HARDWARE` are
  separate labels (`qscope/simulator/simulator.py`). Ideal and noisy results are never merged
  into one figure, and every artefact carries the mode that produced it.
- **No fabricated numbers.** Benchmarks are wall-clock measurements on the machine that ran
  them. Hardware figures are *estimates from a model* and are labelled as estimates. Nothing
  claims quantum advantage — classical simulation cost is exponential in qubit count by
  construction, and the observatory exists to make that visible.
- **Refusals instead of guesses.** A run whose state would exceed the memory budget is refused
  with the arithmetic, not attempted. An experiment that measured nothing returns an error. An
  external comparison is only published if a third-party simulator is actually installed and
  actually run.
- **Limitations travel with results.** Metrics, traces, optimisations, hardware estimates,
  assistant answers and reports all carry the limitations of their own method.
- **The interface computes nothing.** Every number on screen comes from the Python engine, with
  the provenance the server attached (`mode`, `backend`, `representation`, `exact`, `seed`,
  `shots`, noise model, timing, memory).

---

## The engine

The mathematical core is written from first principles on NumPy — state vectors, tensor
products, controlled and multi-qubit gates, measurement, Kraus channels, partial traces,
entanglement measures, fidelity and trace distance. Nothing wraps another simulator.

| Engine | Representation | Exact | Noise | Practical ceiling |
| --- | --- | --- | --- | --- |
| `statevector` | 2ⁿ complex amplitudes | yes | no | ~27 qubits |
| `density_matrix` | 4ⁿ complex entries | yes | yes (exact mixed states) | far fewer qubits |
| `trajectory` | sampled pure-state trajectories | no — sampled | yes (sampled) | between the two |

A budget is enforced per simulation (`QSCOPE_MEMORY_MB`, default 60 % of available memory):
`plan_execution` refuses rather than attempting an allocation it cannot complete.

---

## The API

47 routes: 41 under `/api`, two websockets, plus the built-in docs. Highlights:

| Group | Endpoints |
| --- | --- |
| Discovery | `/api/health`, `/api/meta`, `/api/meta/{gates,metrics,noise,backends,hardware,experiments,whatif}` |
| Circuit | `/api/circuit/{validate,document,diagram,qasm,from-qasm}`, `/api/plan` |
| Execution | `/api/simulate`, `/api/simulate/batch` |
| Debugging | `/api/trace`, `/api/trace/diff`, `ws /ws/trace` |
| Analysis | `/api/metrics`, `/api/compare`, `/api/whatif` |
| Optimisation | `/api/optimize`, `/api/optimize/opportunities`, `/api/evolve`, `/api/hardware` |
| Experiments | `/api/experiments/run`, `ws /ws/experiment` |
| Performance | `/api/benchmark` (`scaling`, `backends`, `throughput`, `memory`, `external`, `suite`) |
| Research | `/api/ai/ask`, `/api/ai/suggestions` |
| Reporting | `/api/report`, `/api/report/export`, `/api/reports`, `/api/reports/{name}` |
| History | `/api/history`, `/api/history/{id}`, `/api/history/compare`, `/api/history/export`, `/api/history/reproduce/{id}` |

Interactive reference: **http://127.0.0.1:8000/api/docs**

---

## Environment

| Variable | Default | Meaning |
| --- | --- | --- |
| `QSCOPE_HOST` / `QSCOPE_PORT` | `127.0.0.1` / `8000` | bind address and port |
| `QSCOPE_RELOAD` | off | reload on source changes |
| `QSCOPE_DB` | `~/.qscope/qscope.sqlite3` | history database |
| `QSCOPE_REPORTS` | `~/.qscope/reports` | where reports are written |
| `QSCOPE_MEMORY_MB` | 60 % of available | per-simulation memory budget |
| `QSCOPE_FRONTEND` | `frontend/dist` | where the built interface is served from |
| `QSCOPE_DEV` | off | permissive CORS for a separate dev server |
| `QSCOPE_LLM_BASE_URL`, `QSCOPE_LLM_API_KEY`, `QSCOPE_LLM_MODEL` | unset | optional OpenAI-compatible narration endpoint |

---

## Development

```bash
# backend — 177 tests covering the maths, the engine and the HTTP surface
python -m pytest tests/

# frontend — typecheck and production build
cd frontend && npm run typecheck && npm run build
```

```
qscope/
  core/          tensors, gates, state vectors, density matrices, channels
  circuit/       circuit model, QASM, JSON documents, diagrams, resources
  simulator/     execution planning, noise models, the three engines
  debugger/      gate-by-gate tracing, Quantum Diff, streaming
  analysis/      metrics, entanglement, fidelity, comparison, what-if
  optimizer/     passes, verification, opportunity audit
  algorithms/    Bell, GHZ, teleportation, Deutsch–Jozsa, Bernstein–Vazirani,
                 Grover, QFT, QPE, VQE ansatz, QAOA Max-Cut
  hardware/      topologies, routing, noise estimates
  evolution/     candidate circuits under a fitness function
  experiments/   sweeps, SQLite history, benchmark observatory, reports, PDF writer
  ai/            intent classification, grounded answers, optional narration
  api/           FastAPI application, schemas, websockets, SPA hosting
frontend/        React + TypeScript + Tailwind v4 interface
  src/components/ motion primitives, SVG backdrops, interface kit, charts, quantum views
  src/modes/       one file per stage of the workflow
  src/theme/       the five-decision palette model, written to CSS variables
  src/lib/api.ts   typed client for every endpoint
  src/state/       one store: settings, the working circuit, and every artefact
tests/           test_core.py, test_engine.py, test_api.py
```

### Interface design

- **Motion** — small copy-in components in the spirit of Motion Primitives
  (`frontend/src/components/motion/`): reveal-on-scroll, staggering, counting numbers,
  cross-fading panels, pointer spotlight, meter bars. They reveal *change* — a value moving,
  a state difference appearing — rather than decorating.
- **Backdrops** — layered waves, blobs, poly grids and circle scatter generated as SVG in the
  browser, in the spirit of Haikei's layered assets, so no binary art is shipped and every
  backdrop follows the palette.
- **Palette** — the Realtime Colors model: five decisions (text, background, primary,
  secondary, accent), everything else derived, six presets, a randomiser, a shareable link and
  a live contrast check. Writing the palette to CSS variables repaints the whole instrument,
  charts included, without recomputing anything.
- **One accent per meaning** — the three modes, verification statuses, entanglement statuses
  and benchmark caveats each own a colour, and it is the same colour everywhere.

---

## What QScope does not claim

- It is not quantum hardware, and no number in it is a measurement of a physical device.
  Hardware views are estimates from a stated model, marked as such.
- It is not faster than the mathematics allows: classical state-vector simulation is exponential
  in qubit count, which is exactly what the benchmark observatory shows.
- It does not publish comparisons it cannot measure, numbers it did not compute, or results
  whose provenance it cannot state.

MIT licensed. Built to make quantum computation observable, experimentable, optimizable and
researchable.
