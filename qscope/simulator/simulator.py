"""The execution engines.

Three engines, three honest tradeoffs:

============================  ==========  =========  ==============================
engine                        exact?      noise?     when QScope picks it
============================  ==========  =========  ==============================
``statevector``               yes         no         ideal circuits
``density_matrix``            yes         yes        noisy, small enough to be exact
``trajectory`` (Monte Carlo)  no          yes        noisy, too large for a matrix
============================  ==========  =========  ==============================

Every result carries ``mode``: ``SIMULATED`` for an ideal run, ``NOISY
SIMULATION`` when a noise model was applied, and the noise summary says whether
that noisy run was exact (density matrix) or sampled (trajectories).  A mixture
of the two is never presented as a single number without that label.
"""

from __future__ import annotations

import platform
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

import numpy as np

from qscope.core.density import DensityMatrix
from qscope.core.measurement import apply_readout_error, marginal_probabilities
from qscope.core.statevector import StateVector
from qscope.core.tensor import COMPLEX
from qscope.circuit.circuit import BARRIER, DELAY, GATE, MEASURE, RESET, Circuit, Operation
from qscope.simulator.execution import BACKENDS, ExecutionPlan, RunOptions, plan_execution
from qscope.simulator.noise import SCOPE_GATE, SCOPE_GLOBAL, SCOPE_IDLE, NoiseModel

MODE_IDEAL = "SIMULATED"
MODE_NOISY = "NOISY SIMULATION"
MODE_HARDWARE = "REAL HARDWARE"
"""QScope never claims hardware results without a hardware backend."""


class SimulationError(RuntimeError):
    """Raised when a plan is blocked or an operation cannot be executed."""

    def __init__(self, message: str, plan: ExecutionPlan | None = None) -> None:
        super().__init__(message)
        self.plan = plan

    def to_dict(self) -> dict[str, Any]:
        return {
            "error": str(self),
            "plan": self.plan.to_dict() if self.plan else None,
        }


@dataclass
class StepTiming:
    """Per-operation timing captured during a run."""

    index: int
    name: str
    display: str
    kind: str
    seconds: float
    targets: list[int]
    depth_layer: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "name": self.name,
            "display": self.display,
            "kind": self.kind,
            "seconds": self.seconds,
            "targets": self.targets,
            "depth_layer": self.depth_layer,
        }


@dataclass
class ShotRecord:
    """Outcome of one conditional (mid-circuit) run."""

    shot: int
    clbits: dict[int, int]
    label: str

    def to_dict(self) -> dict[str, Any]:
        return {"shot": self.shot, "clbits": self.clbits, "label": self.label}


