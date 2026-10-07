"""Quantum Diff — what exactly did that gate change?

A gate in a textbook is a matrix.  In a running circuit it is a specific edit to
the amplitude vector, and this module makes that edit explicit:

* amplitude moves (real/imag/magnitude) per basis state,
* probability moves per basis state,
* phase rotations, including the mean phase shift the gate imposed,
* which qubits' Bloch vectors actually moved,
* what happened to the entanglement structure between every qubit pair.

Everything is exact (state vectors) — no approximations are introduced here, and
any measure that is not reliable for the state at hand is reported with its
limitation instead of being dropped.
"""

from __future__ import annotations

from typing import Any, Sequence

import numpy as np

from qscope.analysis.entanglement import entanglement_change
from qscope.core.density import DensityMatrix
from qscope.core.statevector import StateVector
from qscope.core.tensor import COMPLEX, basis_label

CHANGE_TOL = 1e-9


def _probabilities(state: Any) -> np.ndarray:
    if isinstance(state, DensityMatrix):
        return state.probabilities()
    return state.normalized_probabilities()


def _terms(state: Any, labels: list[str]) -> dict[str, dict[str, float]]:
    """basis -> {real, imag, magnitude, probability, phase}."""
    out: dict[str, dict[str, float]] = {}
    if isinstance(state, StateVector):
        for i, label in enumerate(labels):
            amp = complex(state.data[i])
            out[label] = {
                "real": float(amp.real),
                "imag": float(amp.imag),
                "magnitude": float(abs(amp)),
                "probability": float(abs(amp) ** 2),
                "phase": float(np.angle(amp)),
            }
    else:
        probs = state.probabilities()
        for i, label in enumerate(labels):
            p = float(probs[i])
            out[label] = {
                "real": float(np.sqrt(max(p, 0.0))),
                "imag": 0.0,
                "magnitude": float(np.sqrt(max(p, 0.0))),
                "probability": p,
                "phase": 0.0,
            }
    return out


def _entanglement_light(state: Any) -> dict[str, Any]:
    """Cheap-but-exact entanglement snapshot for a pure state.

    ``max_q S([q]) > 0`` is *equivalent* to entanglement for a globally pure
    state (if no single qubit is entangled with the rest, every qubit factorises
    and the state is a product state).  Single-qubit entropies cost one SVD each,
    which is why the tracer can afford them on every step while a full
    bipartition sweep would be prohibitive.
    """
    n = state.num_qubits
    if n < 2:
        return {"status": "NOT APPLICABLE (single qubit)", "max_single_qubit_entropy": 0.0}
    entropies = [float(state.entanglement_entropy([q])) for q in range(n)]
    best = max(entropies, default=0.0)
    return {
        "status": "ENTANGLED" if best > 1e-9 else "SEPARABLE",
        "max_single_qubit_entropy": best,
        "entropies": entropies,
    }


def _entanglement_delta_light(before: Any, after: Any) -> dict[str, Any]:
    b = _entanglement_light(before)
    a = _entanglement_light(after)
    delta = a["max_single_qubit_entropy"] - b["max_single_qubit_entropy"]
    if b["status"].startswith("SEPARABLE") and a["status"].startswith("ENTANGLED"):
        transition = "NONE → DETECTED"
    elif b["status"].startswith("ENTANGLED") and a["status"].startswith("SEPARABLE"):
        transition = "DETECTED → NONE"
    else:
        transition = "UNCHANGED"
    return {
        "mode": "single-qubit entropies (exact for pure states)",
        "before_status": b["status"],
        "after_status": a["status"],
        "transition": transition,
        "max_entropy_before": b["max_single_qubit_entropy"],
        "max_entropy_after": a["max_single_qubit_entropy"],
        "max_concurrence_after": a["max_single_qubit_entropy"],
        "delta": delta,
        "per_qubit_before": b.get("entropies", []),
        "per_qubit_after": a.get("entropies", []),
        "limitations": [
            "Single-qubit entropy detects entanglement but does not identify the partner "
            "qubit; ask for the full entanglement report to get pairwise concurrence."
        ],
    }


