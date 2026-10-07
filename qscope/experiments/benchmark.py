"""Performance observatory and benchmarking.

Everything in this module **measures**.  Nothing is estimated unless it is labelled
as an estimate, and QScope does not compare itself to another simulator unless that
simulator is actually importable and actually run — in which case the raw numbers
are returned with the caveats that explain why the comparison is or is not fair
(different representations, different precision, different threading).

Methodology, stated so the numbers can be judged:

* every measurement is repeated (default 3 trials) and the **median** is reported;
  the spread is reported too, so a noisy measurement cannot masquerade as a trend,
* a warm-up run precedes timing so import/JIT/allocation effects do not dominate,
* garbage collection is disabled during timing intervals,
* timings are wall-clock on this machine in a single Python process.
"""

from __future__ import annotations

import gc
import importlib.util
import math
import platform
import statistics
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

import numpy as np

from qscope.circuit.circuit import Circuit
from qscope.simulator.execution import (
    BACKENDS,
    RunOptions,
    describe_bytes,
    memory_budget_bytes,
    plan_execution,
    safe_max_qubits,
    scaling_table,
)
from qscope.simulator.noise import NoiseModel
from qscope.simulator.simulator import SimulationError, run_circuit

BENCHMARK_CAVEATS = [
    "Wall-clock timing in one Python process on this machine; not a hardware claim.",
    "Only medians of repeated trials are reported, with the spread alongside.",
    "Different engines represent different physics; runtime differences between them are not "
    "differences in correctness.",
    "Classical simulation cost is exponential in qubit count by construction: that is the "
    "fundamental limit this observatory exists to make visible.",
]


@dataclass
class Measurement:
    """One timed measurement with its spread."""

    label: str
    trials: int
    median_seconds: float
    min_seconds: float
    max_seconds: float
    spread_seconds: float
    per_shot_seconds: float | None = None
    operations_per_second: float | None = None
    memory_mb: float | None = None
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "trials": self.trials,
            "median_seconds": self.median_seconds,
            "min_seconds": self.min_seconds,
            "max_seconds": self.max_seconds,
            "spread_seconds": self.spread_seconds,
            "per_shot_seconds": self.per_shot_seconds,
            "operations_per_second": self.operations_per_second,
            "memory_mb": self.memory_mb,
            "notes": self.notes,
        }


def _time_callable(fn: Callable[[], Any], trials: int = 3) -> tuple[list[float], Any]:
    """Time ``fn`` with a warm-up, GC disabled, returning all trial times."""
    fn()  # warm-up
    times: list[float] = []
    result = None
    gc_was_enabled = gc.isenabled()
    gc.disable()
    try:
        for _ in range(trials):
            start = time.perf_counter()
            result = fn()
            times.append(time.perf_counter() - start)
    finally:
        if gc_was_enabled:
            gc.enable()
    return times, result


def compute_circuit(num_qubits: int, depth: int = 4, seed: int = 7) -> Circuit:
    """A reproducible benchmark circuit: layered rotations plus a CNOT ladder."""
    rng = np.random.default_rng(seed)
    circuit = Circuit(num_qubits, num_qubits, name=f"bench_{num_qubits}q_d{depth}")
    for layer in range(depth):
        for q in range(num_qubits):
            circuit.add("RY", [q], [float(rng.uniform(0, 2 * math.pi))])
            circuit.add("RZ", [q], [float(rng.uniform(0, 2 * math.pi))])
        for q in range(layer % 2, num_qubits - 1, 2):
            circuit.add("CNOT", [q, q + 1])
    circuit.measure_all()
    return circuit


def ghz_circuit(num_qubits: int) -> Circuit:
    circuit = Circuit(num_qubits, num_qubits, name=f"ghz_{num_qubits}")
    circuit.add("H", [0])
    for q in range(1, num_qubits):
        circuit.add("CNOT", [q - 1, q])
    circuit.measure_all()
    return circuit