@dataclass
class SimulationResult:
    """Everything a single run produced, with provenance attached."""

    circuit_name: str
    circuit: dict[str, Any]
    plan: dict[str, Any]
    mode: str
    backend: str
    shots: int
    seed: int
    counts: dict[str, int]
    ideal_probabilities: dict[str, float]
    sampled_probabilities: dict[str, float]
    measured_qubits: list[int]
    reference_probabilities: dict[str, float] | None = None
    """Born distribution of the ideal reference state (``None`` for ideal runs)."""
    statevector: dict[str, Any] | None = None
    density_matrix: dict[str, Any] | None = None
    metrics: dict[str, Any] = field(default_factory=dict)
    ideal_metrics: dict[str, Any] | None = None
    fidelity_vs_ideal: float | None = None
    trace_distance_vs_ideal: float | None = None
    noise: dict[str, Any] = field(default_factory=dict)
    timing: dict[str, Any] = field(default_factory=dict)
    memory: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    shot_records: list[dict[str, Any]] = field(default_factory=list)
    timestamp: str = ""
    solution_register: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)
    _state: Any = field(default=None, repr=False, compare=False)
    """Live :class:`StateVector`/:class:`DensityMatrix` retained for downstream analysis."""

    def to_dict(self, include_state: bool = True) -> dict[str, Any]:
        out = {
            "circuit_name": self.circuit_name,
            "circuit": self.circuit,
            "plan": self.plan,
            "mode": self.mode,
            "backend": self.backend,
            "shots": self.shots,
            "seed": self.seed,
            "counts": self.counts,
            "ideal_probabilities": self.ideal_probabilities,
            "reference_probabilities": self.reference_probabilities,
            "sampled_probabilities": self.sampled_probabilities,
            "measured_qubits": self.measured_qubits,
            "metrics": self.metrics,
            "ideal_metrics": self.ideal_metrics,
            "fidelity_vs_ideal": self.fidelity_vs_ideal,
            "trace_distance_vs_ideal": self.trace_distance_vs_ideal,
            "noise": self.noise,
            "timing": self.timing,
            "memory": self.memory,
            "warnings": self.warnings,
            "notes": self.notes,
            "shot_records": self.shot_records,
            "timestamp": self.timestamp,
            "solution_register": self.solution_register,
            "extra": self.extra,
        }
        if include_state:
            out["statevector"] = self.statevector
            out["density_matrix"] = self.density_matrix
        return out

    def probabilities(self) -> list[dict[str, Any]]:
        """Born distribution of the reported final state, sorted by probability."""
        return [
            {"basis": k, "probability": v}
            for k, v in sorted(self.ideal_probabilities.items(), key=lambda kv: (-kv[1], kv[0]))
        ]

    def state_stage(self) -> str:
        """Where in the circuit the reported state was captured."""
        return "pre-final-measurement"


# ---------------------------------------------------------------------------
# single-shot execution
# ---------------------------------------------------------------------------


def _condition_met(op: Operation, clbits: dict[int, int]) -> bool:
    if op.condition is None:
        return True
    return clbits.get(op.condition.clbit, 0) == op.condition.value


def _sample_kraus(
    state: StateVector,
    kraus: Sequence[np.ndarray],
    targets: Sequence[int],
    rng: np.random.Generator,
) -> StateVector:
    """Draw one Kraus branch and renormalise (a single Monte-Carlo trajectory).

    ``p_i = ||K_i |psi>||^2`` is the probability of that branch; the drawn state is
    ``K_i|psi> / sqrt(p_i)``, which keeps the trajectory normalised at every step.
    """
    if len(kraus) == 1:
        return state.apply_matrix(kraus[0], targets)
    branches: list[StateVector] = []
    probs = np.zeros(len(kraus))
    for i, k in enumerate(kraus):
        branch = state.copy().apply_matrix(k, targets)
        probs[i] = float(np.linalg.norm(branch.data) ** 2)
        branches.append(branch)
    total = probs.sum()
    if total <= 0:
        return state
    probs = probs / total
    pick = int(rng.choice(len(kraus), p=probs))
    chosen = branches[pick]
    norm = float(np.linalg.norm(chosen.data))
    if norm > 0:
        chosen.data /= norm
    return chosen


def _noise_for_op(model: NoiseModel, op: Operation, num_qubits: int) -> list[tuple[list[np.ndarray], list[int]]]:
    """Kraus channels to apply after ``op``.

    A ``delay`` is treated as a machine-idle step: every wire takes idle noise,
    which is how idle decoherence is normally accounted for in a gate-level model.
    """
    if model.is_ideal():
        return []
    if op.kind == DELAY:
        shim = Operation(name="delay", targets=[], kind=DELAY)
        return model.gate_channels(shim, num_qubits)
    if op.kind in (MEASURE, RESET, BARRIER):
        return []
    return model.gate_channels(op, num_qubits)


def _reset_statevector(state: StateVector, qubit: int) -> StateVector:
    """Project a qubit to |0> and renormalise (a deterministic reset)."""
    mask = [state.num_qubits - 1 - qubit]
    data = state.data.copy()
    for index in range(len(data)):
        if (index >> mask[0]) & 1:
            data[index] = 0.0
    norm = float(np.linalg.norm(data))
    if norm <= 0:
        raise SimulationError(
            f"reset on qubit {qubit} has zero probability: the operation is not physical here"
        )
    state.data = data / norm
    return state


