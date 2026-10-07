"""The Quantum Time Machine: gate-by-gate execution tracing.

Tracing is deliberately *precomputed*.  A user wants to scrub backwards and
forwards instantly, and re-evolving the circuit for every scrub would make the
debugger feel broken.  So a trace run walks the circuit once, keeps a snapshot of
the state after every operation, and then every "step" is an array index.

What each step records:

* the operation (gate, targets, controls, parameters, kind),
* the execution time of that operation,
* the full state snapshot (bounded by ``term_limit`` so a 20-qubit trace stays
  transferable over the API),
* a Quantum Diff against the previous step,
* metrics before/after (purity, entropy, entanglement status and — when
  affordable — pairwise concurrence).

Cost control is explicit: ``depth`` selects how much analysis to run per step,
because pairwise entanglement on every step of a large circuit is the only part
that is genuinely expensive.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Iterator, Sequence

import numpy as np

from qscope.circuit.circuit import Circuit, Operation
from qscope.core.statevector import StateVector
from qscope.core.tensor import basis_label
from qscope.debugger.state_diff import diff_states
from qscope.simulator.noise import NoiseModel

TRACE_FAST = "fast"
TRACE_STANDARD = "standard"
TRACE_FULL = "full"

ENTANGLEMENT_PAIR_LIMIT = 8
"""Above this qubit count a per-step pairwise entanglement sweep is skipped."""


@dataclass
class TraceStep:
    """One operation of the circuit, with the state around it."""

    index: int
    operation: dict[str, Any]
    kind: str
    name: str
    display: str
    targets: list[int]
    controls: list[int]
    params: list[float]
    layer: int
    seconds: float
    cumulative_seconds: float
    state: dict[str, Any]
    state_before: dict[str, Any]
    diff: dict[str, Any]
    metrics: dict[str, Any]
    probabilities: dict[str, float]
    measurement: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "operation": self.operation,
            "kind": self.kind,
            "name": self.name,
            "display": self.display,
            "targets": self.targets,
            "controls": self.controls,
            "params": self.params,
            "layer": self.layer,
            "seconds": self.seconds,
            "cumulative_seconds": self.cumulative_seconds,
            "state": self.state,
            "state_before": self.state_before,
            "diff": self.diff,
            "metrics": self.metrics,
            "probabilities": self.probabilities,
            "measurement": self.measurement,
        }


@dataclass
class TraceResult:
    """The complete trace, indexable like a film strip."""

    circuit_name: str
    num_qubits: int
    depth_mode: str
    steps: list[TraceStep]
    initial_state: dict[str, Any]
    final_state: dict[str, Any]
    total_seconds: float
    n_operations: int
    layers: list[list[int]]
    warnings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def step(self, index: int) -> TraceStep:
        """Step ``index`` (0-based over operations); ``-1`` returns the last step."""
        if not self.steps:
            raise IndexError("this circuit has no operations to trace")
        return self.steps[index % len(self.steps)]

    def state_at(self, index: int) -> dict[str, Any]:
        """State *after* ``index`` operations (``-1`` = initial state)."""
        if index < 0:
            return self.initial_state
        return self.steps[min(index, len(self.steps) - 1)].state

    def __iter__(self) -> Iterator[TraceStep]:
        return iter(self.steps)

    def __len__(self) -> int:
        return len(self.steps)

    def summary(self) -> dict[str, Any]:
        slowest = max(self.steps, key=lambda s: s.seconds, default=None)
        biggest = max(
            self.steps,
            key=lambda s: s.diff.get("total_variation", 0.0),
            default=None,
        )
        entangling = [
            s for s in self.steps if s.diff.get("entanglement") and s.diff["entanglement"]["transition"] == "NONE → DETECTED"
        ]
        return {
            "circuit": self.circuit_name,
            "num_qubits": self.num_qubits,
            "steps": len(self.steps),
            "layers": len(self.layers),
            "total_seconds": self.total_seconds,
            "slowest_operation": {
                "index": slowest.index,
                "display": slowest.display,
                "seconds": slowest.seconds,
            }
            if slowest
            else None,
            "largest_state_change": {
                "index": biggest.index,
                "display": biggest.display,
                "total_variation": biggest.diff.get("total_variation"),
            }
            if biggest
            else None,
            "entanglement_created_at": [
                {"index": s.index, "display": s.display, "targets": s.targets, "max_concurrence": s.diff["entanglement"]["max_concurrence_after"]}
                for s in entangling
            ],
            "final_entanglement_status": self.final_state.get("entanglement_status"),
            "warnings": self.warnings,
            "notes": self.notes,
        }

    def to_dict(self, max_steps: int | None = None) -> dict[str, Any]:
        steps = self.steps if max_steps is None else self.steps[:max_steps]
        return {
            "circuit_name": self.circuit_name,
            "num_qubits": self.num_qubits,
            "depth_mode": self.depth_mode,
            "initial_state": self.initial_state,
            "final_state": self.final_state,
            "total_seconds": self.total_seconds,
            "n_operations": self.n_operations,
            "layers": self.layers,
            "steps": [s.to_dict() for s in steps],
            "truncated": max_steps is not None and max_steps < len(self.steps),
            "summary": self.summary(),
            "warnings": self.warnings,
            "notes": self.notes,
        }


def _state_dict(state: StateVector, term_limit: int, include_metrics: bool) -> dict[str, Any]:
    out = state.to_dict(term_limit=term_limit)
    if include_metrics:
        out["entanglement_status"] = _entanglement_status(state)
    return out


def _entanglement_status(state: StateVector) -> str:
    if state.num_qubits < 2:
        return "NOT APPLICABLE (single qubit)"
    worst = max(state.entanglement_entropy([q]) for q in range(state.num_qubits))
    return "ENTANGLED" if worst > 1e-9 else "SEPARABLE"


def _step_metrics(state: StateVector, mode: str) -> dict[str, Any]:
    """Per-step metrics at the requested analysis depth."""
    metrics: dict[str, Any] = {
        "num_qubits": state.num_qubits,
        "purity": state.purity(),
        "entropy": state.entropy(),
        "norm": state.norm(),
        "dominant_basis": state.dominant_basis(),
        "dominant_probability": float(np.max(state.probabilities())),
        "support_size": state.nonzero_count(),
        "entanglement_status": _entanglement_status(state),
        "bloch": [b.to_dict() for b in state.bloch_vectors()],
    }
    if mode == TRACE_FAST:
        return metrics
    per_qubit = [
        {"qubit": q, "entanglement_entropy": state.entanglement_entropy([q])}
        for q in range(state.num_qubits)
    ]
    metrics["per_qubit_entropy"] = per_qubit
    metrics["max_bipartite_entropy"] = max((e["entanglement_entropy"] for e in per_qubit), default=0.0)
    if mode == TRACE_FULL and state.num_qubits <= ENTANGLEMENT_PAIR_LIMIT:
        from qscope.analysis.entanglement import pairwise_concurrence

        pairs = pairwise_concurrence(state)
        metrics["pairwise_concurrence"] = pairs["matrix"]
        metrics["pairs"] = pairs["pairs"]
        metrics["max_concurrence"] = max((p["concurrence"] for p in pairs["pairs"]), default=0.0)
    return metrics


def trace_circuit(
    circuit: Circuit,
    *,
    depth: str = TRACE_STANDARD,
    term_limit: int = 32,
    max_steps: int | None = None,
    analyze_last_only: bool = False,
) -> TraceResult:
    """Run a circuit gate by gate and return every intermediate state.

    ``depth``:
      ``fast``     — snapshots, diffs and cheap metrics (purity, bloch, status).
      ``standard`` — plus per-qubit entanglement entropy (the default).
      ``full``     — plus pairwise concurrence up to
                     :data:`ENTANGLEMENT_PAIR_LIMIT` qubits.

    Measurement operations collapse the traced state exactly as they would in a
    real run (a fixed seed makes the trace reproducible).
    """
    if depth not in (TRACE_FAST, TRACE_STANDARD, TRACE_FULL):
        raise ValueError(f"unknown trace depth {depth!r}")
    ops = list(circuit.operations)
    if max_steps is not None:
        ops = ops[:max_steps]
    warnings: list[str] = []
    notes: list[str] = []
    if circuit.num_qubits > 20:
        warnings.append(
            f"Tracing {circuit.num_qubits} qubits keeps {2 ** circuit.num_qubits:,} amplitudes per "
            "step; consider depth='fast' or fewer qubits."
        )
    if depth == TRACE_FULL and circuit.num_qubits > ENTANGLEMENT_PAIR_LIMIT:
        notes.append(
            f"Pairwise concurrence is only computed up to {ENTANGLEMENT_PAIR_LIMIT} qubits; "
            "per-qubit entanglement entropy was used instead."
        )

    rng = np.random.default_rng(20260101)
    state = StateVector(circuit.num_qubits)
    initial = _state_dict(state, term_limit, True)
    layers = circuit.layers()
    layer_of: dict[int, int] = {}
    for layer_index, layer in enumerate(layers):
        for op_index in layer:
            layer_of[op_index] = layer_index

    steps: list[TraceStep] = []
    cumulative = 0.0
    started_all = time.perf_counter()
    previous = state.copy()

    for index, op in enumerate(ops):
        before = previous
        started = time.perf_counter()
        measurement: dict[str, Any] | None = None
        if op.kind == "gate":
            if op.controls:
                state.apply_controlled(op.name, op.controls, op.targets, op.params)
            else:
                state.apply_gate(op.name, op.targets, op.params)
        elif op.kind == "measure":
            outcome = state.measure_qubit(op.targets[0], rng)
            measurement = outcome.to_dict()
            measurement["classical_target"] = op.classical_targets[0] if op.classical_targets else None
        elif op.kind == "reset":
            from qscope.simulator.simulator import reset_statevector

            state = reset_statevector(state, op.targets[0])
        elapsed = time.perf_counter() - started
        cumulative += elapsed

        if before is not state:
            before_snapshot = before
        else:  # pragma: no cover - defensive
            before_snapshot = state.copy()

        diff = diff_states(before_snapshot, state)
        steps.append(
            TraceStep(
                index=index,
                operation=op.to_dict(),
                kind=op.kind,
                name=op.name,
                display=op.display,
                targets=list(op.targets),
                controls=list(op.controls),
                params=list(op.params),
                layer=layer_of.get(index, 0),
                seconds=elapsed,
                cumulative_seconds=cumulative,
                state=_state_dict(state, term_limit, True),
                state_before=_state_dict(before_snapshot, term_limit, True),
                diff=diff,
                metrics=_step_metrics(state, depth),
                probabilities={
                    basis_label(circuit.num_qubits, i): float(p)
                    for i, p in enumerate(state.probabilities())
                    if p > 1e-12
                },
                measurement=measurement,
            )
        )
        previous = state.copy()

    total = time.perf_counter() - started_all
    final_state = _state_dict(state, term_limit, True)
    final_state["entanglement_status"] = _entanglement_status(state)
    return TraceResult(
        circuit_name=circuit.name,
        num_qubits=circuit.num_qubits,
        depth_mode=depth,
        steps=steps,
        initial_state=initial,
        final_state=final_state,
        total_seconds=total,
        n_operations=len(circuit.operations),
        layers=layers,
        warnings=warnings,
        notes=notes,
    )


def replay_states(
    circuit: Circuit,
    *,
    term_limit: int = 16,
) -> list[dict[str, Any]]:
    """Lightweight snapshots only (no diffs/metrics) for smooth replay."""
    trace = trace_circuit(circuit, depth=TRACE_FAST, term_limit=term_limit)
    return [trace.initial_state, *[s.state for s in trace.steps]]


def states_at(circuit: Circuit, indices: Sequence[int]) -> list[dict[str, Any]]:
    """Snapshots for arbitrary operation indices (used by the test suite)."""
    result = trace_circuit(circuit, depth=TRACE_FAST)
    return [result.state_at(i) for i in indices]


__all__ = [
    "ENTANGLEMENT_PAIR_LIMIT",
    "TRACE_FAST",
    "TRACE_FULL",
    "TRACE_STANDARD",
    "TraceResult",
    "TraceStep",
    "Operation",
    "replay_states",
    "states_at",
    "trace_circuit",
]
