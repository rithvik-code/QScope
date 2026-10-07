"""The metrics engine.

Every number QScope displays is produced here (or by the sibling modules
``fidelity``, ``entropy``, ``entanglement``), and every number carries its
formula in :data:`METRIC_DEFINITIONS`.  The UI reads that glossary directly, so a
metric can never appear on screen without an explanation of what it means and
where it breaks down.
"""

from __future__ import annotations

from typing import Any, Sequence

import numpy as np

from qscope.analysis import entropy as entropy_mod
from qscope.analysis.entanglement import entanglement_report
from qscope.core.density import DensityMatrix
from qscope.core.measurement import marginal_probabilities
from qscope.core.statevector import StateVector
from qscope.core.tensor import basis_label

MAX_ENTANGLEMENT_PAIRS = 28
"""Above this many pairs the pairwise concurrence sweep is skipped (cost is quadratic)."""

ENUMERABLE_ENTANGLEMENT_QUBITS = 10
"""Bipartition enumeration is exponential in ``n``; beyond this we report single-qubit cuts."""

METRIC_DEFINITIONS: dict[str, dict[str, str]] = {
    "purity": {
        "formula": "Tr(rho^2)",
        "meaning": "How close the state is to a pure state.",
        "range": "1/2^n (maximally mixed) to 1 (pure)",
        "caveat": "A pure state can still be maximally entangled; purity is not entanglement.",
    },
    "entropy": {
        "formula": "S = -Tr(rho log2 rho)",
        "meaning": "Von Neumann entropy: missing information about the state.",
        "range": "0 (pure) to n bits (maximally mixed)",
        "caveat": "For a state vector this is exactly 0 by construction.",
    },
    "linear_entropy": {
        "formula": "1 - Tr(rho^2)",
        "meaning": "First-order approximation of entropy, cheap to evaluate.",
        "range": "0 to 1 - 1/2^n",
        "caveat": "Not additive; use von Neumann entropy for information-theoretic statements.",
    },
    "entanglement_entropy": {
        "formula": "S(rho_A) with rho_A = Tr_B |psi><psi|",
        "meaning": "Entanglement across the A|B cut, in bits.",
        "range": "0 (product) to min(|A|,|B|) (maximally entangled)",
        "caveat": "Exact only for pure global states.",
    },
    "concurrence": {
        "formula": "C = max(0, l1-l2-l3-l4), l_i = sqrt(eig(rho (Y⊗Y) rho* (Y⊗Y)))",
        "meaning": "Two-qubit entanglement (Wootters), faithful for 2 qubits.",
        "range": "0 (separable) to 1 (maximally entangled)",
        "caveat": "Only defined for two-qubit states; on reduced states it can vanish while "
        "the global state is entangled.",
    },
    "negativity": {
        "formula": "(||rho^{T_A}||_1 - 1) / 2",
        "meaning": "Entanglement witness from the partial transpose.",
        "range": "0 to (d-1)/2",
        "caveat": "Zero does not prove separability (bound entanglement is invisible).",
    },
    "fidelity": {
        "formula": "(Tr sqrt(sqrt(rho) sigma sqrt(rho)))^2",
        "meaning": "Overlap between an ideal reference and the produced state.",
        "range": "0 to 1",
        "caveat": "A high state fidelity does not guarantee a correct measurement outcome.",
    },
    "trace_distance": {
        "formula": "0.5 ||rho - sigma||_1",
        "meaning": "How distinguishable two states are in the best case.",
        "range": "0 to 1",
        "caveat": "For pure states it equals sqrt(1 - fidelity).",
    },
    "total_variation": {
        "formula": "0.5 sum_i |p_i - q_i|",
        "meaning": "Classical distance between two measurement distributions.",
        "range": "0 to 1",
        "caveat": "Depends on shot noise; compare with the expected statistical error.",
    },
    "depth": {
        "formula": "number of sequential layers after scheduling",
        "meaning": "How long the circuit takes on a device that can run disjoint gates in parallel.",
        "range": ">= 1",
        "caveat": "Depends on the assumed connectivity; routing can add SWAP layers.",
    },
    "gate_count": {
        "formula": "number of unitary operations",
        "meaning": "Raw instruction count.",
        "range": ">= 0",
        "caveat": "Native gate sets differ, so gate counts are only comparable within one device.",
    },
    "t_count": {
        "formula": "count of T / T-dagger gates",
        "meaning": "Cost proxy for fault-tolerant execution (magic-state distillation).",
        "range": ">= 0",
        "caveat": "Irrelevant for near-term NISQ estimates.",
    },
    "participation_ratio": {
        "formula": "1 / sum_i p_i^2",
        "meaning": "Effective number of occupied basis states.",
        "range": "1 to 2^n",
        "caveat": "A descriptive statistic, not a quantum information measure.",
    },
    "operations_per_second": {
        "formula": "operations / wall-clock seconds",
        "meaning": "Throughput of the engine on this machine for this circuit.",
        "range": "> 0",
        "caveat": "Python and NumPy bound; not a hardware claim.",
    },
    "coherence_l1": {
        "formula": "sum_{i != j} |rho_ij|",
        "meaning": "Total off-diagonal weight: how much phase coherence survives.",
        "range": "0 to 2^n - 1",
        "caveat": "Basis dependent (here: the computational basis).",
    },
}


