"""Entanglement observatory: detection, quantification and honest limitations.

What QScope can and cannot say:

**Pure states (state-vector engine)** — entanglement across a bipartition
``A|rest`` is *exactly* the von Neumann entropy of the reduced state of ``A``
(the Schmidt entropy).  ``S > 0`` for any bipartition, and the state is
entangled; ``S = 0`` for *every* bipartition, and it is a product state.  That is
a decision, not an estimate, so QScope reports ``SEPARABLE`` / ``ENTANGLED``.

**Mixed states (density-matrix engine)** — there is no single scalar that decides
entanglement for a general ``n``-qubit mixed state.  QScope therefore computes:

* *concurrence* (Wootters) on each two-qubit reduced state — **faithful**: it is
  zero exactly when those two qubits are separable, including mixed states;
* *negativity* per bipartition — a **witness**: nonzero proves entanglement,
  zero proves nothing (bound entanglement is invisible to it).

The report states which of those cases applies, and the ``limitations`` list is
carried into every API response and research report rather than being hidden in
the documentation.
"""

from __future__ import annotations

from itertools import combinations
from typing import Any, Sequence

import numpy as np

from qscope.core.density import DensityMatrix
from qscope.core.statevector import StateVector
from qscope.core.tensor import COMPLEX, as_complex, trace_norm

SEPARABLE = "SEPARABLE"
ENTANGLED = "ENTANGLED"
ENTANGLED_WITNESSED = "ENTANGLED (witnessed)"
NO_DETECTION = "NO ENTANGLEMENT DETECTED (inconclusive)"
NOT_APPLICABLE = "NOT APPLICABLE (single qubit)"

TOL = 1e-9

_Y = np.array([[0, -1j], [1j, 0]], dtype=COMPLEX)
_YY = np.kron(_Y, _Y)


# ---------------------------------------------------------------------------
# single measures
# ---------------------------------------------------------------------------


def partial_transpose(rho: np.ndarray, n: int, system: Sequence[int]) -> np.ndarray:
    """Partial transpose of ``rho`` with respect to the qubits in ``system``."""
    rho = as_complex(rho)
    axes = list(range(2 * n))
    for q in sorted(system):
        axes[q], axes[n + q] = axes[n + q], axes[q]
    tensor = rho.reshape((2,) * n + (2,) * n).transpose(axes)
    return np.ascontiguousarray(tensor).reshape(2**n, 2**n)


def negativity(rho: np.ndarray, n: int, system: Sequence[int]) -> float:
    """``(||rho^{T_A}||_1 - 1) / 2`` — an entanglement witness for the ``A|rest`` cut.

    ``0`` means "not detected by this test" (which for two qubits *does* mean
    separable, but for larger systems can also mean bound entanglement).
    """
    return float((trace_norm(partial_transpose(rho, n, system)) - 1.0) / 2.0)


def logarithmic_negativity(rho: np.ndarray, n: int, system: Sequence[int]) -> float:
    """``log2 ||rho^{T_A}||_1`` — an additive, monotone entanglement measure."""
    return float(np.log2(max(trace_norm(partial_transpose(rho, n, system)), 1.0)))


def concurrence(rho: np.ndarray) -> float:
    """Wootters concurrence of a two-qubit state.

    ``C = max(0, l1 - l2 - l3 - l4)`` where ``l_i`` are the square roots of the
    eigenvalues of ``rho * rho_tilde`` and ``rho_tilde = (Y⊗Y) rho* (Y⊗Y)``.
    Faithful: ``C = 0`` iff the state is separable.
    """
    rho = np.asarray(rho, dtype=COMPLEX)
    if rho.shape != (4, 4):
        raise ValueError("concurrence is defined for two-qubit states")
    rho_tilde = _YY @ rho.conj() @ _YY
    vals = np.linalg.eigvals(rho @ rho_tilde)
    roots = np.sort(np.sqrt(np.abs(np.real(vals))))[::-1]
    return float(max(0.0, roots[0] - roots[1] - roots[2] - roots[3]))


def entanglement_of_formation(c: float) -> float:
    """``E = h((1 + sqrt(1 - C^2)) / 2)`` with ``h`` the binary entropy (bits)."""
    c = float(min(max(c, 0.0), 1.0))
    x = (1.0 + np.sqrt(max(0.0, 1.0 - c**2))) / 2.0
    if x <= 0 or x >= 1:
        return 0.0
    return float(-x * np.log2(x) - (1 - x) * np.log2(1 - x))


def schmidt_entropy(state: StateVector, keep: Sequence[int]) -> float:
    """Entanglement entropy of a pure state's bipartition (bits)."""
    return state.entanglement_entropy(keep)