def diff_states(
    before: Any,
    after: Any,
    *,
    threshold: float = CHANGE_TOL,
    top: int = 12,
    entanglement_detail: str = "light",
) -> dict[str, Any]:
    """Full diff between two states with matching qubit counts.

    ``entanglement_detail='light'`` (default) uses single-qubit entropies so that
    tracing a long circuit stays responsive; ``'full'`` runs the complete
    bipartition/witness analysis, which is what the observer UI requests when a
    user opens a specific step.
    """
    if entanglement_detail not in ("light", "full", "none"):
        raise ValueError("entanglement_detail must be 'light', 'full' or 'none'")
    if before.num_qubits != after.num_qubits:
        raise ValueError("diff_states requires states with the same qubit count")
    n = before.num_qubits
    labels = [basis_label(n, i) for i in range(2**n)]

    tb = _terms(before, labels)
    ta = _terms(after, labels)

    changes: list[dict[str, Any]] = []
    for label in labels:
        b, a = tb[label], ta[label]
        dp = a["probability"] - b["probability"]
        dmag = a["magnitude"] - b["magnitude"]
        phase_shift = float(np.angle(np.exp(1j * (a["phase"] - b["phase"])))) if b["magnitude"] > 1e-12 and a["magnitude"] > 1e-12 else 0.0
        if (
            abs(dp) > threshold
            or abs(dmag) > threshold
            or abs(a["real"] - b["real"]) > threshold
            or abs(a["imag"] - b["imag"]) > threshold
            or abs(phase_shift) > 1e-6
        ):
            changes.append(
                {
                    "basis": label,
                    "before": b,
                    "after": a,
                    "delta_probability": dp,
                    "delta_magnitude": dmag,
                    "delta_real": a["real"] - b["real"],
                    "delta_imag": a["imag"] - b["imag"],
                    "phase_shift": phase_shift,
                    "appeared": b["probability"] <= threshold and a["probability"] > threshold,
                    "vanished": b["probability"] > threshold and a["probability"] <= threshold,
                }
            )

    changes.sort(key=lambda c: abs(c["delta_probability"]), reverse=True)
    moved = [c for c in changes if abs(c["delta_probability"]) > threshold]

    pb, pa = _probabilities(before), _probabilities(after)
    total_variation = float(0.5 * np.sum(np.abs(pa - pb)))

    amp_l1 = float(np.sum(np.abs(_amplitudes(after) - _amplitudes(before)))) if isinstance(before, StateVector) else None
    amp_l2 = float(np.linalg.norm(_amplitudes(after) - _amplitudes(before))) if isinstance(before, StateVector) else None

    phase_changes = [abs(c["phase_shift"]) for c in changes if abs(c["phase_shift"]) > 1e-9]
    qubit_changes = _qubit_changes(before, after)

    result = {
        "num_qubits": n,
        "total_variation": total_variation,
        "amplitude_l1": amp_l1,
        "amplitude_l2": amp_l2,
        "changed_basis_states": len(moved),
        "appeared": [c["basis"] for c in changes if c["appeared"]][:top],
        "vanished": [c["basis"] for c in changes if c["vanished"]][:top],
        "largest_moves": changed_rows(changes, top),
        "probability_changes": [
            {
                "basis": c["basis"],
                "before": c["before"]["probability"],
                "after": c["after"]["probability"],
                "delta": c["delta_probability"],
            }
            for c in changes[:top]
        ],
        "qubit_changes": qubit_changes,
        "most_changed_qubit": max(qubit_changes, key=lambda q: q["bloch_delta"], default=None),
        "phase": {
            "mean_shift": float(np.mean(phase_changes)) if phase_changes else 0.0,
            "max_shift": float(np.max(phase_changes)) if phase_changes else 0.0,
            "shifted_states": len(phase_changes),
        },
        "entanglement": (
            None
            if entanglement_detail == "none"
            else entanglement_change(before, after)
            if entanglement_detail == "full"
            else _entanglement_delta_light(before, after)
        )
        if n >= 2
        else None,
        "entangled_before": _entangled(before),
        "entangled_after": _entangled(after),
    }
    result["summary"] = summarise_diff(result)
    return result


def _amplitudes(state: Any) -> np.ndarray:
    if isinstance(state, StateVector):
        return state.data
    return np.diag(state.data).astype(COMPLEX)