def metric_glossary() -> list[dict[str, str]]:
    """Glossary rows for the UI/API."""
    return [{"key": k, **v} for k, v in METRIC_DEFINITIONS.items()]


def state_metrics(
    state: StateVector | DensityMatrix,
    measured: Sequence[int] | None = None,
    *,
    include_entanglement: bool = True,
    term_limit: int = 64,
) -> dict[str, Any]:
    """Metrics bundle for a final state (pure or mixed).

    Large states are handled by *not* computing what would be ruinous: the
    pairwise entanglement sweep is skipped above
    :data:`MAX_ENTANGLEMENT_PAIRS` pairs, and bipartition enumeration above
    :data:`ENUMERABLE_ENTANGLEMENT_QUBITS` qubits, with the omission recorded in
    ``omitted`` so a report can never imply a full analysis it did not run.
    """
    n = state.num_qubits
    pure = isinstance(state, StateVector)
    omitted: list[str] = []

    if pure:
        probs = state.normalized_probabilities()
        amplitudes = [
            {
                "basis": basis_label(n, int(i)),
                "real": float(state.data[i].real),
                "imag": float(state.data[i].imag),
                "magnitude": float(abs(state.data[i])),
                "probability": float(probs[i]),
                "phase": float(np.angle(state.data[i])),
            }
            for i in np.argsort(probs)[::-1][:term_limit]
            if probs[i] > 1e-12
        ]
        support = state.nonzero_count()
        purity_value = state.purity()
        entropy_value = 0.0
        linear = 0.0
    else:
        probs = state.probabilities()
        amplitudes = [
            {
                "basis": basis_label(n, int(i)),
                "real": float(np.sqrt(max(probs[i], 0.0))),
                "imag": 0.0,
                "magnitude": float(np.sqrt(max(probs[i], 0.0))),
                "probability": float(probs[i]),
                "phase": 0.0,
            }
            for i in np.argsort(probs)[::-1][:term_limit]
            if probs[i] > 1e-12
        ]
        support = int(np.sum(np.real(np.diag(state.data)) > 1e-9))
        purity_value = state.purity()
        entropy_value = state.entropy()
        linear = state.linear_entropy()

    ensemble = {basis_label(n, int(i)): float(p) for i, p in enumerate(probs) if p > 1e-12}
    measured_probs = (
        marginal_probabilities(probs, n, list(measured)) if measured else {}
    )

    bloch = [b.to_dict() for b in state.bloch_vectors()]
    top = max(ensemble.items(), key=lambda kv: kv[1]) if ensemble else ("", 0.0)

    metrics: dict[str, Any] = {
        "num_qubits": n,
        "representation": "density_matrix" if not pure else "statevector",
        "is_pure": bool(pure or (not pure and state.is_pure(1e-8))),
        "purity": purity_value,
        "entropy": entropy_value,
        "linear_entropy": linear,
        "max_entropy": float(n),
        "normalized_entropy": entropy_value / n if n else 0.0,
        "support_size": support,
        "participation_ratio": entropy_mod.participation_ratio(probs),
        "dominant_basis": top[0],
        "dominant_probability": float(top[1]),
        "probability_distribution": [
            {"basis": k, "probability": v}
            for k, v in sorted(ensemble.items(), key=lambda kv: (-kv[1], kv[0]))
        ],
        "measured_probabilities": measured_probs,
        "measured_qubits": list(measured or []),
        "amplitudes": amplitudes,
        "bloch": bloch,
        "bloch_lengths": [b["length"] for b in bloch],
        "coherence_l1": _coherence(state),
        "pauli_expectations": _pauli_expectations(state, n),
        "omitted": omitted,
    }

    if include_entanglement and n >= 2:
        if n * (n - 1) // 2 > MAX_ENTANGLEMENT_PAIRS:
            omitted.append(
                f"pairwise entanglement skipped: {n * (n - 1) // 2} pairs would take "
                f"too long; using single-qubit cuts only"
            )
            report = _single_cut_entanglement(state, n)
        else:
            report = entanglement_report(state)
        metrics["entanglement"] = report
        metrics["entanglement_status"] = report.get("status")
        metrics["entangled"] = report.get("status") in ("ENTANGLED", "ENTANGLED (witnessed)")
        metrics["entanglement_limitations"] = report.get("limitations", [])
    else:
        metrics["entanglement"] = None

    return metrics


