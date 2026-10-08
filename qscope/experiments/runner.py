"""The experiment laboratory.

An experiment is a *sweep*: one or more parameters, a list of values for each, and
a pipeline that builds a circuit, runs it, measures everything, and stores the
result.  The output is chart-ready and reproducibility-complete: for every row you
get the parameters, the circuit cost, the runtime and memory actually observed,
the success probability, the metrics, and — where theory exists — what the
analytic answer should have been.

Supported kinds
---------------
``algorithm_scaling``   algorithm vs system size (qubit count)
``noise_sweep``         one circuit under increasing noise
``backend_comparison``  the same circuit on every engine
``optimizer_comparison`` original vs optimized, with verification
``shots_convergence``   sampled vs exact distribution as shots grow
``parameter_sweep``     variational parameters (VQE / QAOA energy)
``custom``              cartesian product of user-defined axes
"""

from __future__ import annotations

import inspect
import itertools
import math
import time
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Callable, Sequence

import numpy as np

from qscope.analysis.fidelity import total_variation
from qscope.analysis.metrics import circuit_metrics, state_metrics
from qscope.algorithms.library import (
    ALGORITHMS,
    AlgorithmSpec,
    build_algorithm,
    evaluate_maxcut_counts,
    expectation_value,
    grover_success_probability,
    ising_hamiltonian,
)
from qscope.circuit.circuit import Circuit
from qscope.optimizer.optimizer import optimise
from qscope.simulator.execution import RunOptions, describe_bytes, plan_execution
from qscope.simulator.noise import NoiseModel
from qscope.simulator.simulator import SimulationResult, run_circuit

EXPERIMENT_KINDS = (
    "algorithm_scaling",
    "noise_sweep",
    "backend_comparison",
    "optimizer_comparison",
    "shots_convergence",
    "parameter_sweep",
    "custom",
)


@dataclass
class SweepAxis:
    """One swept parameter."""

    name: str
    values: list[Any]
    label: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "values": list(self.values), "label": self.label or self.name}


@dataclass
class ExperimentSpec:
    """A fully described, reproducible experiment."""

    key: str
    name: str
    kind: str = "custom"
    description: str = ""
    algorithm: str | None = None
    axes: list[SweepAxis] = field(default_factory=list)
    fixed: dict[str, Any] = field(default_factory=dict)
    shots: int = 2048
    backend: str = "auto"
    noise: NoiseModel = field(default_factory=NoiseModel.ideal)
    noise_axis_values: list[float] | None = None
    seed: int = 12345
    optimizer_level: str | None = None
    tags: list[str] = field(default_factory=list)
    store: bool = True
    notes: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    max_combinations: int = 64

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "name": self.name,
            "kind": self.kind,
            "description": self.description,
            "algorithm": self.algorithm,
            "axes": [a.to_dict() for a in self.axes],
            "fixed": dict(self.fixed),
            "shots": self.shots,
            "backend": self.backend,
            "noise": self.noise.to_dict(),
            "noise_axis_values": self.noise_axis_values,
            "seed": self.seed,
            "optimizer_level": self.optimizer_level,
            "tags": list(self.tags),
            "store": self.store,
            "notes": list(self.notes),
            "metadata": dict(self.metadata),
        }

    def combinations(self) -> list[dict[str, Any]]:
        """All parameter combinations (cartesian product of the axes)."""
        if not self.axes:
            return [dict(self.fixed)]
        names = [a.name for a in self.axes]
        combos: list[dict[str, Any]] = []
        for values in itertools.product(*[a.values for a in self.axes]):
            params = dict(self.fixed)
            params.update(dict(zip(names, values)))
            combos.append(params)
            if len(combos) >= self.max_combinations:
                break
        return combos