def all_bipartitions(n: int, max_subsets: int = 512) -> list[list[int]]:
    """Canonical bipartitions: every non-trivial subset containing qubit 0.

    ``S(A) = S(complement)`` for pure states, so fixing qubit 0 on one side halves
    the work without losing information.
    """
    out: list[list[int]] = []
    for size in range(1, n):
        for combo in combinations(range(1, n), size - 1):
            out.append([0, *combo])
            if len(out) >= max_subsets:
                return out
    return out


# ---------------------------------------------------------------------------
# reports
# ---------------------------------------------------------------------------


def pairwise_concurrence(state: Any) -> dict[str, Any]:
    """Concurrence between every qubit pair, from their reduced state.

    Works for pure and mixed states: for a pure state the two-qubit reduced
    density matrix is what Wootters' formula is applied to, and the result is
    still faithful for that reduced state.
    """
    n = state.num_qubits
    matrix = [[0.0] * n for _ in range(n)]
    edges: list[dict[str, Any]] = []
    for i in range(n):
        for j in range(i + 1, n):
            rho = np.asarray(state.reduced_density([i, j]), dtype=COMPLEX)
            c = concurrence(rho)
            matrix[i][j] = matrix[j][i] = c
            edges.append(
                {
                    "a": i,
                    "b": j,
                    "concurrence": c,
                    "entanglement_of_formation": entanglement_of_formation(c),
                    "negativity": negativity(rho, 2, [0]),
                }
            )
    return {"matrix": matrix, "pairs": edges}


def entanglement_report(state: Any, *, max_bipartitions: int = 256) -> dict[str, Any]:
    """Full entanglement analysis with an explicit reliability statement."""
    n = state.num_qubits
    report: dict[str, Any] = {
        "num_qubits": n,
        "representation": "density_matrix" if isinstance(state, DensityMatrix) else "statevector",
        "limitations": [],
    }
    if n < 2:
        report.update(
            status=NOT_APPLICABLE,
            summary="Entanglement requires at least two qubits.",
            per_qubit_entropy=[],
            pairs=[],
            edges=[],
        )
        return report

    pure = isinstance(state, StateVector)
    per_qubit: list[dict[str, Any]] = []
    for q in range(n):
        others = [x for x in range(n) if x != q]
        s = state.entanglement_entropy([q]) if pure else _mixed_entropy(state, [q], others)
        per_qubit.append({"qubit": q, "entanglement_entropy": float(s), "entangled_with_rest": s > TOL})

    pairs = pairwise_concurrence(state)
    edges = [p for p in pairs["pairs"] if p["concurrence"] > TOL]

    if pure:
        splits = all_bipartitions(n, max_subsets=max_bipartitions)
        entropies = []
        for subset in splits:
            s = state.entanglement_entropy(subset)
            entropies.append(
                {
                    "bipartition": subset,
                    "entanglement_entropy": float(s),
                    "schmidt_rank": state.schmidt_rank(subset),
                    "max_possible": float(min(len(subset), n - len(subset))),
                }
            )
        entropies.sort(key=lambda e: e["entanglement_entropy"], reverse=True)
        worst = entropies[0] if entropies else None
        max_entropy = worst["entanglement_entropy"] if worst else 0.0
        status = ENTANGLED if max_entropy > TOL else SEPARABLE
        report.update(
            status=status,
            method="Schmidt entropy over all bipartitions (exact for pure states)",
            summary=(
                f"Entangled across at least one bipartition (max entropy {max_entropy:.4f} bits)."
                if status == ENTANGLED
                else "Separable: every bipartition factorises (all Schmidt ranks are 1)."
            ),
            bipartitions=entropies[:64],
            max_bipartite_entropy=float(max_entropy),
            max_bipartite_split=worst["bipartition"] if worst else None,
            max_pairs=edges,
        )
        if status == ENTANGLED:
            report["limitations"].append(
                "Bipartite entropies characterise entanglement across cuts; they do not by "
                "themselves distinguish GHZ-type from W-type multipartite entanglement."
            )
    else:
        witnesses = []
        for subset in all_bipartitions(n, max_subsets=max_bipartitions):
            neg = negativity(state.data, n, subset)
            witnesses.append(
                {
                    "bipartition": subset,
                    "negativity": neg,
                    "logarithmic_negativity": logarithmic_negativity(state.data, n, subset),
                    "detected": neg > TOL,
                }
            )
        witnesses.sort(key=lambda w: w["negativity"], reverse=True)
        detected = [w for w in witnesses if w["detected"]]
        status = ENTANGLED_WITNESSED if detected else NO_DETECTION
        report.update(
            status=status,
            method="Pairwise concurrence (faithful for 2 qubits) + negativity witnesses",
            summary=(
                f"Entanglement witnessed across {len(detected)} bipartition(s); strongest "
                f"negativity {detected[0]['negativity']:.4f}."
                if detected
                else "No entanglement detected. Mixed states can be entangled without any "
                "nonzero negativity (bound entanglement), so this is not proof of separability."
            ),
            witnesses=witnesses[:64],
            max_negativity=float(max(0.0, witnesses[0]["negativity"])) if witnesses else 0.0,
            max_pairs=edges,
        )
        report["limitations"].append(
            "The state is mixed, so no scalar decides entanglement: negativity is a witness "
            "(nonzero proves entanglement, zero does not prove separability) and pairwise "
            "concurrence only characterises each two-qubit reduced state."
        )
    report["per_qubit_entropy"] = per_qubit
    report["pairs"] = pairs["pairs"]
    report["edges"] = edges
    report["pairwise_concurrence_matrix"] = pairs["matrix"]
    report["max_concurrence"] = float(max((p["concurrence"] for p in pairs["pairs"]), default=0.0))
    report["entangled_pair_count"] = len(edges)
    report["num_qubits"] = n
    return report


