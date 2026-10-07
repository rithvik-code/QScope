"""Fidelity and distance measures.

Formulas used (spelled out because "fidelity" means different things in
different papers):

* **Pure vs pure** — ``F = |<psi|phi>|^2``.
* **Pure vs mixed** — ``F = <psi| rho |psi>``.
* **Mixed vs mixed** — ``F = (Tr sqrt(sqrt(rho) sigma sqrt(rho)))^2`` (Uhlmann/Jozsa).
* **Trace distance** — ``T = 0.5 ||rho - sigma||_1``, in ``[0, 1]``.
* **Total variation distance (classical)** — ``0.5 * sum_i |p_i - q_i|`` on
  measured probability distributions.
* **Process (entanglement) fidelity** — ``F_process = (|Tr(U^dagger V)| / d)^2``.

All are normalised so that 1 means "identical".
"""

from __future__ import annotations

from typing import Any, Sequence

import numpy as np

from qscope.core.density import DensityMatrix
from qscope.core.statevector import StateVector
from qscope.core.tensor import COMPLEX, as_complex, matrix_sqrt, trace_norm


def state_fidelity(a: Any, b: Any) -> float:
    """Fidelity between any combination of :class:`StateVector`/:class:`DensityMatrix`.

    The representation is promoted automatically so callers never have to care
    whether a state is pure or mixed.
    """
    if isinstance(a, StateVector) and isinstance(b, StateVector):
        return a.fidelity(b)
    if isinstance(a, StateVector) and isinstance(b, DensityMatrix):
        return b.fidelity_pure(a)
    if isinstance(a, DensityMatrix) and isinstance(b, StateVector):
        return a.fidelity_pure(b)
    if isinstance(a, DensityMatrix) and isinstance(b, DensityMatrix):
        return a.fidelity(b)
    raise TypeError("fidelity expects StateVector or DensityMatrix instances")


def trace_distance(a: Any, b: Any) -> float:
    """``0.5 ||rho - sigma||_1``; for pure states ``sqrt(1 - F)``."""
    if isinstance(a, StateVector) and isinstance(b, StateVector):
        return float(np.sqrt(max(0.0, 1.0 - a.fidelity(b))))
    rho = a if isinstance(a, DensityMatrix) else DensityMatrix.from_statevector(a)
    sigma = b if isinstance(b, DensityMatrix) else DensityMatrix.from_statevector(b)
    return rho.trace_distance(sigma)


def total_variation(p: dict[str, float] | Sequence[float], q: dict[str, float] | Sequence[float]) -> float:
    """Classical total variation distance between two distributions.

    Missing keys count as zero probability, so histograms of different support
    sizes can still be compared.
    """
    if isinstance(p, dict) and isinstance(q, dict):
        keys = set(p) | set(q)
        return float(0.5 * sum(abs(p.get(k, 0.0) - q.get(k, 0.0)) for k in keys))
    pv, qv = np.asarray(p, dtype=float), np.asarray(q, dtype=float)
    if pv.shape != qv.shape:
        raise ValueError("total_variation needs equal-length distributions for sequences")
    return float(0.5 * np.sum(np.abs(pv - qv)))


def process_fidelity(u: np.ndarray, v: np.ndarray) -> float:
    """Entanglement (process) fidelity between two unitaries, in ``[0, 1]``."""
    u, v = as_complex(u), as_complex(v)
    d = u.shape[0]
    return float((abs(np.trace(u.conj().T @ v)) / d) ** 2)


def average_gate_fidelity(u: np.ndarray, v: np.ndarray) -> float:
    """Average gate fidelity ``(d F_process + 1) / (d + 1)``."""
    d = as_complex(u).shape[0]
    return (d * process_fidelity(u, v) + 1.0) / (d + 1.0)


def gate_error_from_fidelity(fidelity: float) -> float:
    """``1 - F`` — the standard definition of infidelity/gate error."""
    return float(max(0.0, 1.0 - fidelity))


def distinguishability(fidelity: float) -> float:
    """Helstrom's bound: ``0.5 (1 + sqrt(1 - F))`` success probability of telling two
    states apart with an optimal single-shot measurement.  Useful as a sanity
    check that a fidelity drop actually matters for state discrimination.
    """
    f = float(min(max(fidelity, 0.0), 1.0))
    return 0.5 * (1.0 + np.sqrt(max(0.0, 1.0 - f)))


def matrix_fidelity_theoretical(rho: np.ndarray, sigma: np.ndarray) -> float:
    """Uhlmann fidelity straight from matrices (used to cross-check the class API)."""
    rho, sigma = as_complex(rho), as_complex(sigma)
    sqrt_rho = matrix_sqrt(rho)
    inner = sqrt_rho @ sigma @ sqrt_rho
    return float(np.real(np.trace(matrix_sqrt(inner))) ** 2)


def trace_distance_theoretical(rho: np.ndarray, sigma: np.ndarray) -> float:
    """``0.5 ||rho - sigma||_1`` straight from matrices."""
    return 0.5 * trace_norm(as_complex(rho) - as_complex(sigma))


def fidelity_matrix(states: Sequence[Any]) -> list[list[float]]:
    """Pairwise fidelity table (used by the comparison view)."""
    return [[state_fidelity(a, b) for b in states] for a in states]


def counts_fidelity_to_target(counts: dict[str, int], target: str) -> float:
    """Empirical ``P(measured == target)`` from a shot histogram.

    This is the *experimental* success probability of an algorithm run — it
    includes sampling error and every error source in the model, which is why the
    UI distinguishes it from the ideal state fidelity.
    """
    total = sum(counts.values())
    if total == 0:
        return 0.0
    return counts.get(target, 0) / total


def maximum_likelihood_success(counts: dict[str, int], targets: Sequence[str]) -> float:
    """Probability mass on a set of acceptable outcomes."""
    total = sum(counts.values())
    if total == 0:
        return 0.0
    return sum(counts.get(t, 0) for t in targets) / total


__all__ = [
    "average_gate_fidelity",
    "counts_fidelity_to_target",
    "distinguishability",
    "fidelity_matrix",
    "gate_error_from_fidelity",
    "matrix_fidelity_theoretical",
    "maximum_likelihood_success",
    "process_fidelity",
    "state_fidelity",
    "total_variation",
    "trace_distance",
    "trace_distance_theoretical",
]