@dataclass
class ExperimentRow:
    """One parameter point, fully measured."""

    index: int
    params: dict[str, Any]
    label: str
    qubits: int
    gates: int
    depth: int
    two_qubit_gates: int
    runtime_seconds: float
    memory_mb: float
    backend: str
    mode: str
    success_probability: float | None
    success_definition: str
    top_outcome: str | None
    top_count: int | None
    counts: dict[str, int]
    ideal_probabilities: dict[str, float]
    sampled_probabilities: dict[str, float]
    distribution_distance: float
    fidelity_vs_ideal: float | None
    purity: float | None
    entropy: float | None
    entanglement_status: str | None
    max_concurrence: float | None
    analytic_success: float | None = None
    analytic_deviation: float | None = None
    estimated_error_budget: float | None = None
    observation: str = ""
    extra: dict[str, Any] = field(default_factory=dict)
    circuit: dict[str, Any] | None = None
    experiment_id: str | None = None

    def to_dict(self, include_circuit: bool = False) -> dict[str, Any]:
        out = {
            "index": self.index,
            "params": self.params,
            "label": self.label,
            "qubits": self.qubits,
            "gates": self.gates,
            "depth": self.depth,
            "two_qubit_gates": self.two_qubit_gates,
            "runtime_seconds": self.runtime_seconds,
            "memory_mb": self.memory_mb,
            "backend": self.backend,
            "mode": self.mode,
            "success_probability": self.success_probability,
            "success_definition": self.success_definition,
            "top_outcome": self.top_outcome,
            "top_count": self.top_count,
            "counts": self.counts,
            "ideal_probabilities": self.ideal_probabilities,
            "sampled_probabilities": self.sampled_probabilities,
            "distribution_distance": self.distribution_distance,
            "fidelity_vs_ideal": self.fidelity_vs_ideal,
            "purity": self.purity,
            "entropy": self.entropy,
            "entanglement_status": self.entanglement_status,
            "max_concurrence": self.max_concurrence,
            "analytic_success": self.analytic_success,
            "analytic_deviation": self.analytic_deviation,
            "estimated_error_budget": self.estimated_error_budget,
            "observation": self.observation,
            "extra": self.extra,
            "experiment_id": self.experiment_id,
        }
        if include_circuit:
            out["circuit"] = self.circuit
        return out


@dataclass
class ExperimentOutcome:
    """Everything an experiment produced, including chart series."""

    spec: dict[str, Any]
    rows: list[ExperimentRow]
    series: dict[str, Any]
    aggregates: dict[str, Any]
    observations: list[str]
    warnings: list[str]
    seconds: float
    started_at: str
    finished_at: str
    experiment_ids: list[str] = field(default_factory=list)

    def to_dict(self, include_circuits: bool = False) -> dict[str, Any]:
        return {
            "spec": self.spec,
            "rows": [r.to_dict(include_circuit=include_circuits) for r in self.rows],
            "series": self.series,
            "aggregates": self.aggregates,
            "observations": self.observations,
            "warnings": self.warnings,
            "seconds": self.seconds,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "experiment_ids": self.experiment_ids,
        }

    def headline(self) -> str:
        if not self.rows:
            return "experiment produced no rows"
        first, last = self.rows[0], self.rows[-1]
        parts = [f"{len(self.rows)} runs"]
        if first.runtime_seconds and last.runtime_seconds:
            ratio = last.runtime_seconds / first.runtime_seconds if first.runtime_seconds else 0
            parts.append(f"runtime {ratio:.1f}x from first to last point")
        if first.success_probability is not None and last.success_probability is not None:
            parts.append(
                f"success {first.success_probability:.3f} → {last.success_probability:.3f}"
            )
        return "; ".join(parts)


# ---------------------------------------------------------------------------
# circuit construction
# ---------------------------------------------------------------------------


@lru_cache(maxsize=None)
def accepted_parameters(key: str) -> frozenset[str]:
    """Keyword parameters an algorithm factory actually accepts.

    A sweep axis like ``num_qubits`` is meaningless for an algorithm that has no
    size (``bell_state`` is always two qubits).  Passing it anyway would raise
    inside the factory and silently skip the point, so unknown keywords are
    dropped here and reported through :func:`unsupported_parameters`.
    """
    factory = ALGORITHMS.get(key)
    if factory is None:
        return frozenset()
    try:
        signature = inspect.signature(factory)
    except (TypeError, ValueError):  # pragma: no cover - builtins
        return frozenset()
    return frozenset(
        name
        for name, parameter in signature.parameters.items()
        if parameter.kind
        in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
    )


def unsupported_parameters(params: dict[str, Any], key: str) -> list[str]:
    """Requested parameters this algorithm cannot use (for warnings and the UI)."""
    accepted = accepted_parameters(key)
    interesting = {
        "num_qubits",
        "layers",
        "iterations",
        "theta",
        "phase",
        "secret",
        "marked",
        "oracle",
        "mask",
        "counting_qubits",
    }
    return sorted(name for name in params if name in interesting and name not in accepted)