def simulate_shot(
    circuit: Circuit,
    backend: str,
    noise: NoiseModel,
    rng: np.random.Generator,
    *,
    ops: Sequence[Operation] | None = None,
    timings: list[StepTiming] | None = None,
    trace: list[dict[str, Any]] | None = None,
    trace_step: int = 0,
) -> tuple[Any, dict[int, int], int]:
    """Execute one shot, returning ``(final_state, clbits, measured_steps)``.

    ``ops`` overrides the operation list (the run loop uses it to stop before the
    terminal measurement block, so that a single evolution still yields the true
    Born distribution instead of one collapsed branch).

    Noise is applied exactly (density matrix) or by branch sampling (trajectory)
    depending on ``backend``.
    """
    n = circuit.num_qubits
    clbits: dict[int, int] = {}
    exact = backend == "density_matrix"
    state: Any = DensityMatrix(n) if exact else StateVector(n)
    measured_steps = 0
    operations = list(circuit.operations if ops is None else ops)

    for index, op in enumerate(operations):
        started = time.perf_counter()
        if op.kind == BARRIER:
            continue
        if not _condition_met(op, clbits):
            continue
        if op.kind == GATE:
            # ``apply_controlled`` builds the embedded operator itself, so the two
            # paths are mutually exclusive; applying both would double the gate.
            if op.controls:
                state.apply_controlled(op.name, op.controls, op.targets, op.params)
            else:
                state.apply_gate(op.name, op.targets, op.params)
        elif op.kind == MEASURE:
            outcome = state.measure_qubit(op.targets[0], rng)
            clbits[op.classical_targets[0]] = outcome.outcome
            measured_steps += 1
        elif op.kind == RESET:
            if exact:
                state.partial_reset(op.targets[0], 1.0)
            else:
                state = _reset_statevector(state, op.targets[0])
        elif op.kind == DELAY:
            pass  # handled by the noise block below

        for kraus, targets in _noise_for_op(noise, op, n):
            if exact:
                state.apply_channel(kraus, targets)
            else:
                state = _sample_kraus(state, kraus, targets, rng)

        elapsed = time.perf_counter() - started
        if timings is not None:
            timings.append(
                StepTiming(
                    index=index,
                    name=op.name,
                    display=op.display,
                    kind=op.kind,
                    seconds=elapsed,
                    targets=list(op.qubits),
                )
            )
        if trace is not None:
            trace.append(
                {
                    "index": index,
                    "step": trace_step + index,
                    "name": op.name,
                    "display": op.display,
                    "kind": op.kind,
                    "targets": list(op.qubits),
                    "controls": list(op.controls),
                    "params": list(op.params),
                    "seconds": elapsed,
                    "clbits": dict(clbits),
                    "state": _summarise_state(state, n),
                }
            )
    return state, clbits, measured_steps


def _summarise_state(state: Any, n: int, limit: int = 24) -> dict[str, Any]:
    """Compact state snapshot for traces (kept small on purpose)."""
    if isinstance(state, DensityMatrix):
        probs = state.probabilities()
        order = np.argsort(probs)[::-1][:limit]
        from qscope.core.tensor import basis_label

        return {
            "type": "density_matrix",
            "purity": state.purity(),
            "entropy": state.entropy(),
            "terms": [
                {"basis": basis_label(n, int(i)), "probability": float(probs[i])}
                for i in order
                if probs[i] > 1e-12
            ],
        }
    probs = state.probabilities()
    order = np.argsort(probs)[::-1][:limit]
    from qscope.core.tensor import basis_label

    return {
        "type": "statevector",
        "norm": state.norm(),
        "terms": [
            {
                "basis": basis_label(n, int(i)),
                "probability": float(probs[i]),
                "amplitude": [float(state.data[i].real), float(state.data[i].imag)],
                "phase": float(np.angle(state.data[i])),
            }
            for i in order
            if probs[i] > 1e-12
        ],
    }


# ---------------------------------------------------------------------------
# whole-circuit execution
# ---------------------------------------------------------------------------