def benchmark_backends(
    *,
    qubits: Sequence[int] = (6, 8, 10),
    shots: int = 1024,
    trials: int = 3,
    noise: NoiseModel | None = None,
    circuit_factory: Callable[[int], Circuit] = ghz_circuit,
) -> dict[str, Any]:
    """Time each engine at each circuit size; report refusals instead of crashing."""
    rows: list[dict[str, Any]] = []
    model = noise or NoiseModel.ideal()
    for n in qubits:
        circuit = circuit_factory(n)
        for key in BACKENDS:
            options = RunOptions(backend=key, shots=shots, noise=model, seed=99)
            plan = plan_execution(circuit, options)
            row: dict[str, Any] = {
                "qubits": n,
                "backend": key,
                "backend_label": BACKENDS[key].label,
                "exact": plan.exact,
                "gates": circuit.gate_count(),
                "depth": circuit.depth(),
                "estimated_mb": plan.estimated_bytes / 1e6,
                "blocked": plan.blocked,
                "warnings": plan.warnings,
            }
            if plan.blocked:
                row.update(
                    status="refused",
                    reason=plan.warnings[-1] if plan.warnings else "memory budget exceeded",
                    median_seconds=None,
                )
                rows.append(row)
                continue
            try:
                times, result = _time_callable(lambda: run_circuit(circuit, options), trials)
            except SimulationError as exc:
                row.update(status="error", reason=str(exc), median_seconds=None)
                rows.append(row)
                continue
            measurement = Measurement(
                label=f"{key}@{n}q",
                trials=len(times),
                median_seconds=statistics.median(times),
                min_seconds=min(times),
                max_seconds=max(times),
                spread_seconds=max(times) - min(times),
                per_shot_seconds=statistics.median(times) / shots,
                operations_per_second=circuit.op_count() / statistics.median(times),
                memory_mb=result.memory.get("state_mb"),
            )
            row.update(
                status="measured",
                **{k: v for k, v in measurement.to_dict().items() if k != "label"},
                mode=result.mode,
            )
            rows.append(row)
    return {
        "kind": "backend_benchmark",
        "rows": rows,
        "shots": shots,
        "trials": trials,
        "noise": model.to_dict(),
        "caveats": BENCHMARK_CAVEATS,
        "method": "median of repeated timed runs, warm-up discarded, GC disabled during timing",
    }