def _algorithm_for(params: dict[str, Any], algorithm: str | None) -> AlgorithmSpec:
    """Build the algorithm spec for one parameter point."""
    key = algorithm or str(params.get("algorithm", "grover"))
    args: dict[str, Any] = {}
    for name in ("num_qubits", "layers", "iterations", "theta", "phase", "secret", "marked", "oracle", "mask"):
        if name in params and params[name] is not None:
            args[name] = params[name]
    if key == "qaoa_maxcut":
        layers = int(params.get("layers", 1) or 1)
        gamma = float(params.get("gamma", 0.6))
        beta = float(params.get("beta", 0.6))
        args["layers"] = layers
        args["params"] = [gamma, beta] * layers
    if key == "vqe_ansatz":
        layers = int(params.get("layers", 2) or 2)
        n = int(params.get("num_qubits", 3) or 3)
        n_params = layers * n * 2
        params_list = params.get("vector")
        args["layers"] = layers
        args["params"] = list(params_list) if params_list is not None else [float(params.get("theta", 0.4))] * n_params
    if key == "quantum_phase_estimation":
        args["counting_qubits"] = int(params.get("num_qubits", params.get("counting_qubits", 4)) or 4)
        args.pop("num_qubits", None)
    accepted = accepted_parameters(key)
    if accepted:
        args = {name: value for name, value in args.items() if name in accepted}
    return build_algorithm(key, **args)


def _success(
    counts: dict[str, int],
    ideal: dict[str, float],
    spec: AlgorithmSpec | None,
    params: dict[str, Any],
) -> tuple[float | None, str]:
    """Success probability with an explicit definition of what counts as success."""
    total = sum(counts.values())
    if not total:
        return None, "no shots"
    analytic = (spec.analytic if spec else {}) or {}
    key = spec.key if spec else ""
    if key == "grover":
        marked = str(params.get("marked") or (spec.parameters.get("marked") if spec else "") or "")
        if marked:
            return counts.get(marked, 0) / total, f"P(measured == marked {marked})"
    if key == "bernstein_vazirani":
        secret = str(params.get("secret") or analytic.get("secret", ""))
        return counts.get(secret, 0) / total, f"P(measured == secret {secret})"
    if key == "deutsch_jozsa":
        if params.get("oracle") == "balanced" or analytic.get("oracle") == "balanced":
            zeros = "0" * int((spec.parameters.get("num_qubits") if spec else 0) or 0)
            return 1.0 - counts.get(zeros, 0) / total, "P(measured != 00..0) for a balanced oracle"
        zeros = "0" * int((spec.parameters.get("num_qubits") if spec else 0) or 0)
        return counts.get(zeros, 0) / total, "P(measured == 00..0) for a constant oracle"
    if key in {"bell_state", "ghz_state"}:
        n = spec.circuit.num_qubits if spec else 0
        return (counts.get("0" * n, 0) + counts.get("1" * n, 0)) / total, "P(all-zero) + P(all-one)"
    if key == "quantum_phase_estimation":
        target = (spec.expected_outcome or {}).get("most_likely_bitstring") if spec else None
        if target:
            return counts.get(target, 0) / total, f"P(measured == best estimate {target})"
    if ideal:
        best = max(ideal.items(), key=lambda kv: kv[1])[0]
        return counts.get(best, 0) / total, f"P(measured == ideal dominant outcome {best})"
    return None, "undefined"


def _observation(row: ExperimentRow) -> str:
    """One sentence grounded in the row's own numbers."""
    bits: list[str] = []
    if row.analytic_success is not None and row.success_probability is not None:
        bits.append(
            f"measured {row.success_probability:.4f} vs analytic {row.analytic_success:.4f} "
            f"(Δ={row.analytic_deviation:+.4f})"
        )
    if row.fidelity_vs_ideal is not None:
        bits.append(f"state fidelity {row.fidelity_vs_ideal:.4f}")
    if row.distribution_distance > 0.05:
        bits.append(
            f"sampled distribution differs from the exact one by {row.distribution_distance:.3f} (TV)"
        )
    if row.backend != "statevector" and row.purity is not None and row.purity < 0.999:
        bits.append(f"purity fell to {row.purity:.4f}")
    if row.extra.get("routing_swaps"):
        bits.append(f"{row.extra['routing_swaps']} SWAPs needed for this topology")
    return "; ".join(bits) if bits else "no anomalies"


# ---------------------------------------------------------------------------
# runner
# ---------------------------------------------------------------------------