def _mixed_entropy(state: DensityMatrix, keep: Sequence[int], rest: Sequence[int]) -> float:
    rho = state.reduced_density(keep)
    vals = np.linalg.eigvalsh((rho + rho.conj().T) / 2)
    vals = vals[vals > 1e-12]
    if vals.size == 0:
        return 0.0
    return float(-np.sum(vals * np.log2(vals)))


def entanglement_graph(state: Any) -> dict[str, Any]:
    """Node/edge data for the entanglement map visualisation."""
    report = entanglement_report(state)
    nodes = []
    for entry in report.get("per_qubit_entropy", []):
        nodes.append(
            {
                "id": entry["qubit"],
                "label": f"q{entry['qubit']}",
                "entanglement": entry["entanglement_entropy"],
            }
        )
    edges = [
        {
            "source": e["a"],
            "target": e["b"],
            "weight": e["concurrence"],
            "negativity": e["negativity"],
        }
        for e in report.get("edges", [])
    ]
    return {
        "nodes": nodes,
        "edges": edges,
        "status": report["status"],
        "max_concurrence": report.get("max_concurrence", 0.0),
        "limitations": report.get("limitations", []),
    }


def entanglement_change(before: Any, after: Any) -> dict[str, Any]:
    """Entanglement bookkeeping for the Quantum Diff engine and per-gate tracing."""
    b = entanglement_report(before)
    a = entanglement_report(after)
    b_map = {(p["a"], p["b"]): p["concurrence"] for p in b.get("pairs", [])}
    deltas = []
    for pair in a.get("pairs", []):
        key = (pair["a"], pair["b"])
        previous = b_map.get(key, 0.0)
        deltas.append(
            {
                "pair": [pair["a"], pair["b"]],
                "before": previous,
                "after": pair["concurrence"],
                "delta": pair["concurrence"] - previous,
            }
        )
    deltas.sort(key=lambda d: abs(d["delta"]), reverse=True)
    return {
        "before_status": b.get("status"),
        "after_status": a.get("status"),
        "transition": (
            "NONE → DETECTED"
            if b.get("status") in (SEPARABLE, NO_DETECTION) and a.get("status") in (ENTANGLED, ENTANGLED_WITNESSED)
            else "DETECTED → NONE"
            if a.get("status") in (SEPARABLE, NO_DETECTION) and b.get("status") in (ENTANGLED, ENTANGLED_WITNESSED)
            else "UNCHANGED"
        ),
        "max_concurrence_before": b.get("max_concurrence", 0.0),
        "max_concurrence_after": a.get("max_concurrence", 0.0),
        "pairwise_deltas": deltas,
        "created_by_pair": [d for d in deltas if d["delta"] > 1e-6],
        "destroyed_by_pair": [d for d in deltas if d["delta"] < -1e-6],
        "limitations": a.get("limitations", []),
    }


__all__ = [
    "ENTANGLED",
    "ENTANGLED_WITNESSED",
    "NOT_APPLICABLE",
    "NO_DETECTION",
    "SEPARABLE",
    "all_bipartitions",
    "concurrence",
    "entanglement_change",
    "entanglement_graph",
    "entanglement_of_formation",
    "entanglement_report",
    "logarithmic_negativity",
    "negativity",
    "pairwise_concurrence",
    "partial_transpose",
    "schmidt_entropy",
]