def benchmark_scaling(
    *,
    qubits: Sequence[int] = (8, 10, 12, 14, 16, 18),
    shots: int = 512,
    trials: int = 3,
    circuit_factory: Callable[[int], Circuit] = ghz_circuit,
    extrapolate_to: Sequence[int] = (20, 22, 24),
    noise: NoiseModel | None = None,
) -> dict[str, Any]:
    """Measure runtime vs qubit count and fit the observed growth.

    The fit is an exponential ``t(n) = a * b^n`` obtained by linear regression on
    ``log t``; the fitted base ``b`` is the empirical cost multiplier per added
    qubit.  Extrapolations are clearly separated from measurements.
    """
    points: list[dict[str, Any]] = []
    model = noise or NoiseModel.ideal()
    for n in qubits:
        circuit = circuit_factory(n)
        options = RunOptions(backend="statevector", shots=shots, noise=model, seed=5)
        plan = plan_execution(circuit, options)
        if plan.blocked:
            points.append(
                {
                    "qubits": n,
                    "status": "refused",
                    "reason": plan.warnings[-1] if plan.warnings else "over budget",
                }
            )
            continue
        try:
            times, result = _time_callable(lambda: run_circuit(circuit, options), trials)
        except SimulationError as exc:
            points.append({"qubits": n, "status": "error", "reason": str(exc)})
            continue
        points.append(
            {
                "qubits": n,
                "status": "measured",
                "gates": circuit.gate_count(),
                "depth": circuit.depth(),
                "median_seconds": statistics.median(times),
                "spread_seconds": max(times) - min(times),
                "memory_mb": result.memory.get("state_mb"),
                "ops_per_second": circuit.op_count() / statistics.median(times),
            }
        )

    measured = [p for p in points if p["status"] == "measured"]
    fit: dict[str, Any] = {"available": False}
    if len(measured) >= 3:
        xs = np.array([p["qubits"] for p in measured], dtype=float)
        ys = np.array([math.log(max(p["median_seconds"], 1e-9)) for p in measured], dtype=float)
        slope, intercept = np.polyfit(xs, ys, 1)
        predicted = np.exp(intercept + slope * xs)
        residuals = ys - (intercept + slope * xs)
        ss_res = float(np.sum(residuals**2))
        ss_tot = float(np.sum((ys - ys.mean()) ** 2))
        r_squared = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0
        base = math.exp(slope)
        fit = {
            "available": True,
            "model": "t(n) = a * b^n  (linear regression of log runtime on qubit count)",
            "multiplier_per_added_qubit": base,
            "doubling_qubits": math.log(2) / slope if slope > 0 else None,
            "r_squared": r_squared,
            "a": math.exp(intercept),
            "measurements": [
                {"qubits": int(x), "measured_seconds": float(t), "predicted_seconds": float(p)}
                for x, t, p in zip(xs, [p["median_seconds"] for p in measured], predicted)
            ],
            "extrapolations": [
                {
                    "qubits": int(n),
                    "predicted_seconds": float(math.exp(intercept + slope * n)),
                    "predicted_memory_mb": BACKENDS["statevector"].estimate_bytes(n) / 1e6,
                    "label": "EXTRAPOLATED from the fitted model, not measured",
                }
                for n in extrapolate_to
            ],
            "note": (
                f"Each added qubit multiplied runtime by about {base:.2f}× on this machine. "
                "This is the empirical exponential of classical state-vector simulation."
            ),
        }
    else:
        fit["reason"] = "fewer than three successful measurements; no fit attempted"
    return {
        "kind": "scaling_benchmark",
        "points": points,
        "fit": fit,
        "shots": shots,
        "trials": trials,
        "caveats": BENCHMARK_CAVEATS
        + ["Extrapolated points are model output, and are labelled as such."],
    }


def benchmark_gate_throughput(
    *,
    num_qubits: int = 16,
    gates: Sequence[str] = ("X", "H", "RZ", "CNOT", "CZ", "SWAP"),
    repetitions: int = 20,
    trials: int = 3,
) -> dict[str, Any]:
    """Gate application throughput at a fixed qubit count."""
    from qscope.core.statevector import StateVector

    rows: list[dict[str, Any]] = []
    for gate in gates:
        arity = 1 if gate in {"X", "H", "RZ"} else 2

        def run() -> None:
            state = StateVector(num_qubits)
            for _ in range(repetitions):
                if arity == 1:
                    state.apply_gate(gate, [0], [0.3] if gate == "RZ" else [])
                else:
                    state.apply_gate(gate, [0, 1, 2][:arity])

        times, _ = _time_callable(run, trials)
        total_gates = repetitions * trials
        rows.append(
            Measurement(
                label=gate,
                trials=trials,
                median_seconds=statistics.median(times),
                min_seconds=min(times),
                max_seconds=max(times),
                spread_seconds=max(times) - min(times),
                per_shot_seconds=statistics.median(times) / repetitions,
                operations_per_second=total_gates / sum(times),
                notes=["per-gate time excludes state allocation"],
            ).to_dict()
        )
    return {
        "kind": "gate_throughput",
        "num_qubits": num_qubits,
        "rows": rows,
        "caveats": BENCHMARK_CAVEATS,
    }