def run_experiment(
    spec: ExperimentSpec,
    *,
    store: Any | None = None,
    progress: Callable[[int, int, str], None] | None = None,
) -> ExperimentOutcome:
    """Run every parameter point of an experiment and collect the results."""
    started_at = time.strftime("%Y-%m-%dT%H:%M:%S")
    t0 = time.perf_counter()
    rows: list[ExperimentRow] = []
    warnings: list[str] = []
    experiment_ids: list[str] = []
    combos = spec.combinations()

    for index, params in enumerate(combos):
        if progress is not None:
            progress(index, len(combos), str(params))
        row, row_warnings, exp_id = _run_point(spec, params, index, store=store)
        rows.extend([row] if row is not None else [])
        warnings.extend(row_warnings)
        if exp_id:
            experiment_ids.append(exp_id)

    series = _series(rows, spec)
    aggregates = _aggregates(rows)
    observations = [f"{r.label}: {r.observation}" for r in rows if r.observation]
    observations.extend(spec.notes)
    seconds = time.perf_counter() - t0
    return ExperimentOutcome(
        spec=spec.to_dict(),
        rows=rows,
        series=series,
        aggregates=aggregates,
        observations=observations,
        warnings=warnings,
        seconds=seconds,
        started_at=started_at,
        finished_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
        experiment_ids=experiment_ids,
    )


def _run_point(
    spec: ExperimentSpec,
    params: dict[str, Any],
    index: int,
    *,
    store: Any | None,
) -> tuple[ExperimentRow | None, list[str], str | None]:
    warnings: list[str] = []
    algorithm_spec: AlgorithmSpec | None = None
    noise = spec.noise
    optimizer_note = ""
    routing_extra: dict[str, Any] = {}

    if spec.kind == "noise_sweep" and spec.noise_axis_values:
        strength = float(params.get("noise", spec.noise_axis_values[0]))
        noise = _scale_noise(spec.noise, strength)
    key = spec.algorithm or str(params.get("algorithm", "grover"))
    dropped = unsupported_parameters(params, key)
    if dropped:
        warnings.append(
            f"{key} does not take {', '.join(dropped)}; the axis was ignored for this point "
            f"(the algorithm is always {ALGORITHMS[key]().circuit.num_qubits}-qubit)"
            if key in ALGORITHMS
            else f"{key} does not take {', '.join(dropped)}; the axis was ignored"
        )
    try:
        algorithm_spec = _algorithm_for(params, spec.algorithm)
        circuit = algorithm_spec.circuit.copy()
    except Exception as exc:
        return None, [f"skipping {params}: {exc}"], None

    if source := params.get("circuit_source"):
        if source == "optimized":
            level = str(params.get("level", "standard"))
            result = optimise(circuit, level=level)
            circuit = result.optimized
            optimizer_note = f"optimized ({level}): {result.headline()}"
            routing_extra["verification"] = result.verification

    if spec.optimizer_level:
        result = optimise(circuit, level=spec.optimizer_level)
        circuit = result.optimized
        optimizer_note = result.headline()
        routing_extra["optimization_verification"] = result.verification["status"]

    if hardware_key := params.get("hardware"):
        from qscope.hardware.topology import HARDWARE_PRESETS, hardware_report

        hardware = HARDWARE_PRESETS[str(hardware_key)]
        report = hardware_report(circuit, hardware)
        routing_extra["routing_swaps"] = (report.get("routing") or {}).get("swaps_inserted", 0)
        routing_extra["estimated_success"] = report["estimate_before_routing"]["estimated_success_probability"]
        if hardware_key == "linear_5" and circuit.num_qubits > hardware.num_qubits:
            warnings.append(f"{hardware_key} has fewer qubits than the circuit needs")

    run_backend = str(params.get("backend", spec.backend))
    options = RunOptions(
        backend=run_backend,
        shots=int(params.get("shots", spec.shots)),
        noise=noise,
        seed=int(spec.seed),
        algorithm=algorithm_spec.key if algorithm_spec else "",
        optimizer=optimizer_note,
        label=spec.name,
    )
    plan = plan_execution(circuit, options)
    if plan.blocked:
        return None, [f"{params}: {plan.warnings[-1]}"], None

    result: SimulationResult = run_circuit(circuit, options)
    resources = circuit_metrics(circuit)
    success, definition = _success(result.counts, result.ideal_probabilities, algorithm_spec, params)
    analytic_success = None
    if algorithm_spec is not None and algorithm_spec.key == "grover":
        analytic_success = float(
            algorithm_spec.analytic.get("success_probability", grover_success_probability(circuit.num_qubits, 0))
        )

    entropy_metrics = result.metrics.get("entanglement") or {}
    row = ExperimentRow(
        index=index,
        params=params,
        label=_label(spec, params),
        qubits=circuit.num_qubits,
        gates=resources["gates"],
        depth=resources["depth"],
        two_qubit_gates=resources["two_qubit_gates"],
        runtime_seconds=result.timing["total_seconds"],
        memory_mb=result.memory.get("state_mb", 0.0),
        backend=result.backend,
        mode=result.mode,
        success_probability=success,
        success_definition=definition,
        top_outcome=next(iter(result.counts), None),
        top_count=next(iter(result.counts.values()), None),
        counts=result.counts,
        ideal_probabilities=result.ideal_probabilities,
        sampled_probabilities=result.sampled_probabilities,
        distribution_distance=total_variation(result.sampled_probabilities, result.ideal_probabilities),
        fidelity_vs_ideal=result.fidelity_vs_ideal,
        purity=result.metrics.get("purity"),
        entropy=result.metrics.get("entropy"),
        entanglement_status=result.metrics.get("entanglement_status"),
        max_concurrence=(entropy_metrics or {}).get("max_concurrence"),
        analytic_success=analytic_success,
        analytic_deviation=(
            (success - analytic_success) if (success is not None and analytic_success is not None) else None
        ),
        estimated_error_budget=routing_extra.get("estimated_success"),
        extra={
            **routing_extra,
            "plan": result.plan,
            "warnings": result.warnings,
            "notes": result.notes,
            "optimizer": optimizer_note,
            "noise_name": noise.name,
            "noise_strength": params.get("noise"),
        },
    )
    # combinatorial scoring for QAOA
    if algorithm_spec is not None and algorithm_spec.key == "qaoa_maxcut":
        edges = algorithm_spec.parameters.get("edges") or []
        scored = evaluate_maxcut_counts(edges, result.counts)
        row.extra["maxcut"] = {k: v for k, v in scored.items() if k != "rows"}
        row.extra["maxcut_rows"] = scored["rows"][:8]
    if algorithm_spec is not None and algorithm_spec.key == "vqe_ansatz":
        terms = ising_hamiltonian(circuit.num_qubits)
        if isinstance(result._state, object) and hasattr(result._state, "expectation_pauli"):
            energy = expectation_value(result._state, terms)
            row.extra["energy"] = energy
            row.extra["energy_terms"] = [{"pauli": p, "coefficient": c} for p, c in terms]
    row.observation = _observation(row)

    experiment_id = None
    if spec.store and store is not None:
        stored = store.record_result(
            name=f"{spec.name} · {row.label}",
            circuit=circuit,
            result=result,
            tags=list(spec.tags) + [spec.kind],
            optimizer=optimizer_note,
            metadata={"experiment_key": spec.key, "params": params},
        )
        experiment_id = stored.experiment_id
    return row, warnings, experiment_id


