"""The QScope application server: REST, streaming WebSockets and the SPA host.

Every endpoint is a thin wrapper around the library.  It validates the request,
resolves the circuit and the noise model, calls exactly the same functions the
library exposes, and returns the objects' own ``to_dict()`` payloads — so the
API can never drift away from the engine that computed the answer.

Three rules are enforced here rather than in the UI, because a client should not
be able to lose them:

* every result carries the provenance the engine attached to it (engine,
  representation, exactness, seed, shots, noise model, timing, memory);
* the mode of a run is always reported as ``ideal``, ``noisy`` or ``hardware``,
  never blended into one number;
* anything that fails validation comes back as a structured error with a hint,
  never as a bare 500.
"""

from __future__ import annotations

import asyncio
import io
import json
import os
import platform
import sys
import time
from pathlib import Path
from typing import Any, Callable, Iterator

import numpy as np
from fastapi import Body, FastAPI, HTTPException, Query, Response, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from qscope import __version__
from qscope.ai import ResearchContext, ask as ai_ask, suggested_questions
from qscope.algorithms import algorithm_catalog, build_algorithm
from qscope.analysis.metrics import METRIC_DEFINITIONS, circuit_metrics, metric_glossary, state_metrics
from qscope.api.schemas import (
    AIRequest,
    BatchSimulateRequest,
    BenchmarkRequest,
    CircuitSource,
    CompareRequest,
    EvolutionRequest,
    ExperimentRequest,
    HardwareRequest,
    HealthResponse,
    MetricRequest,
    NoiseSpec,
    OptimizeRequest,
    PlanRequest,
    ReportRequest,
    SimulateRequest,
    TraceRequest,
    ValidateResponse,
    WhatIfRequest,
)
from qscope.circuit import Circuit, from_qasm
from qscope.core.gates import gate_catalog
from qscope.debugger import iter_trace, trace_circuit
from qscope.evolution import evolve_circuit
from qscope.experiments import (
    DEFAULT_DB,
    ExperimentSpec,
    ExperimentStore,
    SweepAxis,
    algorithm_scaling,
    backend_comparison,
    benchmark_backends,
    benchmark_gate_throughput,
    benchmark_scaling,
    benchmark_suite,
    compare_with_external,
    compute_circuit,
    custom_experiment,
    detect_external_backends,
    experiment_catalog,
    memory_observatory,
    noise_sweep,
    optimizer_comparison,
    parameter_sweep,
    report_from_comparison,
    report_from_evolution,
    report_from_experiment,
    report_from_hardware,
    report_from_optimization,
    report_from_result,
    report_from_trace,
    run_experiment,
    shots_convergence,
    what_if,
    what_if_catalog,
)
from qscope.hardware import HARDWARE_PRESETS, HardwareModel, hardware_report, preset_catalog
from qscope.optimizer import opportunities, optimization_levels, optimise
from qscope.simulator import (
    MODE_HARDWARE,
    MODE_IDEAL,
    MODE_NOISY,
    RunOptions,
    SimulationError,
    backend_catalog,
    memory_budget_bytes,
    noise_model_catalog,
    plan_execution,
    run_circuit,
    scaling_table,
)
from qscope.simulator.noise import NoiseChannel, NoiseModel

REPORTS_DIR = Path(os.environ.get("QSCOPE_REPORTS", Path.home() / ".qscope" / "reports"))
FRONTEND_DIST = Path(os.environ.get("QSCOPE_FRONTEND", Path(__file__).resolve().parents[2] / "frontend" / "dist"))


# ---------------------------------------------------------------------------
# resolution helpers
# ---------------------------------------------------------------------------


def resolve_circuit(source: CircuitSource) -> Circuit:
    """Turn a :class:`CircuitSource` into a real circuit, or explain why not."""
    provided = [
        name
        for name, value in (("circuit", source.circuit), ("qasm", source.qasm), ("algorithm", source.algorithm))
        if value
    ]
    if len(provided) > 1:
        raise ValueError(
            f"a circuit source may carry only one of circuit/qasm/algorithm; got {', '.join(provided)}"
        )
    if source.circuit:
        circuit = Circuit.from_dict(source.circuit)
    elif source.qasm:
        circuit = from_qasm(source.qasm)
    elif source.algorithm:
        circuit = build_algorithm(source.algorithm, **source.algorithm_kwargs).circuit
    else:
        if source.num_qubits is None:
            raise ValueError("provide one of circuit, qasm, algorithm, or num_qubits for an empty circuit")
        circuit = Circuit(int(source.num_qubits), int(source.num_clbits or 0), name=source.name or "circuit")
    if source.name:
        circuit.name = source.name
    if source.num_qubits is not None and source.num_qubits != circuit.num_qubits:
        # never silently ignore a size the caller asked for: either they meant it
        # (and the source disagrees) or they sent a stale value, and both deserve an
        # error rather than a result on the wrong register.
        raise ValueError(
            f"num_qubits={source.num_qubits} conflicts with the {circuit.num_qubits}-qubit circuit built from "
            f"{'the supplied document' if source.circuit else 'the supplied QASM' if source.qasm else repr(source.algorithm)}"
        )
    if source.num_clbits is not None and source.num_clbits > circuit.num_clbits:
        circuit.clbits = type(circuit.clbits)(int(source.num_clbits))
    if circuit.num_qubits > 32:
        raise ValueError(f"{circuit.num_qubits} qubits exceeds the 32-qubit API limit")
    return circuit


def resolve_noise(spec: NoiseSpec) -> NoiseModel:
    """Build a :class:`NoiseModel` from a preset name plus overrides."""
    payload: dict[str, Any] = {
        "name": spec.name,
        "readout_error": spec.readout_error,
        "one_qubit_gate_error": spec.one_qubit_gate_error,
        "two_qubit_gate_error": spec.two_qubit_gate_error,
        "multi_qubit_gate_error": spec.multi_qubit_gate_error,
        "idle_error": spec.idle_error,
        "description": spec.description,
        "calibrated": spec.calibrated,
    }
    base: NoiseModel | None = None
    if spec.name and spec.name != "ideal" and not spec.channels:
        base = preset_model(spec.name, spec.params)
        if base is not None:
            payload["readout_error"] = max(payload["readout_error"], base.readout_error)
            payload["channels"] = [c.to_dict() for c in base.channels]
            payload["description"] = payload["description"] or base.description
    if spec.channels:
        payload["channels"] = [
            {
                "kind": channel.kind,
                "params": channel.params,
                "scope": channel.scope,
                "qubits": channel.qubits,
                "after_gates": channel.after_gates,
                "label": channel.label,
                "approximate": channel.approximate,
            }
            for channel in spec.channels
        ]
    model = NoiseModel.from_dict(payload)
    if spec.scale is not None:
        model = _scale_model(model, float(spec.scale))
    return model