def _single_cut_entanglement(state: Any, n: int) -> dict[str, Any]:
    """Cheap fallback: entropy of each qubit against the rest plus pairwise matrix."""
    per_qubit = []
    for q in range(n):
        value = state.entanglement_entropy([q])
        per_qubit.append({"qubit": q, "entanglement_entropy": float(value), "entangled_with_rest": value > 1e-9})
    warmup = max((p["entanglement_entropy"] for p in per_qubit), default=0.0)
    return {
        "num_qubits": n,
        "method": "per-qubit entropy against the rest (scalable fallback)",
        "status": "ENTANGLED" if warmup > 1e-9 else "SEPARABLE",
        "summary": (
            f"At least one qubit is entangled with the rest (max entropy {warmup:.4f} bits)."
            if warmup > 1e-9
            else "Every qubit is in a product state with the rest."
        ),
        "per_qubit_entropy": per_qubit,
        "max_bipartite_entropy": float(warmup),
        "pairs": [],
        "edges": [],
        "max_concurrence": 0.0,
        "limitations": [
            "Pairwise concurrence was skipped for this state size; per-qubit entropy detects "
            "entanglement with the rest but does not identify which partner created it."
        ],
    }


def _coherence(state: Any) -> float:
    if isinstance(state, DensityMatrix):
        return float(np.sum(np.abs(state.data)) - np.sum(np.abs(np.diag(state.data))))
    return 0.0


def _pauli_expectations(state: Any, n: int, limit: int = 8) -> dict[str, float]:
    """Single-qubit Pauli expectations ``<X_i>, <Y_i>, <Z_i>`` (skip at large n)."""
    if n > limit:
        return {}
    out: dict[str, float] = {}
    for q in range(n):
        for pauli in "XYZ":
            string = "".join(pauli if i == q else "I" for i in range(n))
            out[f"{pauli}{q}"] = float(state.expectation_pauli(string))
    return out


def probability_distance(p: dict[str, float], q: dict[str, float]) -> float:
    """Total variation distance between two measurement distributions."""
    from qscope.analysis.fidelity import total_variation

    return total_variation(p, q)


def circuit_metrics(circuit: Any) -> dict[str, Any]:
    """Circuit-level metrics (independent of any execution)."""
    resources = circuit.resources()
    gates = max(resources["gates"], 1)
    depth = max(resources["depth"], 1)
    resources.update(
        {
            "gate_density": gates / depth,
            "entangling_ratio": resources["two_qubit_gates"] / gates,
            "measurement_ratio": resources["measurements"] / max(resources["operations"], 1),
            "parameter_count": len(resources["parameters"]),
            "clifford": resources["is_clifford"],
            "estimated_error_budget": None,
        }
    )
    return resources


def compare_metrics(a: dict[str, Any], b: dict[str, Any], keys: Sequence[str] | None = None) -> dict[str, Any]:
    """Side-by-side comparison with signed deltas and a verdict.

    The verdict only claims what the numbers support: it never says one circuit is
    "better" on a metric that does not apply to both.
    """
    keys = keys or [
        "purity",
        "entropy",
        "participation_ratio",
        "dominant_probability",
        "coherence_l1",
    ]
    rows = []
    for key in keys:
        va, vb = a.get(key), b.get(key)
        if va is None or vb is None:
            continue
        delta = float(vb) - float(va)
        rows.append(
            {
                "metric": key,
                "a": float(va),
                "b": float(vb),
                "delta": delta,
                "direction": "increase" if delta > 0 else "decrease" if delta < 0 else "unchanged",
            }
        )
    verdict: list[str] = []
    for row in rows:
        if abs(row["delta"]) < 1e-9:
            continue
        verdict.append(
            f"{row['metric']} {'increases' if row['delta'] > 0 else 'decreases'} by "
            f"{abs(row['delta']):.4g} from A to B."
        )
    return {"rows": rows, "verdict": verdict}


def summarize_result(result: Any) -> dict[str, Any]:
    """Compact metric digest of a :class:`~qscope.simulator.simulator.SimulationResult`."""
    metrics = result.metrics or {}
    return {
        "backend": result.backend,
        "mode": result.mode,
        "shots": result.shots,
        "qubits": metrics.get("num_qubits"),
        "purity": metrics.get("purity"),
        "entropy": metrics.get("entropy"),
        "dominant_basis": metrics.get("dominant_basis"),
        "dominant_probability": metrics.get("dominant_probability"),
        "fidelity_vs_ideal": result.fidelity_vs_ideal,
        "runtime_seconds": result.timing.get("total_seconds"),
        "entanglement_status": metrics.get("entanglement_status"),
        "max_concurrence": (metrics.get("entanglement") or {}).get("max_concurrence"),
        "depth": result.circuit.get("resources", {}).get("depth") if isinstance(result.circuit, dict) else None,
    }


__all__ = [
    "ENUMERABLE_ENTANGLEMENT_QUBITS",
    "MAX_ENTANGLEMENT_PAIRS",
    "METRIC_DEFINITIONS",
    "circuit_metrics",
    "compare_metrics",
    "metric_glossary",
    "probability_distance",
    "state_metrics",
    "summarize_result",
]