def _scale_noise(model: NoiseModel, strength: float) -> NoiseModel:
    """Rebuild a noise model with every parameter scaled to ``strength`` in [0, 1]."""
    from qscope.simulator.noise import NoiseChannel

    strength = max(0.0, min(1.0, float(strength)))
    channels = []
    for channel in model.channels:
        scaled = {}
        for name, value in channel.params.items():
            if name in {"p", "gamma", "lambda"}:
                scaled[name] = strength
            else:
                scaled[name] = value
        channels.append(
            NoiseChannel(
                kind=channel.kind,
                params=scaled,
                scope=channel.scope,
                qubits=channel.qubits,
                after_gates=channel.after_gates,
                label=channel.label,
                approximate=channel.approximate,
            )
        )
    return NoiseModel(
        name=f"{model.name} @ strength {strength:g}",
        channels=channels,
        readout_error=strength * (model.readout_error or 0.02),
        one_qubit_gate_error=0.0,
        two_qubit_gate_error=0.0,
        multi_qubit_gate_error=0.0,
        idle_error=0.0,
        description=f"Scaled noise: every channel probability set to {strength:g}.",
        calibrated=model.calibrated,
    )


def _label(spec: ExperimentSpec, params: dict[str, Any]) -> str:
    parts = [f"{k}={v}" for k, v in params.items() if k not in {"algorithm", "backend", "shots", "vector", "circuit_source", "level", "hardware"}]
    return ", ".join(parts) if parts else spec.name