def preset_model(name: str, params: dict[str, float]) -> NoiseModel | None:
    """Named noise presets, resolved to the same constructors the library uses."""
    p = float(params.get("p", params.get("error", params.get("strength", 0.05))))
    gamma = float(params.get("gamma", params.get("gamma1", 0.05)))
    lam = float(params.get("lambda", params.get("lambda2", 0.05)))
    readout = float(params.get("readout_error", 0.02))

    def channel_model(kind: str, values: dict[str, float]) -> NoiseModel:
        return NoiseModel(name=f"{kind} {values}", channels=[NoiseChannel(kind, values)])

    presets: dict[str, Callable[[], NoiseModel]] = {
        "bit_flip": lambda: NoiseModel.bit_flip(p),
        "phase_flip": lambda: NoiseModel.phase_flip(p),
        "bit_phase_flip": lambda: channel_model("bit_phase_flip", {"p": p}),
        "depolarizing": lambda: NoiseModel.depolarizing(p),
        "amplitude_damping": lambda: NoiseModel.amplitude_damping(gamma),
        "phase_damping": lambda: NoiseModel.phase_damping(lam),
        "amp_phase": lambda: channel_model("amp_phase", {"gamma": gamma, "lambda": lam}),
        "thermal": lambda: NoiseModel.thermal(
            float(params.get("t1", 1.0)), float(params.get("t2", 1.0)), float(params.get("duration", 0.05))
        ),
        "readout": lambda: NoiseModel(
            name=f"readout {readout:g}",
            readout_error=readout,
            description=f"Symmetric readout error of {readout:g} on every measured qubit.",
        ),
        "uniform_gate": lambda: NoiseModel(
            name="uniform gate error",
            one_qubit_gate_error=float(params.get("one_qubit", 0.001)),
            two_qubit_gate_error=float(params.get("two_qubit", 0.01)),
            idle_error=float(params.get("idle", 0.0)),
            description="Depolarising error applied uniformly to each gate by arity.",
        ),
    }
    builder = presets.get(name)
    return builder() if builder else None


def _scale_model(model: NoiseModel, strength: float) -> NoiseModel:
    """Scale every probability in a model to ``strength`` (the noise-observatory knob)."""
    strength = min(max(strength, 0.0), 1.0)
    channels = []
    for channel in model.channels:
        payload = channel.to_dict()
        payload["params"] = {key: strength * float(value) for key, value in channel.params.items()}
        channels.append(NoiseChannel.from_dict(payload))
    scaled = NoiseModel.from_dict({**model.to_dict(), "channels": [c.to_dict() for c in channels]})
    scaled.readout_error = strength * model.readout_error
    scaled.one_qubit_gate_error = strength * model.one_qubit_gate_error
    scaled.two_qubit_gate_error = strength * model.two_qubit_gate_error
    scaled.multi_qubit_gate_error = strength * model.multi_qubit_gate_error
    scaled.idle_error = strength * model.idle_error
    scaled.name = f"{model.name} @ {strength:g}"
    return scaled


def circuit_document(circuit: Circuit, *, include_qasm: bool = True, include_diagram: bool = True) -> dict[str, Any]:
    """The editor's view of a circuit."""
    return {
        "format": Circuit.FORMAT,
        "version": Circuit.VERSION,
        "name": circuit.name,
        "num_qubits": circuit.num_qubits,
        "num_clbits": circuit.num_clbits,
        "operations": [op.to_dict() for op in circuit.operations],
        "resources": circuit.resources(),
        "diagram": circuit.diagram() if include_diagram else "",
        "qasm": circuit.to_qasm() if include_qasm else "",
        "metadata": dict(circuit.metadata),
    }


def run_options(request: SimulateRequest, noise: NoiseModel) -> RunOptions:
    return RunOptions(
        backend=request.backend,
        shots=request.shots,
        noise=noise,
        seed=request.seed,
        measure_all=request.measure_all,
        compare_ideal=request.compare_ideal and not noise.is_ideal(),
        memory_budget_mb=request.memory_budget_mb,
        max_qubits=request.max_qubits,
        label=request.label,
    )


def store_singleton() -> ExperimentStore:
    global _STORE
    if _STORE is None:
        _STORE = ExperimentStore()
    return _STORE


_STORE: ExperimentStore | None = None


def mode_label(mode: str) -> str:
    """The human label for a result mode.

    The engine already reports modes as labels (``SIMULATED``, ``NOISY
    SIMULATION``, ``REAL HARDWARE``); the slugs are accepted too so a client can
    round-trip whatever it holds.
    """
    return {"ideal": MODE_IDEAL, "noisy": MODE_NOISY, "hardware": MODE_HARDWARE}.get(mode, mode)


def safe_filename(name: str, fallback: str = "qscope-report") -> str:
    """An ASCII, quote-free filename for a Content-Disposition header.

    HTTP header values are latin-1, so a report title containing an em dash or a
    Greek letter cannot be echoed into the header verbatim.
    """
    import re
    import unicodedata

    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", ascii_name).strip("_.")[:80]
    return cleaned or fallback


def algorithm_accepts(algorithm: str, parameter: str) -> bool:
    """Whether an algorithm factory takes a given keyword (e.g. bell_state has no size)."""
    import inspect

    from qscope.algorithms import ALGORITHMS

    factory = ALGORITHMS.get(algorithm)
    if factory is None:
        return False
    try:
        return parameter in inspect.signature(factory).parameters
    except (TypeError, ValueError):  # pragma: no cover - builtins and the like
        return False


def custom_hardware(payload: dict[str, Any]) -> HardwareModel:
    """Build a device profile from a client description (topology + rates)."""
    from qscope.hardware.topology import CouplingMap

    num_qubits = int(payload.get("num_qubits") or 0)
    edges = payload.get("edges")
    topology = str(payload.get("topology", "linear"))
    if edges:
        coupling = CouplingMap(num_qubits, [(int(a), int(b)) for a, b in edges])
    elif num_qubits:
        coupling = {
            "ring": CouplingMap.ring,
            "all_to_all": CouplingMap.all_to_all,
        }.get(topology, CouplingMap.linear)(num_qubits)
    else:
        raise ValueError("a custom device needs num_qubits (and optionally edges)")
    known = set(HardwareModel.__dataclass_fields__) - {"coupling_map"}
    kwargs = {k: v for k, v in payload.items() if k in known and k not in {"name"}}
    if "native_one_qubit" in kwargs:
        kwargs["native_one_qubit"] = tuple(kwargs["native_one_qubit"])
    if "native_two_qubit" in kwargs:
        kwargs["native_two_qubit"] = tuple(kwargs["native_two_qubit"])
    return HardwareModel(
        name=str(payload.get("name", f"custom {topology} {num_qubits}q")),
        coupling_map=coupling,
        source=str(payload.get("source", "user-defined")),
        **kwargs,
    )


def fail(exc: Exception, *, status: int = 400) -> HTTPException:
    """A structured, actionable error instead of a bare stack trace."""
    hint = ""
    text = str(exc)
    if isinstance(exc, KeyError):
        text = text.strip("'\"")
        hint = "See /api/meta for the list of valid keys."
    elif isinstance(exc, SimulationError):
        hint = "The engine refused this run; reduce the qubit count or raise the memory budget."
        status = 422
    elif isinstance(exc, FileNotFoundError):
        status = 404
    return HTTPException(status_code=status, detail={"error": type(exc).__name__, "detail": text, "hint": hint})


# ---------------------------------------------------------------------------
# the application
# ---------------------------------------------------------------------------