def measured_qubits_of(circuit: Circuit, measure_all: bool = True) -> list[int]:
    """Which qubits a run reports on."""
    explicit = sorted({op.targets[0] for op in circuit.measurements})
    if explicit:
        return explicit
    if measure_all:
        return list(range(circuit.num_qubits))
    return []


def split_terminal_measurements(circuit: Circuit) -> tuple[list[Operation], list[Operation]]:
    """Split off the trailing measurement block.

    A circuit that ends in measurements is usually meant as "prepare this state,
    then read every wire".  Collapsing once and reporting that single branch would
    throw away the distribution we are actually trying to measure, so the run loop
    evolves only the prefix and samples the terminal readout from its Born
    distribution.  Anything *before* the final block still collapses for real.
    """
    ops = circuit.operations
    cut = len(ops)
    while cut > 0 and ops[cut - 1].kind in (MEASURE, BARRIER):
        cut -= 1
    prefix = ops[:cut]
    terminal = [op for op in ops[cut:] if op.kind == MEASURE]
    return prefix, terminal


def reset_statevector(state: Any, qubit: int) -> Any:
    """Public alias for the deterministic reset used by the simulator and tracer."""
    return _reset_statevector(state, qubit)


def _memory_snapshot(state: Any, plan: ExecutionPlan) -> dict[str, Any]:
    """State footprint plus process RSS delta when available."""
    live = int(getattr(state, "data", np.zeros(1)).nbytes)
    info: dict[str, Any] = {
        "state_bytes": live,
        "state_mb": live / 1e6,
        "estimated_bytes": plan.estimated_bytes,
        "estimated_peak_bytes": plan.estimated_peak_bytes,
        "budget_bytes": plan.budget_bytes,
    }
    try:
        import psutil

        proc = psutil.Process()
        rss = proc.memory_info().rss
        info["process_rss_bytes"] = int(rss)
        info["process_rss_mb"] = rss / 1e6
        info["system_available_mb"] = psutil.virtual_memory().available / 1e6
    except Exception:
        info["process_rss_bytes"] = None
    return info