def _qubit_changes(before: Any, after: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    bb = before.bloch_vectors()
    ab = after.bloch_vectors()
    for q in range(before.num_qubits):
        delta = (ab[q].x - bb[q].x, ab[q].y - bb[q].y, ab[q].z - bb[q].z)
        out.append(
            {
                "qubit": q,
                "before": bb[q].to_dict(),
                "after": ab[q].to_dict(),
                "bloch_delta": float(np.sqrt(sum(d**2 for d in delta))),
                "length_delta": ab[q].length - bb[q].length,
            }
        )
    out.sort(key=lambda q: q["bloch_delta"], reverse=True)
    return out


def _entangled(state: Any) -> bool:
    """Exact for pure states (see :func:`_entanglement_light`), witness-based for mixed."""
    if state.num_qubits < 2:
        return False
    if isinstance(state, StateVector):
        return any(state.entanglement_entropy([q]) > 1e-9 for q in range(state.num_qubits))
    from qscope.analysis.entanglement import entanglement_report

    return entanglement_report(state).get("status") in ("ENTANGLED", "ENTANGLED (witnessed)")


def changed_rows(changes: list[dict[str, Any]], top: int) -> list[dict[str, Any]]:
    """Rows for the diff table: real/imag/magnitude/probability before and after."""
    rows = []
    for c in changes[:top]:
        rows.append(
            {
                "basis": c["basis"],
                "before": {
                    "real": c["before"]["real"],
                    "imag": c["before"]["imag"],
                    "magnitude": c["before"]["magnitude"],
                    "probability": c["before"]["probability"],
                    "phase": c["before"]["phase"],
                },
                "after": {
                    "real": c["after"]["real"],
                    "imag": c["after"]["imag"],
                    "magnitude": c["after"]["magnitude"],
                    "probability": c["after"]["probability"],
                    "phase": c["after"]["phase"],
                },
                "delta_probability": c["delta_probability"],
                "phase_shift": c["phase_shift"],
                "note": "created"
                if c["appeared"]
                else "annihilated"
                if c["vanished"]
                else "amplitude shifted",
            }
        )
    return rows


def summarise_diff(diff: dict[str, Any]) -> str:
    """One-sentence, data-grounded description of the diff."""
    bits: list[str] = []
    if diff["changed_basis_states"]:
        bits.append(
            f"{diff['changed_basis_states']} basis state(s) changed "
            f"(total variation {diff['total_variation']:.4f})"
        )
    if diff["appeared"]:
        bits.append(f"created {', '.join(diff['appeared'][:3])}")
    if diff["vanished"]:
        bits.append(f"annihilated {', '.join(diff['vanished'][:3])}")
    ent = diff.get("entanglement")
    if ent and ent["transition"] != "UNCHANGED":
        bits.append(f"entanglement {ent['transition']} (max concurrence {ent['max_concurrence_after']:.3f})")
    elif ent:
        bits.append(f"entanglement unchanged (max concurrence {ent['max_concurrence_after']:.3f})")
    if diff["phase"]["shifted_states"]:
        bits.append(
            f"{diff['phase']['shifted_states']} state(s) picked up phase "
            f"(mean {diff['phase']['mean_shift']:.4f} rad)"
        )
    top = diff.get("most_changed_qubit")
    if top and top["bloch_delta"] > 1e-9:
        bits.append(f"largest Bloch move on q{top['qubit']} ({top['bloch_delta']:.4f})")
    return "; ".join(bits) if bits else "no measurable change"


def quantum_diff(
    circuit: Any,
    index: int,
    *,
    backend: str = "statevector",
    threshold: float = CHANGE_TOL,
    entanglement_detail: str = "full",
) -> dict[str, Any]:
    """Diff the state immediately before and after operation ``index``.

    Uses the same evolution path as the simulator (measurements collapse for
    real), so the diff reflects what actually happens inside a run.
    """
    from qscope.simulator.noise import NoiseModel
    from qscope.simulator.simulator import simulate_shot

    if not 0 <= index < len(circuit.operations):
        raise IndexError(f"operation index {index} out of range")
    rng = np.random.default_rng(0)
    before_state, _, _ = simulate_shot(
        circuit, backend, NoiseModel.ideal(), rng, ops=list(circuit.operations[:index])
    )
    after_state, _, _ = simulate_shot(
        circuit, backend, NoiseModel.ideal(), rng, ops=list(circuit.operations[: index + 1])
    )
    op = circuit.operations[index]
    diff = diff_states(
        before_state, after_state, threshold=threshold, entanglement_detail=entanglement_detail
    )
    diff.update(
        {
            "operation_index": index,
            "operation": op.to_dict(),
            "gate": op.name,
            "display": op.display,
            "targets": list(op.qubits),
            "params": list(op.params),
        }
    )
    return diff


def diff_circuits(
    circuit_a: Any,
    circuit_b: Any,
    *,
    include_state: bool = True,
    options_a: Any = None,
    options_b: Any = None,
) -> dict[str, Any]:
    """Compare two circuits end to end: resources, output distribution, metrics.

    This is the engine behind Research Comparison Mode.  It runs both circuits
    with the same seed so that any difference in the histograms comes from the
    circuits (or their noise), not from the sampling.
    """
    from qscope.analysis.metrics import circuit_metrics
    from qscope.analysis.fidelity import total_variation
    from qscope.simulator.simulator import RunOptions, run_circuit

    result_a = run_circuit(circuit_a, options_a or RunOptions(shots=2048, seed=11))
    result_b = run_circuit(circuit_b, options_b or RunOptions(shots=2048, seed=11))

    res_a = circuit_metrics(circuit_a)
    res_b = circuit_metrics(circuit_b)
    keys = [
        "num_qubits",
        "gates",
        "depth",
        "two_qubit_gates",
        "multi_qubit_gates",
        "t_count",
        "measurements",
        "operations",
        "is_clifford",
    ]
    rows = []
    for key in keys:
        va, vb = res_a.get(key), res_b.get(key)
        if isinstance(va, bool) or isinstance(vb, bool):
            rows.append({"metric": key, "a": va, "b": vb, "delta": None})
            continue
        delta = (vb - va) if va is not None and vb is not None else None
        rows.append({"metric": key, "a": va, "b": vb, "delta": delta})
    perf_keys = ["total_seconds", "operations_per_second", "shots"]
    for key in perf_keys:
        va, vb = result_a.timing.get(key), result_b.timing.get(key)
        if va is None or vb is None:
            continue
        rows.append({"metric": f"runtime.{key}", "a": va, "b": vb, "delta": vb - va})

    metrics_rows = []
    for key in ("purity", "entropy", "dominant_probability", "participation_ratio", "support_size"):
        va, vb = result_a.metrics.get(key), result_b.metrics.get(key)
        if va is None or vb is None:
            continue
        metrics_rows.append({"metric": key, "a": va, "b": vb, "delta": float(vb) - float(va)})

    tvd = total_variation(result_a.sampled_probabilities, result_b.sampled_probabilities)

    verdict: list[str] = []
    gate_row = next((r for r in rows if r["metric"] == "gates"), None)
    depth_row = next((r for r in rows if r["metric"] == "depth"), None)
    if gate_row and gate_row["delta"] is not None and gate_row["delta"] != 0:
        verdict.append(
            f"B uses {abs(gate_row['delta']):.0f} {'more' if gate_row['delta'] > 0 else 'fewer'} gates."
        )
    if depth_row and depth_row["delta"] is not None and depth_row["delta"] != 0:
        verdict.append(
            f"B is {'deeper' if depth_row['delta'] > 0 else 'shallower'} by {abs(depth_row['delta']):.0f} layers."
        )
    if tvd < 0.05:
        verdict.append(f"Output distributions agree closely (total variation {tvd:.4f}).")
    else:
        verdict.append(
            f"Output distributions differ (total variation {tvd:.4f}); they are not the same computation."
        )
    if result_a.fidelity_vs_ideal is not None and result_b.fidelity_vs_ideal is not None:
        verdict.append(
            f"Fidelity vs the ideal state: A={result_a.fidelity_vs_ideal:.4f}, "
            f"B={result_b.fidelity_vs_ideal:.4f}."
        )

    out: dict[str, Any] = {
        "circuit_a": {"name": circuit_a.name, "resources": res_a},
        "circuit_b": {"name": circuit_b.name, "resources": res_b},
        "resource_rows": rows,
        "metric_rows": metrics_rows,
        "output_total_variation": tvd,
        "verdict": verdict,
        "a": {"counts": result_a.counts, "metrics": result_a.metrics, "timing": result_a.timing, "mode": result_a.mode},
        "b": {"counts": result_b.counts, "metrics": result_b.metrics, "timing": result_b.timing, "mode": result_b.mode},
    }
    if include_state:
        out["state_diff"] = diff_states(
            _final(result_a), _final(result_b)
        )
    return out


def _final(result: Any) -> Any:
    """Live final state of a :class:`SimulationResult` (serialised forms are lossy)."""
    state = getattr(result, "_state", None)
    if state is None:
        raise ValueError(
            "diff_circuits needs live simulation results (run with store_state=True, which is "
            "the default); serialised results do not carry the full density matrix"
        )
    return state


__all__ = [
    "CHANGE_TOL",
    "diff_circuits",
    "diff_states",
    "quantum_diff",
    "summarise_diff",
]
