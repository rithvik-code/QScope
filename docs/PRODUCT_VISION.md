# QScope product vision

QScope is a downloadable, local-first quantum-computing workspace. A person should be able to clone the repository, run one command on a normal laptop, and go from a plain-language question to a runnable, explainable quantum experiment.

The product is not only a simulator. It combines a circuit IDE, a quantum execution engine, visual debugging, algorithm examples, performance measurement, and an assistant that explains the user's own work.

## The simple promise

> Ask a question. Build or choose a circuit. Run it locally. See what happened. Understand why.

The interface should feel as approachable as a chat product while remaining honest and technically useful. Beginner actions stay simple; advanced controls remain available without dominating the first screen.

## Product pillars

1. **Local-first quantum computing**
   - Works on a regular laptop with Python and NumPy.
   - No account, cloud quantum provider, or GPU is required.
   - Optional hardware and LLM integrations are clearly separated from local simulation.

2. **One continuous workspace**
   - Build, execute, trace, analyze, optimize, experiment, benchmark, and research all use the same circuit and recorded results.
   - The user should not need to understand the internal API or data model to move between stages.

3. **Explainability by default**
   - Show the state after each gate, probability changes, entanglement, fidelity, and limitations.
   - Prefer plain-language explanations alongside technical values.
   - Never present a classical simulation as real quantum hardware.

4. **ChatGPT-like assistance, grounded in evidence**
   - The user can ask questions in ordinary language.
   - The assistant can create a circuit, run a supported operation, explain a result, or generate a report.
   - Every numeric claim is sourced from QScope's recorded artifacts.

5. **Research and engineering quality**
   - Reproducible seeds, provenance, saved history, comparisons, exports, and reports.
   - Safe memory budgets and explicit refusal when a laptop cannot complete a request.

## User-facing modes

The default path is intentionally short:

`Ask / Start → Build → Run → Understand`

Advanced tools remain available under an explicit tools drawer:

`Analyze · Optimize · Noise · Experiment · Benchmark · Research`

The user should be able to begin with a ready-made Bell state, GHZ state, teleportation, Grover search, QFT, or Bernstein–Vazirani example, then progressively move toward custom circuits and QASM.

## Architecture

```text
Local web UI
  ├─ simple workspace and chat-like command bar
  ├─ circuit canvas and visual state panels
  └─ advanced research tools
          │ HTTP / WebSocket
Python API
  ├─ circuit model and validation
  ├─ statevector / density-matrix / trajectory engines
  ├─ trace, diff, analysis, optimization, experiments
  ├─ local history and report generation
  └─ grounded assistant
```

The Python engine remains the source of truth. The interface computes nothing and renders only server-provided artifacts.

## Definition of “ready for GitHub”

- `git clone` followed by one documented command starts the product.
- A first-run check explains missing Python or Node dependencies.
- The app opens on a beginner-safe welcome flow, not a wall of controls.
- A user can complete a Bell State experiment without reading the documentation.
- Advanced capabilities remain discoverable and tested.
- README examples match the actual commands and ports.
- CI runs Python tests, frontend type-check/build, and a smoke test against `/api/health`.

## Delivery sequence

### Phase 1 — approachable core

- Simplified shell and progressive disclosure.
- Chat-like “What do you want to explore?” entry point.
- One-click starter experiments.
- Continuous Build → Run → Understand flow.

### Phase 2 — visual quantum workspace

- Circuit canvas with drag/drop gates and readable gate explanations.
- Statevector probabilities, amplitudes, phase, Bloch sphere, and entanglement views.
- Gate-by-gate timeline with a plain-language insight for the selected step.

### Phase 3 — assistant and research

- Natural-language circuit creation and result explanation.
- Saved projects, experiment comparison, reproducibility controls, and reports.
- Optional LLM narration that cannot override grounded numeric results.

### Phase 4 — distribution and performance

- Single-command local install and startup checks.
- Packaged desktop option when the web-local workflow is stable.
- CPU/GPU/backend benchmarking with honest measured-vs-estimated labels.

## Non-goals

- Pretending laptop simulation is equivalent to a quantum processor.
- Hiding complexity by deleting the underlying research tools.
- Requiring cloud accounts for the core experience.
- Adding an ungrounded chatbot that invents circuit results.