def create_app() -> FastAPI:
    """Build the QScope API (a fresh instance per call, so tests can isolate)."""
    app = FastAPI(
        title="QScope",
        version=__version__,
        description=(
            "A quantum computing research environment: build, execute, trace, analyze, optimise, "
            "experiment, benchmark and report.  Every result records the engine that produced it, "
            "and ideal, noisy and hardware-estimated runs are never confused with one another."
        ),
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if os.environ.get("QSCOPE_DEV") else [],
        allow_origin_regex=r"http://(localhost|127\.0\.0\.1)(:\d+)?",
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(ValueError)
    async def _value_error(_request: Any, exc: ValueError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"error": "ValueError", "detail": str(exc), "hint": ""})

    @app.exception_handler(KeyError)
    async def _key_error(_request: Any, exc: KeyError) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content={"error": "KeyError", "detail": str(exc).strip("'\""), "hint": "See /api/meta for valid keys."},
        )

    # ------------------------------------------------------------- discovery

    @app.get("/api/health", response_model=HealthResponse)
    def health() -> dict[str, Any]:
        try:
            store = store_singleton()
            stored = store.count()
            database_ok = True
        except Exception:  # pragma: no cover - only when the sqlite file is unwritable
            stored, database_ok = 0, False
        return {
            "status": "ok",
            "version": __version__,
            "python": sys.version.split()[0],
            "numpy": np.__version__,
            "database": str(DEFAULT_DB),
            "database_ok": database_ok,
            "experiments_stored": stored,
            "reports_dir": str(REPORTS_DIR),
            "llm_configured": bool(os.environ.get("QSCOPE_LLM_BASE_URL")),
            "offline": True,
        }

    @app.get("/api/meta")
    def meta() -> dict[str, Any]:
        """One call that fills every picker in the UI."""
        return {
            "version": __version__,
            "platform": {
                "python": sys.version.split()[0],
                "platform": platform.platform(),
                "processor": platform.processor(),
                "numpy": np.__version__,
            },
            "modes": [
                {"key": "ideal", "label": MODE_IDEAL, "description": "Exact unitary evolution; no error model applied."},
                {"key": "noisy", "label": MODE_NOISY, "description": "The circuit plus an explicit error model, simulated on this machine."},
                {"key": "hardware", "label": MODE_HARDWARE, "description": "Numbers derived from a device model, not measured on a device."},
            ],
            "workflow": [
                {"key": "build", "label": "Build", "endpoint": "/api/circuit/validate"},
                {"key": "execute", "label": "Execute", "endpoint": "/api/simulate"},
                {"key": "trace", "label": "Trace", "endpoint": "/api/trace"},
                {"key": "analyze", "label": "Analyze", "endpoint": "/api/metrics"},
                {"key": "optimize", "label": "Optimize", "endpoint": "/api/optimize"},
                {"key": "experiment", "label": "Experiment", "endpoint": "/api/experiments/run"},
                {"key": "benchmark", "label": "Benchmark", "endpoint": "/api/benchmark"},
                {"key": "research", "label": "Research", "endpoint": "/api/ai/ask"},
            ],
            "algorithms": algorithm_catalog(),
            "hardware": preset_catalog(),
            "experiments": experiment_catalog(),
            "backends": backend_catalog(),
            "noise_models": noise_model_catalog(),
            "optimizer_levels": optimization_levels(),
            "whatif": what_if_catalog(),
            "ai_suggestions": suggested_questions(),
        }

    @app.get("/api/meta/gates")
    def meta_gates() -> dict[str, Any]:
        return {"gates": gate_catalog()}

    @app.get("/api/meta/metrics")
    def meta_metrics() -> dict[str, Any]:
        return {"metrics": metric_glossary(), "definitions": METRIC_DEFINITIONS}

    @app.get("/api/meta/noise")
    def meta_noise() -> dict[str, Any]:
        return {"channels": noise_model_catalog(), "presets": [
            "ideal", "bit_flip", "phase_flip", "bit_phase_flip", "depolarizing",
            "amplitude_damping", "phase_damping", "amp_phase", "thermal", "readout", "uniform_gate",
        ]}

    @app.get("/api/meta/backends")
    def meta_backends() -> dict[str, Any]:
        return {"backends": backend_catalog(), "scaling": scaling_table()}

    @app.get("/api/meta/hardware")
    def meta_hardware() -> dict[str, Any]:
        return {"devices": preset_catalog()}

    @app.get("/api/meta/experiments")
    def meta_experiments() -> dict[str, Any]:
        return {"experiments": experiment_catalog(), "kinds": [
            "algorithm_scaling", "noise_sweep", "backend_comparison", "optimizer_comparison",
            "shots_convergence", "parameter_sweep", "custom",
        ]}

    @app.get("/api/meta/whatif")
    def meta_whatif() -> dict[str, Any]:
        return {"modifications": what_if_catalog()}

    # --------------------------------------------------------------- circuits

    @app.post("/api/circuit/validate", response_model=ValidateResponse)
    def validate_circuit(source: CircuitSource) -> dict[str, Any]:
        try:
            circuit = resolve_circuit(source)
        except Exception as exc:
            return {"valid": False, "errors": [f"{type(exc).__name__}: {exc}"], "warnings": [], "resources": {}}
        warnings: list[str] = []
        if circuit.num_qubits > 20:
            warnings.append(
                f"{circuit.num_qubits} qubits needs {circuit.num_qubits * 16} bytes per statevector copy; "
                "statevector simulation becomes impractical here."
            )
        if circuit.num_clbits == 0 and any(op.kind == "measure" for op in circuit.operations):
            warnings.append("Measurement without classical bits: results are still sampled per qubit.")
        if circuit.depth() > 200:
            warnings.append(f"Depth {circuit.depth()} — traces and optimiser passes will take a while.")
        return {"valid": True, "errors": [], "warnings": warnings + circuit.resources().get("warnings", []), "resources": circuit.resources()}

    @app.post("/api/circuit/document")
    def circuit_doc(source: CircuitSource) -> dict[str, Any]:
        return circuit_document(resolve_circuit(source))

    @app.post("/api/circuit/diagram", response_class=PlainTextResponse)
    def circuit_diagram(source: CircuitSource) -> str:
        return resolve_circuit(source).diagram()

    @app.post("/api/circuit/qasm", response_class=PlainTextResponse)
    def circuit_qasm(source: CircuitSource) -> str:
        return resolve_circuit(source).to_qasm()

    @app.post("/api/circuit/from-qasm")
    def circuit_from_qasm(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
        text = payload.get("qasm")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("body must be {\"qasm\": \"...\"}")
        return circuit_document(from_qasm(text))

    # --------------------------------------------------------------- planning

    @app.post("/api/plan")
    def plan(request: PlanRequest) -> dict[str, Any]:
        circuit = resolve_circuit(request.source)
        noise = resolve_noise(request.noise)
        options = RunOptions(
            backend=request.backend,
            shots=request.shots,
            noise=noise,
            memory_budget_mb=request.memory_budget_mb,
        )
        plan = plan_execution(circuit, options).to_dict()
        plan["circuit"] = circuit_document(circuit, include_qasm=False, include_diagram=False)
        plan["budget"] = {
            "budget_bytes": memory_budget_bytes(request.memory_budget_mb),
            "budget_mb": memory_budget_bytes(request.memory_budget_mb) / 1e6,
            "source": "QSCOPE_MEMORY_MB" if request.memory_budget_mb is None else "request",
        }
        return plan

    # ------------------------------------------------------------- simulation

    @app.post("/api/simulate")
    def simulate(request: SimulateRequest) -> dict[str, Any]:
        circuit = resolve_circuit(request.source)
        noise = resolve_noise(request.noise)
        options = run_options(request, noise)
        try:
            result = run_circuit(circuit, options)
        except SimulationError as exc:
            raise fail(exc) from exc
        experiment_id: str | None = None
        if request.store:
            try:
                stored = store_singleton().record_result(
                    request.label or f"{circuit.name} · {mode_label(result.mode)}",
                    circuit,
                    result,
                    tags=[result.mode, result.backend, circuit.name],
                )
                experiment_id = stored.experiment_id
            except Exception as exc:  # storing must never lose a completed run
                result.warnings.append(f"result not stored: {type(exc).__name__}: {exc}")
        return {
            "result": result.to_dict(include_state=request.include_state),
            "circuit": circuit_document(circuit),
            "plan": result.plan,
            "experiment_id": experiment_id,
        }

    @app.post("/api/simulate/batch")
    def simulate_batch(request: BatchSimulateRequest) -> dict[str, Any]:
        noise = resolve_noise(request.noise)
        runs: list[dict[str, Any]] = []
        for source in request.sources:
            circuit = resolve_circuit(source)
            options = RunOptions(
                backend=request.backend,
                shots=request.shots,
                noise=noise,
                seed=request.seed,
                compare_ideal=not noise.is_ideal(),
            )
            result = run_circuit(circuit, options)
            runs.append(
                {
                    "result": result.to_dict(include_state=False),
                    "circuit": circuit_document(circuit, include_qasm=False, include_diagram=False),
                    "plan": result.plan,
                    "summary": {
                        "name": circuit.name,
                        "mode": result.mode,
                        "mode_label": mode_label(result.mode),
                        "backend": result.backend,
                        "fidelity_vs_ideal": result.fidelity_vs_ideal,
                        "trace_distance_vs_ideal": result.trace_distance_vs_ideal,
                        "dominant_basis": result.metrics.get("dominant_basis"),
                        "dominant_probability": result.metrics.get("dominant_probability"),
                        "entanglement_status": result.metrics.get("entanglement_status"),
                        "runtime_seconds": result.timing.get("total_seconds"),
                    },
                }
            )
        return {"runs": runs, "noise": noise.to_dict(), "shots": request.shots, "seed": request.seed}

    # ------------------------------------------------------------- debugging

    @app.post("/api/trace")
    def trace(request: TraceRequest) -> dict[str, Any]:
        circuit = resolve_circuit(request.source)
        traced = trace_circuit(
            circuit,
            depth=request.depth,
            term_limit=request.term_limit,
            max_steps=request.max_steps,
            analyze_last_only=request.analyze_last_only,
        )
        payload = traced.to_dict(max_steps=request.max_steps)
        payload["circuit"] = circuit_document(circuit, include_qasm=False, include_diagram=False)
        payload["summary"] = traced.summary()
        payload["diff"] = None
        return payload

    @app.post("/api/trace/diff")
    def trace_diff(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
        """Quantum Diff between two basis labels of an already-computed trace."""
        from qscope.debugger.state_diff import diff_states

        request = TraceRequest.model_validate(payload)
        circuit = resolve_circuit(request.source)
        traced = trace_circuit(circuit, depth=request.depth, term_limit=request.term_limit, max_steps=request.max_steps)
        return {
            "summary": traced.summary(),
            "diffs": [step.to_dict() for step in traced],
            "final": traced.final_state,
        }

    # ------------------------------------------------------------ optimisation

    @app.post("/api/optimize")
    def optimize(request: OptimizeRequest) -> dict[str, Any]:
        circuit = resolve_circuit(request.source)
        audit = opportunities(circuit)
        result = optimise(circuit, level=request.level, verify=request.verify)
        payload = result.to_dict(include_circuits=True)
        payload["opportunities"] = audit
        payload["headline"] = result.headline()
        payload["level"] = request.level
        payload["circuit"] = circuit_document(circuit, include_qasm=False, include_diagram=False)
        return payload

    @app.post("/api/optimize/opportunities")
    def optimize_opportunities(source: CircuitSource) -> dict[str, Any]:
        circuit = resolve_circuit(source)
        return {"findings": opportunities(circuit), "levels": optimization_levels(), "resources": circuit.resources()}

    # --------------------------------------------------------------- analysis

    @app.post("/api/metrics")
    def metrics(request: MetricRequest) -> dict[str, Any]:
        circuit = resolve_circuit(request.source)
        options = RunOptions(backend="auto", shots=1024, seed=20260101, compare_ideal=False)
        result = run_circuit(circuit, options)
        state = result.metrics or {}
        static = circuit_metrics(circuit)
        if request.keys:
            keep = set(request.keys)
            state = {k: v for k, v in state.items() if k in keep}
            static = {k: v for k, v in static.items() if k in keep
                      or k in {"gates", "depth", "two_qubit_gates", "qubits", "parameters", "is_clifford"}}
        return {
            "circuit": circuit_document(circuit, include_qasm=False, include_diagram=False),
            "state": state,
            "circuit_metrics": static,
            "plan": result.plan,
            "mode": result.mode,
            "mode_label": mode_label(result.mode),
            "shots": result.shots,
            "seed": result.seed,
            "warnings": result.warnings,
            "glossary": metric_glossary(),
        }

    @app.post("/api/compare")
    def compare(request: CompareRequest) -> dict[str, Any]:
        circuit_a = resolve_circuit(request.a)
        circuit_b = resolve_circuit(request.b)
        noise = resolve_noise(request.noise)
        for name, circuit in (("A", circuit_a), ("B", circuit_b)):
            if circuit.num_qubits != circuit_a.num_qubits:
                raise ValueError(
                    f"circuit {name} has {circuit.num_qubits} qubits but circuit A has "
                    f"{circuit_a.num_qubits}; comparisons are only meaningful on one register size"
                )
        def run_options_for() -> RunOptions:
            return RunOptions(
                backend=request.backend,
                shots=request.shots,
                noise=noise,
                seed=request.seed,
                compare_ideal=not noise.is_ideal(),
            )

        run_a = run_circuit(circuit_a, run_options_for())
        run_b = run_circuit(circuit_b, run_options_for())

        resources_a, resources_b = circuit_metrics(circuit_a), circuit_metrics(circuit_b)
        resource_keys = ["qubits", "gates", "depth", "two_qubit_gates", "measurements", "parameters", "is_clifford"]
        resource_rows = []
        for key in resource_keys:
            value_a, value_b = resources_a.get(key), resources_b.get(key)
            delta = None
            if isinstance(value_a, (int, float)) and isinstance(value_b, (int, float)):
                delta = value_b - value_a
            resource_rows.append({"metric": key, "a": value_a, "b": value_b, "delta": delta})

        metric_keys = [
            "purity", "entropy", "participation_ratio", "dominant_probability",
            "coherence_l1", "entanglement_status", "max_concurrence",
        ]
        metric_rows = []
        for key in metric_keys:
            value_a, value_b = (run_a.metrics or {}).get(key), (run_b.metrics or {}).get(key)
            delta = value_b - value_a if isinstance(value_a, (int, float)) and isinstance(value_b, (int, float)) else None
            metric_rows.append({"metric": key, "a": value_a, "b": value_b, "delta": delta})

        from qscope.analysis.fidelity import total_variation

        share = set(run_a.ideal_probabilities) | set(run_b.ideal_probabilities)
        distribution_a = {k: run_a.ideal_probabilities.get(k, 0.0) for k in share}
        distribution_b = {k: run_b.ideal_probabilities.get(k, 0.0) for k in share}
        distance = total_variation(distribution_a, distribution_b) if share else 0.0

        verdict: list[str] = []
        gates_saved = resources_a["gates"] - resources_b["gates"]
        depth_saved = resources_a["depth"] - resources_b["depth"]
        if gates_saved:
            verdict.append(f"B uses {abs(gates_saved)} {'fewer' if gates_saved > 0 else 'more'} gates than A.")
        if depth_saved:
            verdict.append(f"B is {abs(depth_saved)} layers {'shallower' if depth_saved > 0 else 'deeper'} than A.")
        if distance <= 0.02:
            verdict.append(f"The output distributions agree to within total variation {distance:.4f}.")
        elif distance >= 0.2:
            verdict.append(f"The output distributions differ substantially (total variation {distance:.4f}).")
        else:
            verdict.append(f"The output distributions differ moderately (total variation {distance:.4f}).")
        if run_a.mode != run_b.mode:
            verdict.append(
                f"The runs are not the same kind of result: A is {mode_label(run_a.mode)} and B is {mode_label(run_b.mode)}."
            )

        comparison = {
            "circuit_a": {"name": circuit_a.name, "num_qubits": circuit_a.num_qubits, "num_clbits": circuit_a.num_clbits, "resources": resources_a},
            "circuit_b": {"name": circuit_b.name, "num_qubits": circuit_b.num_qubits, "num_clbits": circuit_b.num_clbits, "resources": resources_b},
            "resource_rows": resource_rows,
            "metric_rows": metric_rows,
            "a": run_a.to_dict(include_state=False),
            "b": run_b.to_dict(include_state=False),
            "output_total_variation": distance,
            "verdict": verdict,
            "shots": request.shots,
            "seed": request.seed,
            "noise": noise.to_dict(),
            "mode_a": run_a.mode,
            "mode_b": run_b.mode,
            "diagram_a": circuit_a.diagram(),
            "diagram_b": circuit_b.diagram(),
            "limitations": [
                "Both sides were sampled with the same seed and shot count; equal circuits can still differ by ~1/sqrt(shots).",
                "A cheap-looking circuit is not automatically better: better is defined against the task, which this endpoint does not know.",
            ],
        }
        return comparison

    # --------------------------------------------------------------- what-if

    @app.post("/api/whatif")
    def whatif(request: WhatIfRequest) -> dict[str, Any]:
        circuit = resolve_circuit(request.source)
        noise = resolve_noise(request.noise)
        result = what_if(
            circuit,
            request.modification,
            shots=request.shots,
            seed=request.seed,
            backend=request.backend,
            noise=noise,
            store=store_singleton() if request.store else None,
        )
        payload = result.to_dict()
        payload["headline"] = result.headline()
        payload["catalog"] = what_if_catalog()
        return payload

    # -------------------------------------------------------------- hardware

    @app.post("/api/hardware")
    def hardware(request: HardwareRequest) -> dict[str, Any]:
        circuit = resolve_circuit(request.source)
        if request.device == "custom":
            if not request.model:
                raise ValueError("device='custom' requires a 'model' with the device description")
            device = custom_hardware(request.model)
        else:
            device = HARDWARE_PRESETS.get(request.device)
            if device is None:
                raise KeyError(f"unknown device {request.device!r}; available: {sorted(HARDWARE_PRESETS)}")
        report = hardware_report(circuit, device, route=request.route)
        report["circuit"] = circuit_document(circuit, include_qasm=False, include_diagram=False)
        report["devices"] = preset_catalog()
        return report

    # -------------------------------------------------------------- evolution

    @app.post("/api/evolve")
    def evolve(request: EvolutionRequest) -> dict[str, Any]:
        circuit = resolve_circuit(request.source)
        device = HARDWARE_PRESETS.get(request.hardware) if request.hardware else None
        if request.hardware and device is None:
            raise KeyError(f"unknown device {request.hardware!r}; available: {sorted(HARDWARE_PRESETS)}")
        if request.target == "unitary":
            result = evolve_circuit(
                target_unitary=circuit.to_unitary(),
                hardware=device,
                generations=request.generations,
                population_size=request.population,
                seed=request.seed,
            )
        else:
            result = evolve_circuit(
                circuit,
                hardware=device,
                generations=request.generations,
                population_size=request.population,
                seed=request.seed,
            )
        payload = result.to_dict(include_circuits=True)
        payload["headline"] = result.headline()
        payload["reference"] = circuit_document(circuit, include_qasm=False, include_diagram=False)
        return payload

    # ------------------------------------------------------------ experiments

    def spec_from(request: ExperimentRequest) -> ExperimentSpec:
        """Turn an API experiment request into a reproducible spec."""
        noise = resolve_noise(request.noise)
        algorithm = request.algorithm or request.fixed.get("algorithm") or "grover"
        axes, fixed = request.axes, dict(request.fixed)
        qubits = [int(v) for v in axes.get("num_qubits", [])] or None
        level = request.optimizer_level or fixed.pop("optimizer_level", None)
        # A factory only receives a size if the algorithm actually takes one: bell_state
        # is always two qubits, and injecting num_qubits there would silently skip every
        # point of the sweep.
        sized = algorithm_accepts(algorithm, "num_qubits")
        if request.kind == "algorithm_scaling":
            if not sized:
                raise ValueError(
                    f"{algorithm} has no size parameter, so there is nothing to scale; "
                    "pick an algorithm that takes num_qubits (ghz_state, grover, qft, …) or "
                    "use the shots_convergence kind instead"
                )
            spec = algorithm_scaling(
                algorithm,
                qubits or (2, 3, 4, 5, 6),
                shots=request.shots,
                noise=noise,
                backend=request.backend,
                seed=request.seed,
                optimizer_level=level,
                hardware=fixed.pop("hardware", None),
            )
        elif request.kind == "noise_sweep":
            spec = noise_sweep(
                algorithm,
                strengths=[float(v) for v in axes.get("noise", (0.0, 0.01, 0.02, 0.05, 0.1, 0.2))],
                base_noise=noise,
                num_qubits=int(axes.get("num_qubits", [fixed.pop("num_qubits", 4)])[0]),
                shots=request.shots,
                seed=request.seed,
            )
        elif request.kind == "backend_comparison":
            spec = backend_comparison(
                algorithm,
                num_qubits=int(axes.get("num_qubits", [fixed.pop("num_qubits", 3)])[0]),
                shots=request.shots,
                noise=noise,
                seed=request.seed,
            )
        elif request.kind == "optimizer_comparison":
            spec = optimizer_comparison(
                algorithm,
                levels=axes.get("level", ("safe", "standard", "aggressive")),
                num_qubits=int(axes.get("num_qubits", [fixed.pop("num_qubits", 4)])[0]),
                shots=request.shots,
                seed=request.seed,
            )
        elif request.kind == "shots_convergence":
            spec = shots_convergence(
                algorithm,
                shots_values=[int(v) for v in axes.get("shots", (64, 256, 1024, 4096, 16384))],
                num_qubits=int(axes.get("num_qubits", [fixed.pop("num_qubits", 4)])[0]),
                noise=noise,
                seed=request.seed,
            )
        elif request.kind == "parameter_sweep":
            axis = next(iter(axes), "gamma")
            spec = parameter_sweep(
                algorithm,
                axis=axis,
                values=[float(v) for v in axes[axis]],
                fixed=fixed,
                shots=request.shots,
                seed=request.seed,
            )
        else:
            if not axes:
                raise ValueError("a custom experiment needs at least one sweep axis in 'axes'")
            spec = custom_experiment(
                request.name or request.key or "custom experiment",
                [SweepAxis(name, values, name) for name, values in axes.items()],
                algorithm=algorithm if "algorithm" in fixed or request.algorithm else None,
                fixed=fixed,
                shots=request.shots,
                backend=request.backend,
                noise=noise,
                seed=request.seed,
                tags=[request.kind],
            )
        spec.shots = request.shots
        spec.seed = request.seed
        spec.max_combinations = request.max_combinations
        spec.store = request.store
        spec.notes.extend(request.notes)
        if level:
            spec.optimizer_level = level
        return spec

    @app.post("/api/experiments/run")
    def experiments_run(request: ExperimentRequest) -> dict[str, Any]:
        spec = spec_from(request)
        outcome = run_experiment(spec, store=store_singleton() if request.store else None)
        if not outcome.rows:
            # An experiment that measured nothing must not look like a success.
            raise HTTPException(
                status_code=422,
                detail={
                    "error": "empty-experiment",
                    "detail": "; ".join(outcome.warnings) or "every parameter point was skipped",
                    "hint": "Check that the algorithm accepts the axes and fixed parameters you sent.",
                },
            )
        payload = outcome.to_dict(include_circuits=False)
        payload["headline"] = outcome.headline()
        payload["spec"] = spec.to_dict()
        payload["plan_note"] = (
            "Every row is a simulation on this machine; the run was recorded with its seed and shot "
            "count so it can be reproduced exactly."
            if request.store
            else "store=false: this experiment was not written to the history database."
        )
        return payload

    # -------------------------------------------------------------- benchmark

    @app.post("/api/benchmark")
    def benchmark(request: BenchmarkRequest) -> dict[str, Any]:
        qubits = [int(q) for q in request.qubits]
        if request.kind == "scaling":
            payload = benchmark_scaling(qubits=qubits, shots=request.shots, trials=request.trials)
        elif request.kind == "backends":
            payload = benchmark_backends(qubits=qubits, shots=request.shots, trials=request.trials)
        elif request.kind == "throughput":
            payload = benchmark_gate_throughput(
                num_qubits=qubits[-1] if qubits else 16, repetitions=request.depth, trials=request.trials
            )
        elif request.kind == "memory":
            payload = memory_observatory(qubits=qubits or (10, 15, 20, 24, 26, 28, 30))
        elif request.kind == "external":
            payload = compare_with_external(
                compute_circuit(qubits[0] if qubits else 8, request.depth, request.seed),
                shots=request.shots,
                trials=request.trials,
            )
        else:
            payload = benchmark_suite(
                qubits=qubits or (6, 8, 10),
                scaling_qubits=qubits or (8, 10, 12, 14, 16),
                shots=request.shots,
                trials=request.trials,
            )
        payload = dict(payload) if isinstance(payload, dict) else {"kind": f"benchmark_{request.kind}", "rows": payload}
        payload["request"] = request.model_dump()
        payload["mode"] = MODE_IDEAL
        payload["mode_label"] = mode_label(MODE_IDEAL)
        payload["disclaimer"] = (
            "These are wall-clock measurements of a NumPy state-vector engine on this machine. "
            "They say nothing about quantum hardware speed, and no quantum advantage is claimed."
        )
        return payload

    # ------------------------------------------------------------- reporting

    def build_report(request: ReportRequest) -> Any:
        """Generate a report by re-running the operation the payload describes."""
        payload = request.payload
        kind = request.kind
        if kind == "simulation":
            sim = SimulateRequest.model_validate(payload)
            circuit = resolve_circuit(sim.source)
            result = run_circuit(circuit, run_options(sim, resolve_noise(sim.noise)))
            return report_from_result(result, circuit, title=request.title, objective=request.objective)
        if kind == "optimization":
            opt = OptimizeRequest.model_validate(payload)
            circuit = resolve_circuit(opt.source)
            optimization = optimise(circuit, level=opt.level, verify=opt.verify)
            report = report_from_optimization(optimization, title=request.title)
            if request.objective:
                report.objective = request.objective
            return report
        if kind == "trace":
            trc = TraceRequest.model_validate(payload)
            circuit = resolve_circuit(trc.source)
            traced = trace_circuit(circuit, depth=trc.depth, term_limit=trc.term_limit, max_steps=trc.max_steps)
            report = report_from_trace(traced, title=request.title)
            if request.objective:
                report.objective = request.objective
            return report
        if kind == "comparison":
            cmp_req = CompareRequest.model_validate(payload)
            comparison = compare(cmp_req)
            report = report_from_comparison(comparison, title=request.title)
            if request.objective:
                report.objective = request.objective
            return report
        if kind == "experiment":
            exp = ExperimentRequest.model_validate(payload)
            outcome = run_experiment(spec_from(exp), store=store_singleton() if exp.store else None)
            report = report_from_experiment(outcome, title=request.title)
            if request.objective:
                report.objective = request.objective
            return report
        if kind == "evolution":
            evo = EvolutionRequest.model_validate(payload)
            circuit = resolve_circuit(evo.source)
            device = HARDWARE_PRESETS.get(evo.hardware) if evo.hardware else None
            evolution = (
                evolve_circuit(
                    target_unitary=circuit.to_unitary(),
                    hardware=device,
                    generations=evo.generations,
                    population_size=evo.population,
                    seed=evo.seed,
                )
                if evo.target == "unitary"
                else evolve_circuit(
                    circuit,
                    hardware=device,
                    generations=evo.generations,
                    population_size=evo.population,
                    seed=evo.seed,
                )
            )
            report = report_from_evolution(evolution, title=request.title)
            if request.objective:
                report.objective = request.objective
            return report
        if kind == "hardware":
            hw = HardwareRequest.model_validate(payload)
            circuit = resolve_circuit(hw.source)
            device = custom_hardware(hw.model or {}) if hw.device == "custom" else HARDWARE_PRESETS[hw.device]
            payload_report = hardware_report(circuit, device, route=hw.route)
            payload_report["circuit"] = circuit_document(circuit, include_qasm=False, include_diagram=False)
            report = report_from_hardware(payload_report, title=request.title)
            if request.objective:
                report.objective = request.objective
            return report
        raise ValueError(f"unknown report kind {kind!r}")

    @app.post("/api/report")
    def report(request: ReportRequest) -> dict[str, Any]:
        built = build_report(request)
        payload: dict[str, Any] = {"report": built.to_dict()}
        payload["markdown"] = built.to_markdown()
        payload["html"] = built.to_html()
        if request.save:
            payload["files"] = built.save(REPORTS_DIR)
            payload["dir"] = str(REPORTS_DIR)
        return payload

    @app.post("/api/report/export")
    def report_export(request: ReportRequest, format: str = Query("html")) -> Response:
        """Render the same report to a downloadable artifact."""
        built = build_report(request)
        slug = request.title or built.title
        if format == "pdf":
            return Response(
                content=built.to_pdf(),
                media_type="application/pdf",
                headers={"Content-Disposition": f'attachment; filename="{safe_filename(slug)}.pdf"'},
            )
        if format == "json":
            return Response(content=built.to_json(), media_type="application/json")
        if format == "csv":
            return Response(content=built.to_csv(), media_type="text/csv")
        if format == "markdown":
            return PlainTextResponse(built.to_markdown())
        return HTMLResponse(built.to_html())

    @app.get("/api/reports")
    def list_reports() -> dict[str, Any]:
        if not REPORTS_DIR.exists():
            return {"dir": str(REPORTS_DIR), "files": []}
        files = sorted(
            (
                {
                    "name": path.name,
                    "bytes": path.stat().st_size,
                    "modified": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(path.stat().st_mtime)),
                    "format": path.suffix.lstrip("."),
                }
                for path in REPORTS_DIR.iterdir()
                if path.is_file()
            ),
            key=lambda f: f["modified"],
            reverse=True,
        )
        return {"dir": str(REPORTS_DIR), "files": files}

    @app.get("/api/reports/{name}")
    def get_report(name: str) -> FileResponse:
        if "/" in name or "\\" in name or name.startswith("."):
            raise HTTPException(status_code=400, detail={"error": "bad-name", "detail": name, "hint": ""})
        path = REPORTS_DIR / name
        if not path.is_file():
            raise HTTPException(status_code=404, detail={"error": "not-found", "detail": name, "hint": ""})
        return FileResponse(path)

    # ------------------------------------------------------------------- AI

    def context_from(request: AIRequest) -> ResearchContext:
        context = ResearchContext()
        if request.simulate is not None:
            circuit = resolve_circuit(request.simulate.source)
            context.circuit = circuit
            context.result = run_circuit(circuit, run_options(request.simulate, resolve_noise(request.simulate.noise)))
        elif request.source is not None:
            context.circuit = resolve_circuit(request.source)
        if request.trace is not None:
            traced_circuit = resolve_circuit(request.trace.source)
            context.trace = trace_circuit(
                traced_circuit, depth=request.trace.depth, term_limit=request.trace.term_limit, max_steps=request.trace.max_steps
            )
        if request.optimize is not None:
            opt_circuit = resolve_circuit(request.optimize.source)
            context.optimization = optimise(opt_circuit, level=request.optimize.level, verify=request.optimize.verify)
        if request.hardware is not None:
            circuit = resolve_circuit(request.hardware.source)
            device = (
                custom_hardware(request.hardware.model or {})
                if request.hardware.device == "custom"
                else HARDWARE_PRESETS[request.hardware.device]
            )
            context.hardware_report = hardware_report(circuit, device, route=request.hardware.route)
        if request.experiment_ids:
            store = store_singleton()
            context.stored = [e for e in (store.get(i) for i in request.experiment_ids) if e is not None]
            if not context.stored:
                context.notes.append("none of the requested experiment ids exist in the history database")
        return context

    @app.post("/api/ai/ask")
    def ai_question(request: AIRequest) -> dict[str, Any]:
        context = context_from(request)
        answer = ai_ask(request.question, context, use_llm=request.use_llm)
        payload = answer.to_dict()
        payload["sources_available"] = context.available_sources()
        payload["llm_configured"] = bool(os.environ.get("QSCOPE_LLM_BASE_URL"))
        payload["grounding"] = (
            "Every number in this answer was read from the objects above; the assistant holds no "
            "independent knowledge of your circuit."
        )
        return payload

    @app.get("/api/ai/suggestions")
    def ai_suggestions() -> dict[str, Any]:
        return {
            "questions": suggested_questions(),
            "llm_configured": bool(os.environ.get("QSCOPE_LLM_BASE_URL")),
            "offline_note": (
                "The assistant works fully offline on your own data. An OpenAI-compatible endpoint can "
                "optionally rewrite an answer in prose; it can never introduce a number."
            ),
        }

    # -------------------------------------------------------------- history

    @app.get("/api/history")
    def history_list(
        limit: int = Query(50, ge=1, le=500),
        offset: int = Query(0, ge=0),
        algorithm: str | None = None,
        tag: str | None = None,
        search: str | None = None,
        order_by: str = "created_at",
        descending: bool = True,
    ) -> dict[str, Any]:
        store = store_singleton()
        rows = store.list(
            limit=limit, offset=offset, algorithm=algorithm, tag=tag, search=search,
            order_by=order_by, descending=descending,
        )
        return {
            "total": store.count(),
            "experiments": [e.to_dict(include_circuit=False) for e in rows],
            "tags": store.tags()[:40],
            "stats": store.stats(),
        }

    # NOTE: the literal /api/history/* routes must be declared before the
    # /api/history/{experiment_id} route, or Starlette matches "export" as an id.
    @app.post("/api/history/compare")
    def history_compare(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
        ids = payload.get("ids") or []
        if not isinstance(ids, list) or len(ids) < 2:
            raise ValueError(f"body must be {{\"ids\": [...]}} with at least two experiment ids; got {len(ids)}")
        return store_singleton().compare([str(i) for i in ids])

    @app.get("/api/history/export")
    def history_export(format: str = Query("json"), ids: str | None = None) -> Response:
        selected = [i for i in (ids or "").split(",") if i] or None
        store = store_singleton()
        if format == "csv":
            return Response(
                content=store.export_csv(selected),
                media_type="text/csv",
                headers={"Content-Disposition": 'attachment; filename="qscope-history.csv"'},
            )
        return Response(
            content=store.export_json(selected),
            media_type="application/json",
            headers={"Content-Disposition": 'attachment; filename="qscope-history.json"'},
        )

    @app.get("/api/history/{experiment_id}")
    def history_get(experiment_id: str, include_circuit: bool = True) -> dict[str, Any]:
        stored = store_singleton().get(experiment_id)
        if stored is None:
            raise HTTPException(
                status_code=404,
                detail={"error": "not-found", "detail": experiment_id, "hint": "GET /api/history to list ids"},
            )
        payload = stored.to_dict(include_circuit=include_circuit)
        payload["reproducibility"] = stored.reproducibility()
        return payload

    @app.delete("/api/history/{experiment_id}")
    def history_delete(experiment_id: str) -> dict[str, Any]:
        return {"deleted": store_singleton().delete(experiment_id), "experiment_id": experiment_id}

    @app.get("/api/history/reproduce/{experiment_id}")
    def history_reproduce(experiment_id: str) -> dict[str, Any]:
        """Re-run a stored experiment from its own record, and compare."""
        store = store_singleton()
        stored = store.get(experiment_id)
        if stored is None:
            raise HTTPException(
                status_code=404,
                detail={"error": "not-found", "detail": experiment_id, "hint": "GET /api/history to list ids"},
            )
        circuit = Circuit.from_dict(stored.circuit)
        result = run_circuit(
            circuit,
            RunOptions(
                backend=stored.backend,
                shots=stored.shots,
                noise=NoiseModel.from_dict(stored.noise_json),
                seed=stored.seed,
                compare_ideal=False,
            ),
        )
        from qscope.analysis.fidelity import total_variation

        keys = set(result.counts) | set(stored.counts)
        shots = max(stored.shots, 1)
        stored_distribution = {k: stored.counts.get(k, 0) / shots for k in keys}
        rerun_distribution = {k: result.counts.get(k, 0) / shots for k in keys}
        return {
            "experiment_id": experiment_id,
            "original": {
                "counts": stored.counts,
                "metrics": stored.metrics,
                "backend": stored.backend,
                "mode": stored.mode,
                "runtime_seconds": stored.runtime_seconds,
                "created_at": stored.created_at,
            },
            "rerun": {
                "counts": result.counts,
                "metrics": result.metrics,
                "backend": result.backend,
                "mode": result.mode,
                "runtime_seconds": result.timing.get("total_seconds"),
            },
            "distribution_distance": total_variation(stored_distribution, rerun_distribution),
            "expected_shot_noise": 1.0 / float(np.sqrt(shots)),
            "verdict": (
                "The rerun reproduces the stored distribution to within shot noise."
                if total_variation(stored_distribution, rerun_distribution) <= 3.0 / np.sqrt(shots) + 0.01
                else "The rerun differs from the stored distribution by more than shot noise allows; the "
                "record and this environment disagree."
            ),
            "note": (
                "Reproduction re-executes the stored circuit with the stored seed, shots, backend and noise "
                "model. The stored seed makes the rerun bit-for-bit repeatable on one engine version."
            ),
        }

    # ------------------------------------------------------------ streaming

    @app.websocket("/ws/trace")
    async def ws_trace(websocket: WebSocket) -> None:
        """Stream a gate-by-gate trace as it is computed (the live debugger)."""
        await websocket.accept()
        try:
            while True:
                message = await websocket.receive_json()
                try:
                    request = TraceRequest.model_validate(message)
                    circuit = resolve_circuit(request.source)
                except Exception as exc:
                    await websocket.send_json(
                        {"type": "error", "error": type(exc).__name__, "detail": str(exc)}
                    )
                    continue
                delay = float(message.get("delay_ms", 0) or 0) / 1000.0
                delay = min(max(delay, 0.0), 2.0)
                steps = iter_trace(
                    circuit,
                    depth=request.depth,
                    term_limit=request.term_limit,
                    max_steps=request.max_steps,
                    analyze_last_only=request.analyze_last_only,
                )
                await websocket.send_json(
                    {
                        "type": "start",
                        "circuit": circuit_document(circuit, include_qasm=False, include_diagram=False),
                        "diagram": circuit.diagram(),
                        "total_steps": len(circuit.operations),
                    }
                )
                try:
                    while True:
                        step = await asyncio.to_thread(_next_step, steps)
                        if step is _DONE:
                            break
                        await websocket.send_json({"type": "step", "step": step.to_dict()})
                        if delay:
                            await asyncio.sleep(delay)
                except Exception as exc:  # the trace itself failed part-way
                    await websocket.send_json(
                        {"type": "error", "error": type(exc).__name__, "detail": str(exc)}
                    )
                    continue
                await websocket.send_json({"type": "done", "steps_sent": len(circuit.operations)})
        except WebSocketDisconnect:
            return
        except Exception:  # pragma: no cover - transport-level failure
            return

    @app.websocket("/ws/experiment")
    async def ws_experiment(websocket: WebSocket) -> None:
        """Run an experiment and stream one message per parameter point."""
        await websocket.accept()
        try:
            while True:
                message = await websocket.receive_json()
                try:
                    request = ExperimentRequest.model_validate(message)
                    spec = spec_from(request)
                except Exception as exc:
                    await websocket.send_json(
                        {"type": "error", "error": type(exc).__name__, "detail": str(exc)}
                    )
                    continue
                loop = asyncio.get_running_loop()
                queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

                def progress(index: int, total: int, label: str) -> None:
                    loop.call_soon_threadsafe(
                        queue.put_nowait, {"type": "progress", "index": index, "total": total, "label": label}
                    )

                def worker() -> dict[str, Any]:
                    outcome = run_experiment(
                        spec, store=store_singleton() if request.store else None, progress=progress
                    )
                    return outcome.to_dict(include_circuits=False)

                await websocket.send_json({"type": "start", "spec": spec.to_dict(), "total": len(spec.combinations())})
                task = asyncio.create_task(asyncio.to_thread(worker))
                while not task.done():
                    try:
                        event = await asyncio.wait_for(queue.get(), timeout=0.25)
                        await websocket.send_json(event)
                    except asyncio.TimeoutError:
                        continue
                while not queue.empty():
                    await websocket.send_json(queue.get_nowait())
                try:
                    outcome = await task
                except Exception as exc:
                    await websocket.send_json(
                        {"type": "error", "error": type(exc).__name__, "detail": str(exc)}
                    )
                    continue
                await websocket.send_json({
                    "type": "done",
                    "outcome": outcome,
                    "headline": str(outcome.get("headline", "")) if isinstance(outcome, dict) else "",
                })
        except WebSocketDisconnect:
            return
        except Exception:  # pragma: no cover - transport-level failure
            return

    # ----------------------------------------------------------- static SPA

    assets = FRONTEND_DIST / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/", include_in_schema=False)
    def index() -> Response:
        page = FRONTEND_DIST / "index.html"
        if page.is_file():
            return FileResponse(page)
        return HTMLResponse(_PLACEHOLDER_PAGE)

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> Response:
        if path.startswith(("api/", "ws/")):
            return JSONResponse(
                status_code=404, content={"error": "not-found", "detail": f"/{path}", "hint": "See /api/meta"}
            )
        candidate = FRONTEND_DIST / path
        if candidate.is_file() and FRONTEND_DIST in candidate.resolve().parents:
            return FileResponse(candidate)
        page = FRONTEND_DIST / "index.html"
        if page.is_file():
            return FileResponse(page)
        return HTMLResponse(_PLACEHOLDER_PAGE)

    return app


_DONE = object()


def _next_step(generator: Iterator[Any]) -> Any:
    try:
        return next(generator)
    except StopIteration:
        return _DONE


_PLACEHOLDER_PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>QScope</title>
<style>
 body{background:#08090c;color:#e6e8ee;font:15px/1.6 ui-sans-serif,system-ui,sans-serif;margin:0;padding:56px}
 code{background:#141720;padding:2px 6px;border-radius:4px;color:#7ee0c8}
 a{color:#8ab4ff} h1{font-weight:600;letter-spacing:-0.02em}
</style></head><body>
<h1>QScope API is running</h1>
<p>The compiled interface was not found, so this placeholder is being served. Every endpoint below works.</p>
<ul>
 <li><a href="/api/docs">/api/docs</a> — interactive API reference</li>
 <li><a href="/api/health">/api/health</a> — environment and database status</li>
 <li><a href="/api/meta">/api/meta</a> — algorithms, devices, engines, noise models, experiments</li>
</ul>
<p>Build the interface with <code>cd frontend &amp;&amp; npm install &amp;&amp; npm run build</code>, then reload this page.</p>
</body></html>"""


app = create_app()


__all__ = ["app", "create_app", "resolve_circuit", "resolve_noise", "circuit_document", "REPORTS_DIR"]