def _series(rows: Sequence[ExperimentRow], spec: ExperimentSpec) -> dict[str, Any]:
    """Chart-ready series, one entry per numeric metric with its x-axis."""
    if not rows:
        return {"x": [], "x_label": "", "series": []}
    x_name = spec.axes[0].name if spec.axes else "index"
    x_values: list[Any] = []
    for row in rows:
        value = row.params.get(x_name, row.index)
        x_values.append(value)
    metrics = [
        ("success_probability", "Success probability"),
        ("analytic_success", "Analytic prediction"),
        ("fidelity_vs_ideal", "Fidelity vs ideal"),
        ("distribution_distance", "Distribution distance (TV)"),
        ("gate_count", "Gates"),
        ("depth", "Depth"),
        ("two_qubit_gates", "Two-qubit gates"),
        ("runtime_seconds", "Runtime (s)"),
        ("memory_mb", "State memory (MB)"),
        ("purity", "Purity"),
        ("entropy", "Entropy (bits)"),
        ("max_concurrence", "Max concurrence"),
        ("estimated_error_budget", "Estimated success (model)"),
    ]
    series = []
    for key, label in metrics:
        values = []
        for row in rows:
            if key == "estimated_error_budget":
                values.append(row.estimated_error_budget)
                continue
            value = getattr(row, key, None)
            values.append(value)
        if any(v is not None for v in values):
            series.append({"key": key, "label": label, "y": values})
    return {"x": x_values, "x_label": spec.axes[0].label if spec.axes else "run index", "series": series}


def _aggregates(rows: Sequence[ExperimentRow]) -> dict[str, Any]:
    if not rows:
        return {}
    numeric = {
        "success_probability": [r.success_probability for r in rows if r.success_probability is not None],
        "runtime_seconds": [r.runtime_seconds for r in rows],
        "gates": [r.gates for r in rows],
        "depth": [r.depth for r in rows],
        "memory_mb": [r.memory_mb for r in rows],
    }
    summary = {
        key: {
            "min": float(np.min(values)),
            "max": float(np.max(values)),
            "mean": float(np.mean(values)),
        }
        for key, values in numeric.items()
        if values
    }
    best_success = max(rows, key=lambda r: r.success_probability if r.success_probability is not None else -1)
    fastest = min(rows, key=lambda r: r.runtime_seconds)
    largest = max(rows, key=lambda r: r.qubits)
    growth = None
    if len(rows) >= 2:
        first, last = rows[0], rows[-1]
        if first.runtime_seconds > 0:
            qubit_delta = last.qubits - first.qubits
            runtime_ratio = last.runtime_seconds / first.runtime_seconds
            growth = {
                "qubit_delta": qubit_delta,
                "runtime_ratio": runtime_ratio,
                "seconds_per_added_qubit": (
                    (last.runtime_seconds - first.runtime_seconds) / qubit_delta if qubit_delta else None
                ),
                "note": (
                    "Runtime growth across the sweep. Classical simulation cost is expected to scale "
                    "exponentially in the qubit count, so a super-linear trend here is physics, not a bug."
                ),
            }
    return {
        "rows": len(rows),
        "summary": summary,
        "best_success": best_success.to_dict(),
        "fastest": fastest.to_dict(),
        "largest_circuit": largest.to_dict(),
        "growth": growth,
    }


# ---------------------------------------------------------------------------
# spec builders
# ---------------------------------------------------------------------------


def algorithm_scaling(
    algorithm: str = "grover",
    qubits: Sequence[int] = (2, 3, 4, 5, 6),
    *,
    shots: int = 2048,
    noise: NoiseModel | None = None,
    backend: str = "auto",
    seed: int = 12345,
    optimizer_level: str | None = None,
    hardware: str | None = None,
) -> ExperimentSpec:
    """Scaling of one algorithm with system size."""
    if algorithm not in ALGORITHMS:
        raise KeyError(f"unknown algorithm {algorithm!r}")
    fixed: dict[str, Any] = {"algorithm": algorithm}
    if hardware:
        fixed["hardware"] = hardware
    return ExperimentSpec(
        key=f"{algorithm}_scaling",
        name=f"{algorithm} scaling",
        kind="algorithm_scaling",
        description=(
            f"Run {algorithm} for a range of system sizes and record cost, runtime, memory and "
            "success probability at every point."
        ),
        algorithm=algorithm,
        axes=[SweepAxis("num_qubits", list(qubits), "Qubits")],
        fixed=fixed,
        shots=shots,
        backend=backend,
        noise=noise or NoiseModel.ideal(),
        seed=seed,
        optimizer_level=optimizer_level,
        tags=["scaling", algorithm],
        notes=[
            "Success probability is measured against the analytic predictor where one exists "
            "(Grover), so a deviation is visible rather than hidden.",
            "Runtime is wall-clock on this machine for this circuit size, not a hardware claim.",
        ],
    )


