<div align="center">

# ◉ QScope

### See inside quantum computing.

**Build a circuit. Run it on your laptop. Understand every gate.**

QScope is a local-first quantum workspace that brings simulation, visual debugging,
analysis, optimization, experiments, and research into one approachable app.

<br />

`BUILD`　→　`RUN`　→　`TRACE`　→　`UNDERSTAND`

<br />

[Get started](#-get-started) · [Explore the workspace](#-one-workspace-every-step) · [How it works](#-under-the-hood)

</div>

---

## The idea

Quantum computing can feel like a wall of equations, tools, and unfamiliar terminology.
QScope makes the process tangible: create or import a circuit, execute it locally, and
inspect what happened—one operation at a time.

No quantum computer, GPU, cloud account, or paid service is needed to explore the
simulator. QScope runs on a regular computer, and clearly distinguishes classical
simulation from estimates and real hardware.

## ✨ One workspace, every step

| | Explore | What you can do |
|:--|:--|:--|
| **01 · Build** | Circuit IDE | Compose gates visually, use algorithms and parameters, import/export OpenQASM, and inspect circuit resources. |
| **02 · Execute** | Local simulation | Run circuits and inspect measurement results, amplitudes, probabilities, and execution details. |
| **03 · Trace** | Gate-by-gate debugger | Follow state changes through a circuit and compare what changed at each step. |
| **04 · Analyze** | Quantum observatory | Explore metrics, entanglement, circuit comparisons, and what-if questions. |
| **05 · Optimize** | Verified rewrites | Find optimization opportunities and review equivalence checks before accepting rewrites. |
| **06 · Noise** | Realistic imperfections | Apply explicit noise models and observe how they affect outcomes. |
| **07 · Experiment** | Reproducible sweeps | Vary parameters, track runs, and keep the settings needed to reproduce results. |
| **08 · Benchmark** | Performance lab | Measure runtime and memory, compare engines, and distinguish measured results from extrapolations. |
| **09 · Research** | Explain and share | Ask grounded questions about your work and export reports in multiple formats. |

### Built for curiosity *and* careful work

- **Understand, don’t just execute.** Inspect intermediate states and probability changes, not only the final answer.
- **Keep results traceable.** Runs carry the settings and provenance needed to interpret or reproduce them.
- **Make optimization accountable.** Review verification status; a failed verification is not silently applied.
- **Know what the numbers mean.** Simulation, noisy simulation, estimates, and hardware are not presented as interchangeable.
- **Start simple; go deeper when ready.** Begin with an example circuit, then open advanced analysis and research tools as needed.

## 🚀 Get started

### Requirements

- Python **3.11 or newer**
- Node.js and npm (to build the web interface the first time)

### Run QScope

```bash
git clone <your-qscope-repository-url>
cd QScope

# Install the Python engine and API
python -m pip install -e .

# Build the interface (first run, or after frontend changes)
cd frontend
npm install
npm run build
cd ..

# Start the complete app
python -m qscope
```

Open **http://127.0.0.1:8000** in your browser. The API reference is at
**http://127.0.0.1:8000/api/docs**.

> **Windows:** use `py -3.11` in place of `python` if that is how Python is installed.

### Frontend development

For hot reload, run the backend and Vite in separate terminals:

```bash
# Terminal 1 — from the repository root
python -m qscope

# Terminal 2
cd frontend
npm install
npm run dev
```

Open the local URL printed by Vite (usually **http://127.0.0.1:5173**). Its development
server proxies API and WebSocket requests to the Python backend.

### Handy options

```bash
python -m qscope --info       # Show environment details
python -m qscope --version    # Show the installed version
python -m qscope --port 9000  # Use another port
python -m qscope --reload     # Reload backend code during development
```

## 🧠 Under the hood

QScope's quantum engine is implemented with Python and NumPy. It includes state-vector,
density-matrix, and trajectory simulation, alongside circuit tools, debugging, analysis,
optimization, experiments, and a FastAPI service. The React + TypeScript interface talks
to that backend; it does not independently invent simulation results.

| Engine | What it represents | Useful for |
|:--|:--|:--|
| **State vector** | Complex amplitudes for a pure quantum state | Exact ideal circuit simulation |
| **Density matrix** | A mixed-state description | Exact modeling of supported noise channels |
| **Trajectory** | Sampled pure-state runs | Approximate noisy simulation |

Simulation size is limited by the memory and compute available on the machine. QScope
uses a configurable memory budget to avoid starting runs that exceed its planned limit.
Larger circuits can quickly become impractical on a classical computer.

## 🔌 API at a glance

The local API supports circuit validation and QASM, simulation, traces, analysis,
optimization, experiments, benchmarks, history, and report export. Interactive endpoint
documentation is available at `/api/docs` while QScope is running.

## 🧪 Development and tests

```bash
# Python tests
python -m pip install -e ".[dev]"
python -m pytest

# Frontend checks and production build
cd frontend
npm install
npm run typecheck
npm run build
```

## ⚖️ What QScope is—and isn’t

QScope is a **classical quantum-circuit simulator and research workspace**. It does not
turn a laptop into quantum hardware, and local simulation is not evidence of quantum
advantage. Hardware-related values are estimates unless a real provider is explicitly
connected. Simulation cost grows rapidly with circuit size; results should be interpreted
with their execution mode, settings, and stated limitations in mind.

## 🧭 Project direction

The long-term aim is a beginner-friendly, local-first quantum workspace: start from a
plain-language question, build or choose a circuit, run it, and understand the result—with
advanced research controls there when you need them.

See the [product vision](docs/PRODUCT_VISION.md) for the roadmap and design principles.

---

<div align="center">

**QScope — from quantum circuit to clear understanding.**

</div>