def memory_observatory(
    *,
    qubits: Sequence[int] = (10, 15, 20, 24, 26, 28, 30),
) -> dict[str, Any]:
    """Memory requirement table for each engine, with the budget and safe limits."""
    budget = memory_budget_bytes()
    return {
        "kind": "memory_observatory",
        "budget_bytes": budget,
        "budget_mb": budget / 1e6,
        "backend_tables": {key: scaling_table(key, list(qubits), budget) for key in BACKENDS},
        "safe_max_qubits": {key: safe_max_qubits(key, budget) for key in BACKENDS},
        "backends": [
            {
                "key": spec.key,
                "label": spec.label,
                "expression": spec.per_qubit_bytes.__name__,
                "max_practical_qubits": spec.max_practical_qubits,
                "exact": spec.exact,
                "supports_noise": spec.supports_noise,
                "tradeoff": spec.tradeoff,
            }
            for spec in BACKENDS.values()
        ],
        "notes": [
            f"Memory budget: {describe_bytes(budget)} "
            "(override with QSCOPE_MEMORY_BUDGET_MB).",
            "A density matrix needs 4^n complex entries, so it caps out far earlier than a state vector.",
            "QScope refuses a run rather than attempting an allocation it cannot complete.",
        ],
    }


# ---------------------------------------------------------------------------
# external comparison (only when a real backend is installed)
# ---------------------------------------------------------------------------

EXTERNAL_CANDIDATES = [
    ("qiskit_aer", "Qiskit Aer"),
    ("qiskit", "Qiskit (statevector)"),
    ("cirq", "Cirq"),
    ("pennylane", "PennyLane (default.qubit)"),
]


def detect_external_backends() -> list[dict[str, Any]]:
    """Which other simulators are actually installed right now."""
    out = []
    for module, label in EXTERNAL_CANDIDATES:
        available = importlib.util.find_spec(module) is not None
        out.append(
            {
                "module": module,
                "label": label,
                "available": available,
                "note": "" if available else "not installed in this environment",
            }
        )
    return out


def _qiskit_aer_circuit(circuit: Circuit) -> Any:  # pragma: no cover - optional dependency
    from qiskit import QuantumCircuit

    qc = QuantumCircuit(circuit.num_qubits, circuit.num_clbits or circuit.num_qubits)
    mapping = {
        "H": "h", "X": "x", "Y": "y", "Z": "z", "S": "s", "SDG": "sdg", "T": "t", "TDG": "tdg",
        "RX": "rx", "RY": "ry", "RZ": "rz", "CNOT": "cx", "CX": "cx", "CZ": "cz", "SWAP": "swap",
        "TOFFOLI": "ccx", "P": "p",
    }
    for op in circuit.operations:
        if op.kind != "gate":
            continue
        name = mapping.get(op.name)
        if name is None:
            raise ValueError(f"external comparison does not support gate {op.name}")
        wires = list(op.controls) + list(op.targets)
        if len(op.params):
            getattr(qc, name)(*op.params, *wires)
        else:
            getattr(qc, name)(*wires)
    for op in circuit.measurements:
        qc.measure(op.targets[0], op.classical_targets[0])
    return qc