def noise_sweep(
    algorithm: str = "grover",
    *,
    strengths: Sequence[float] = (0.0, 0.01, 0.02, 0.05, 0.1, 0.2),
    base_noise: NoiseModel | None = None,
    num_qubits: int = 4,
    shots: int = 4096,
    seed: int = 4242,
) -> ExperimentSpec:
    """How one circuit degrades as noise increases."""
    base = base_noise or NoiseModel.depolarizing(0.05)
    return ExperimentSpec(
        key=f"{algorithm}_noise_sweep",
        name=f"{algorithm} noise sweep",
        kind="noise_sweep",
        description=(
            "Scale every noise channel probability from 0 to 1 and record the resulting fidelity, "
            "purity and success probability at each step."
        ),
        algorithm=algorithm,
        axes=[SweepAxis("noise", list(strengths), "Noise strength")],
        fixed={"algorithm": algorithm, "num_qubits": num_qubits},
        shots=shots,
        noise=base,
        noise_axis_values=list(strengths),
        seed=seed,
        tags=["noise", "fidelity", algorithm],
        notes=[
            "Noise strength scales the probabilities of the configured channels; the channel "
            "structure itself is unchanged.",
            "The density-matrix backend gives exact mixed states; the trajectory backend is sampled "
            "and is labelled as such in each row's backend field.",
        ],
    )


def backend_comparison(
    algorithm: str = "bell_state",
    *,
    num_qubits: int = 3,
    shots: int = 2048,
    noise: NoiseModel | None = None,
    seed: int = 777,
) -> ExperimentSpec:
    """The same circuit on every available engine."""
    return ExperimentSpec(
        key=f"{algorithm}_backends",
        name=f"{algorithm} backend comparison",
        kind="backend_comparison",
        description="Run one circuit on the state-vector, density-matrix and trajectory engines.",
        algorithm=algorithm,
        axes=[SweepAxis("backend", ["statevector", "density_matrix", "trajectory"], "Engine")],
        fixed={"algorithm": algorithm, "num_qubits": num_qubits},
        shots=shots,
        noise=noise or NoiseModel.ideal(),
        seed=seed,
        tags=["benchmark", "engines"],
        notes=[
            "Engines represent different physics: a state vector cannot be mixed, so noise "
            "comparisons across engines are only meaningful for the noisy engines.",
        ],
    )


def optimizer_comparison(
    algorithm: str = "grover",
    *,
    levels: Sequence[str] = ("safe", "standard", "aggressive"),
    num_qubits: int = 4,
    shots: int = 2048,
    seed: int = 99,
) -> ExperimentSpec:
    """Original vs optimized circuits, measured side by side."""
    return ExperimentSpec(
        key=f"{algorithm}_optimizer_comparison",
        name=f"{algorithm} optimization study",
        kind="optimizer_comparison",
        description=(
            "Compare the unoptimized circuit with each optimization level, verifying equivalence "
            "and measuring the effect on cost and fidelity."
        ),
        algorithm=algorithm,
        axes=[
            SweepAxis("circuit_source", ["original", "optimized"], "Circuit"),
            SweepAxis("level", list(levels), "Optimization level"),
        ],
        fixed={"algorithm": algorithm, "num_qubits": num_qubits},
        shots=shots,
        seed=seed,
        tags=["optimization", "verification"],
        notes=[
            "Every optimized circuit is verified (unitarily, when small enough) before its row is "
            "recorded; the verification status is in the row's extra data.",
        ],
    )


def shots_convergence(
    algorithm: str = "grover",
    *,
    shots_values: Sequence[int] = (64, 256, 1024, 4096, 16384),
    num_qubits: int = 4,
    noise: NoiseModel | None = None,
    seed: int = 31337,
) -> ExperimentSpec:
    """Sampling error as a function of shot count."""
    return ExperimentSpec(
        key=f"{algorithm}_shots_convergence",
        name=f"{algorithm} shot convergence",
        kind="shots_convergence",
        description="Measure how the sampled distribution approaches the exact one as shots grow.",
        algorithm=algorithm,
        axes=[SweepAxis("shots", list(shots_values), "Shots")],
        fixed={"algorithm": algorithm, "num_qubits": num_qubits},
        shots=max(shots_values),
        noise=noise or NoiseModel.ideal(),
        seed=seed,
        tags=["statistics", "shots"],
        notes=[
            "The distribution distance is the total variation between the sampled histogram and the "
            "exact Born distribution; its expected size shrinks as 1/sqrt(shots).",
        ],
    )