def run_circuit(
    circuit: Circuit,
    options: RunOptions | None = None,
    *,
    progress: Callable[[int, int], None] | None = None,
) -> SimulationResult:
    """Execute a circuit and return a fully annotated result.

    Shot semantics:

    * No mid-circuit measurement and no classical feedback → the state is evolved
      **once** and shots are sampled from the final Born distribution.  That is
      exactly equivalent to repeating the circuit, and much faster.
    * Mid-circuit measurement or classical feedback → the circuit really is run
      ``shots`` times, because later gates depend on earlier outcomes.
    * Trajectory backend with noise → also ``shots`` genuine trajectories, since
      each shot samples a different set of Kraus branches.
    """
    options = options or RunOptions()
    plan = plan_execution(circuit, options)
    if plan.blocked:
        raise SimulationError("; ".join(plan.warnings) or "execution blocked", plan)

    backend = plan.backend
    seed = options.seed if options.seed is not None else int(np.random.default_rng().integers(0, 2**31 - 1))
    rng = np.random.default_rng(seed)
    t_start = time.perf_counter()

    n = circuit.num_qubits
    measured = measured_qubits_of(circuit, options.measure_all)
    conditional = circuit.has_mid_circuit_measurement() or circuit.has_classical_control()
    per_shot = conditional or backend == "trajectory"
    prefix, terminal = split_terminal_measurements(circuit)
    has_measurements = bool(circuit.measurements)

    timings: list[StepTiming] = []
    shot_records: list[ShotRecord] = []
    counts: dict[str, int] = {}
    state: Any = None

    if per_shot:
        ops = circuit.operations if has_measurements else prefix
        for shot in range(options.shots):
            state, clbits, _ = simulate_shot(
                circuit, backend, options.noise, rng, ops=ops, timings=timings if shot == 0 else None
            )
            label = "".join(str(clbits.get(c, 0)) for c in sorted(clbits))
            shot_records.append(ShotRecord(shot=shot, clbits=dict(clbits), label=label))
            if has_measurements:
                key = "".join(str(clbits.get(c, 0)) for c in range(circuit.num_clbits))
            else:
                # No readout in the circuit: read every wire at the end of this shot.
                key = _sample_key(state, measured, rng)
            counts[key] = counts.get(key, 0) + 1
            if progress is not None and (shot % max(1, options.shots // 50) == 0):
                progress(shot, options.shots)
    else:
        state, clbits, _ = simulate_shot(
            circuit, backend, options.noise, rng, ops=prefix, timings=timings
        )

    # ------------------------------------------- ideal reference + sampling
    # The reported state is always the state *before* the terminal readout: the
    # terminal measurement block is a readout instruction, not a computation, and
    # collapsing it would replace the distribution with one sampled branch.
    from qscope.analysis.metrics import state_metrics

    reference_state: Any = None
    if not conditional:
        if options.noise.is_ideal() or not options.compare_ideal:
            reference_state = state  # already the ideal pre-readout state
        else:
            reference_state, _, _ = simulate_shot(
                circuit, "statevector", NoiseModel.ideal(), np.random.default_rng(0), ops=prefix
            )

    probabilities = _marginal_probabilities(state, measured)
    reference_probabilities = (
        _marginal_probabilities(reference_state, measured) if reference_state is not None else None
    )

    if per_shot:
        primary = counts
    else:
        primary = _sample_counts(probabilities, options.shots, rng)
    if options.noise.readout_error > 0 and options.apply_readout_error and measured:
        primary, _ = apply_readout_error(
            primary,
            max(len(measured), 1),
            options.noise.readout_error,
            rng,
            symmetric=not options.noise.measurement_error_asymmetric,
        )
    if conditional:
        # With classical feedback there is no single pre-readout state to sample
        # from; the empirical histogram *is* the distribution.
        probabilities = _normalise(counts)
        reference_probabilities = None

    total_elapsed = time.perf_counter() - t_start

    # ------------------------------------------------ fidelity vs ideal state
    ideal_metrics = None
    fidelity = None
    trace_distance = None
    if reference_state is not None and reference_state is not state:
        ideal_metrics = state_metrics(reference_state, measured)
        try:
            if isinstance(state, DensityMatrix):
                fidelity = state.fidelity_pure(reference_state)
                trace_distance = state.trace_distance(DensityMatrix.from_statevector(reference_state))
            else:
                fidelity = state.fidelity(reference_state)
            if backend == "trajectory":
                plan.notes.append(
                    "Fidelity is measured against the ideal state for this single Monte-Carlo "
                    "trajectory, not for the ensemble average."
                )
        except Exception as exc:  # pragma: no cover - a comparison must never break a run
            plan.warnings.append(f"ideal reference comparison failed: {exc}")
    elif reference_state is state:
        ideal_metrics = None  # an ideal run is its own reference

    metrics = state_metrics(state, measured)
    if ideal_metrics is not None:
        metrics["ideal"] = {
            "dominant_basis": ideal_metrics["dominant_basis"],
            "dominant_probability": ideal_metrics["dominant_probability"],
            "purity": ideal_metrics["purity"],
            "entropy": ideal_metrics["entropy"],
            "entanglement_status": ideal_metrics.get("entanglement_status"),
        }

    mode = MODE_IDEAL if options.noise.is_ideal() else MODE_NOISY
    algorithm = options.algorithm or circuit.metadata.get("algorithm", "")
    solution = circuit.metadata.get("solution_register")

    result = SimulationResult(
        circuit_name=circuit.name,
        circuit=circuit.to_dict() if options.store_state else {"name": circuit.name},
        plan=plan.to_dict(),
        mode=mode,
        backend=backend,
        shots=options.shots,
        seed=seed,
        counts=dict(sorted(primary.items(), key=lambda kv: (-kv[1], kv[0]))),
        ideal_probabilities=probabilities,
        reference_probabilities=reference_probabilities,
        sampled_probabilities=_normalise(primary),
        measured_qubits=measured,
        statevector=state.to_dict() if (options.store_state and isinstance(state, StateVector)) else None,
        density_matrix=state.to_dict() if (options.store_state and isinstance(state, DensityMatrix)) else None,
        metrics=metrics,
        ideal_metrics=ideal_metrics,
        fidelity_vs_ideal=fidelity,
        trace_distance_vs_ideal=trace_distance,
        noise=options.noise.summary(),
        timing={
            "total_seconds": total_elapsed,
            "operations": len(circuit.operations),
            "shots": options.shots,
            "conditional_shots": per_shot,
            "seconds_per_shot": total_elapsed / max(options.shots, 1) if per_shot else None,
            "operations_per_second": len(circuit.operations) / total_elapsed if total_elapsed > 0 else None,
            "per_operation": [t.to_dict() for t in timings],
            "python": platform.python_version(),
            "sampling": "per-shot" if per_shot else "single evolution + Born sampling",
        },
        memory=_memory_snapshot(state, plan),
        warnings=list(plan.warnings),
        notes=list(plan.notes),
        shot_records=[r.to_dict() for r in shot_records[: min(len(shot_records), 256)]],
        timestamp=time.strftime("%Y-%m-%dT%H:%M:%S"),
        solution_register=solution,
        extra={
            "algorithm": algorithm,
            "optimizer": options.optimizer,
            "final_clbits": {str(k): v for k, v in sorted(clbits.items())},
            "num_clbits": circuit.num_clbits,
        },
        _state=state,
    )
    if progress is not None:
        progress(options.shots, options.shots)
    return result


def _marginal_probabilities(state: Any, measured: Sequence[int]) -> dict[str, float]:
    """Born probabilities restricted to the reported qubits."""
    if not measured:
        return {}
    if isinstance(state, DensityMatrix):
        probs = state.probabilities()
    else:
        probs = state.normalized_probabilities()
    return marginal_probabilities(probs, _num_qubits_of(state), measured)


def _num_qubits_of(state: Any) -> int:
    return int(state.num_qubits)


def _sample_counts(probabilities: dict[str, float], shots: int, rng: np.random.Generator) -> dict[str, int]:
    from qscope.core.measurement import sample_counts

    if not probabilities:
        return {}
    labels = sorted(probabilities)
    counts, _ = sample_counts([probabilities[l] for l in labels], shots, rng, labels=labels)
    return counts


def _sample_key(state: Any, measured: Sequence[int], rng: np.random.Generator) -> str:
    """Fallback outcome label when a circuit has no classical bits."""
    probabilities = _marginal_probabilities(state, measured)
    if not probabilities:
        return ""
    labels = sorted(probabilities)
    probs = np.array([probabilities[l] for l in labels], dtype=float)
    probs = probs / probs.sum()
    return str(rng.choice(np.array(labels, dtype=object), p=probs))


def _normalise(counts: dict[str, int]) -> dict[str, float]:
    total = sum(counts.values())
    if not total:
        return {}
    return {k: v / total for k, v in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))}


def ideal_state_of(circuit: Circuit) -> StateVector:
    """Exact ideal final state vector of a unitary circuit (no shots, no noise)."""
    if circuit.has_mid_circuit_measurement() or circuit.has_classical_control():
        raise SimulationError("ideal_state_of requires a circuit without measurement feedback")
    state, _, _ = simulate_shot(circuit, "statevector", NoiseModel.ideal(), np.random.default_rng(0))
    return state


def run_unitary(circuit: Circuit) -> np.ndarray:
    """Full unitary matrix of a circuit (memory-guarded by :meth:`Circuit.to_unitary`)."""
    return circuit.to_unitary()


__all__ = [
    "MODE_HARDWARE",
    "MODE_IDEAL",
    "MODE_NOISY",
    "ShotRecord",
    "SimulationError",
    "SimulationResult",
    "StepTiming",
    "ideal_state_of",
    "measured_qubits_of",
    "reset_statevector",
    "run_circuit",
    "run_unitary",
    "simulate_shot",
    "split_terminal_measurements",
]