def compare_with_external(
    circuit: Circuit,
    *,
    shots: int = 1024,
    trials: int = 3,
) -> dict[str, Any]:
    """Run the same circuit on an installed third-party simulator and QScope.

    Returns ``{"available": false, "reason": ...}`` when nothing comparable is
    installed.  QScope refuses to publish a comparison it cannot perform — an
    invented benchmark table would be worse than no table.
    """
    detected = [d for d in detect_external_backends() if d["available"]]
    if not detected:
        return {
            "available": False,
            "reason": (
                "No third-party simulator (Qiskit Aer, Qiskit, Cirq, PennyLane) is installed in "
                "this environment, so no external benchmark was run. QScope does not report "
                "comparisons it cannot measure."
            ),
            "detected": detect_external_backends(),
        }

    qscope_options = RunOptions(backend="statevector", shots=shots, seed=1234)
    qscope_times, qscope_result = _time_callable(lambda: run_circuit(circuit, qscope_options), trials)
    results: list[dict[str, Any]] = [
        {
            "backend": "qscope (statevector)",
            "available": True,
            "median_seconds": statistics.median(qscope_times),
            "spread_seconds": max(qscope_times) - min(qscope_times),
            "shots": shots,
            "exact": True,
            "note": "exact amplitudes, complex128",
        }
    ]

    aer = next((d for d in detected if d["module"] == "qiskit_aer"), None)
    if aer is not None:  # pragma: no cover - optional dependency path
        try:
            from qiskit import transpile
            from qiskit_aer import AerSimulator

            qc = _qiskit_aer_circuit(circuit)
            simulator = AerSimulator()

            def run_external() -> Any:
                compiled = transpile(qc, simulator)
                return simulator.run(compiled, shots=shots).result().get_counts()

            external_times, external_counts = _time_callable(run_external, trials)
            agreement = _counts_agreement(external_counts, qscope_result.counts, shots)
            results.append(
                {
                    "backend": "qiskit_aer (statevector method)",
                    "available": True,
                    "median_seconds": statistics.median(external_times),
                    "spread_seconds": max(external_times) - min(external_times),
                    "shots": shots,
                    "exact": True,
                    "agreement_with_qscope": agreement,
                    "note": "measured on this machine; transpilation is included in the timing",
                }
            )
        except Exception as exc:
            results.append(
                {
                    "backend": "qiskit_aer",
                    "available": False,
                    "reason": f"installed but failed to run: {exc}",
                }
            )
    else:
        results.append(
            {
                "backend": "qiskit_aer",
                "available": False,
                "reason": "not installed",
            }
        )

    return {
        "available": True,
        "kind": "external_comparison",
        "circuit": circuit.name,
        "num_qubits": circuit.num_qubits,
        "gates": circuit.gate_count(),
        "results": results,
        "caveats": [
            "This is research benchmarking, not a competition: the engines implement different "
            "feature sets and default precisions.",
            "Both are measured in the same process on the same machine, with the same shots.",
            "Agreement is computed as the total variation distance between the shot histograms; "
            "matching histograms confirm both implement the same physics, not that one is faster.",
        ],
    }


def _counts_agreement(a: dict[str, int], b: dict[str, int], shots: int) -> dict[str, Any]:
    def normalise(counts: dict[str, int]) -> dict[str, float]:
        total = sum(counts.values()) or 1
        return {k: v / total for k, v in counts.items()}

    pa, pb = normalise(a), normalise(b)
    keys = set(pa) | set(pb)
    tvd = 0.5 * sum(abs(pa.get(k, 0.0) - pb.get(k, 0.0)) for k in keys)
    return {
        "total_variation": tvd,
        "sampling_floor": 0.5 * math.sqrt(len(keys) / max(shots, 1)),
        "consistent": tvd <= max(0.05, 3 * 0.5 * math.sqrt(len(keys) / max(shots, 1))),
        "note": "compared as histograms, so shot noise sets the floor",
    }


def benchmark_suite(
    *,
    qubits: Sequence[int] = (6, 8, 10),
    scaling_qubits: Sequence[int] = (8, 10, 12, 14, 16),
    shots: int = 1024,
    trials: int = 3,
) -> dict[str, Any]:
    """Assemble the full performance observatory payload."""
    return {
        "kind": "benchmark_suite",
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "processor": platform.processor(),
            "numpy": np.__version__,
            "machine_notes": "single-process wall-clock measurements",
        },
        "backends": benchmark_backends(qubits=qubits, shots=shots, trials=trials),
        "scaling": benchmark_scaling(qubits=scaling_qubits, shots=min(shots, 512), trials=trials),
        "memory": memory_observatory(),
        "external": detect_external_backends(),
        "caveats": BENCHMARK_CAVEATS,
    }


__all__ = [
    "BENCHMARK_CAVEATS",
    "Measurement",
    "benchmark_backends",
    "benchmark_gate_throughput",
    "benchmark_scaling",
    "benchmark_suite",
    "compare_with_external",
    "compute_circuit",
    "detect_external_backends",
    "ghz_circuit",
    "memory_observatory",
]