def parameter_sweep(
    algorithm: str = "qaoa_maxcut",
    *,
    axis: str = "gamma",
    values: Sequence[float] = tuple(np.linspace(0, math.pi, 9)),
    fixed: dict[str, Any] | None = None,
    shots: int = 2048,
    seed: int = 555,
) -> ExperimentSpec:
    """Sweep a variational parameter and watch the objective."""
    return ExperimentSpec(
        key=f"{algorithm}_{axis}_sweep",
        name=f"{algorithm} {axis} sweep",
        kind="parameter_sweep",
        description="Sweep one variational parameter and record the objective at each value.",
        algorithm=algorithm,
        axes=[SweepAxis(axis, [float(v) for v in values], axis)],
        fixed={"algorithm": algorithm, **(fixed or {})},
        shots=shots,
        seed=seed,
        tags=["variational", algorithm],
        notes=[
            "For QAOA the recorded objective is the Max-Cut value of the sampled bitstrings, "
            "including the optimum and the approximation ratio.",
            "For VQE the recorded energy is the exact expectation value of the Ising Hamiltonian, "
            "so it carries no shot noise.",
        ],
    )


def custom_experiment(
    name: str,
    axes: Sequence[SweepAxis],
    *,
    algorithm: str | None = None,
    fixed: dict[str, Any] | None = None,
    shots: int = 2048,
    backend: str = "auto",
    noise: NoiseModel | None = None,
    seed: int = 12345,
    tags: Sequence[str] = (),
) -> ExperimentSpec:
    """Arbitrary cartesian sweep defined by the caller."""
    return ExperimentSpec(
        key=name.lower().replace(" ", "_"),
        name=name,
        kind="custom",
        algorithm=algorithm,
        axes=list(axes),
        fixed=dict(fixed or {}),
        shots=shots,
        backend=backend,
        noise=noise or NoiseModel.ideal(),
        seed=seed,
        tags=list(tags),
    )


def experiment_catalog() -> list[dict[str, Any]]:
    """Ready-made experiments for the UI."""
    return [
        {
            "key": "grover_scaling",
            "name": "Grover scaling",
            "kind": "algorithm_scaling",
            "description": "Grover across 2..6 qubits: cost, runtime, success probability vs the analytic prediction.",
            "factory": "algorithm_scaling",
            "defaults": {"algorithm": "grover", "qubits": [2, 3, 4, 5, 6]},
        },
        {
            "key": "ghz_scaling",
            "name": "GHZ scaling",
            "kind": "algorithm_scaling",
            "description": "Entanglement preparation cost and fidelity as the register grows.",
            "factory": "algorithm_scaling",
            "defaults": {"algorithm": "ghz_state", "qubits": [2, 3, 4, 6, 8]},
        },
        {
            "key": "qpe_precision",
            "name": "Phase estimation precision",
            "kind": "algorithm_scaling",
            "description": "QPE with increasing counting qubits: resolution vs circuit cost.",
            "factory": "algorithm_scaling",
            "defaults": {"algorithm": "quantum_phase_estimation", "qubits": [3, 4, 5, 6, 7]},
        },
        {
            "key": "grover_noise",
            "name": "Noise impact on Grover",
            "kind": "noise_sweep",
            "description": "Fidelity, purity and success probability as depolarising noise grows.",
            "factory": "noise_sweep",
            "defaults": {"algorithm": "grover", "num_qubits": 4},
        },
        {
            "key": "bell_backends",
            "name": "Engine comparison (Bell state)",
            "kind": "backend_comparison",
            "description": "The same circuit on state-vector, density-matrix and trajectory engines.",
            "factory": "backend_comparison",
            "defaults": {"algorithm": "bell_state"},
        },
        {
            "key": "grover_optimize",
            "name": "Optimization study",
            "kind": "optimizer_comparison",
            "description": "Verify and measure each optimization level against the original circuit.",
            "factory": "optimizer_comparison",
            "defaults": {"algorithm": "grover", "num_qubits": 4},
        },
        {
            "key": "grover_shots",
            "name": "Shot convergence",
            "kind": "shots_convergence",
            "description": "Sampling error against the exact distribution as shots increase.",
            "factory": "shots_convergence",
            "defaults": {"algorithm": "grover", "num_qubits": 4},
        },
        {
            "key": "qaoa_gamma",
            "name": "QAOA parameter sweep",
            "kind": "parameter_sweep",
            "description": "Max-Cut objective as the cost angle gamma varies.",
            "factory": "parameter_sweep",
            "defaults": {"algorithm": "qaoa_maxcut", "axis": "gamma"},
        },
    ]


__all__ = [
    "EXPERIMENT_KINDS",
    "ExperimentOutcome",
    "ExperimentRow",
    "ExperimentSpec",
    "SweepAxis",
    "algorithm_scaling",
    "backend_comparison",
    "custom_experiment",
    "describe_bytes",
    "experiment_catalog",
    "noise_sweep",
    "optimizer_comparison",
    "parameter_sweep",
    "run_experiment",
    "shots_convergence",
]
