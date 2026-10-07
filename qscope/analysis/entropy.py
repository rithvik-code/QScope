"""Entropy, purity and information measures.

* **Von Neumann entropy** — ``S = -Tr(rho log_2 rho)`` in bits.  Maximum ``n`` for
  an ``n``-qubit state.  Zero only for a pure state.
* **Rényi entropy** — ``S_alpha = 1/(1-alpha) log_2 Tr(rho^alpha)``.  ``S_1`` is the
  von Neumann limit; ``S_2 = -log_2 Tr(rho^2)`` is the collision entropy.
* **Shannon entropy** — of a measured distribution, not of the state.
* **Purity** — ``Tr(rho^2)``; **linear entropy** — ``1 - Tr(rho^2)``.
* **Participation ratio** — ``1 / sum_i p_i^2`` over basis probabilities: the
  *effective number of occupied basis states*.  It is an intuitive companion to
  entropy for visuals, not a quantum information measure, and is labelled as such.
"""

from __future__ import annotations

from typing import Any, Sequence

import numpy as np

from qscope.core.density import DensityMatrix
from qscope.core.statevector import StateVector
from qscope.core.tensor import COMPLEX, as_complex, von_neumann_entropy


def von_neumann(mat: Any, base: float = 2.0) -> float:
    """Von Neumann entropy of a state (accepts vectors or matrices)."""
    return float(von_neumann_entropy(_as_matrix(mat), base=base))


def renyi(mat: Any, alpha: float = 2.0, base: float = 2.0) -> float:
    """Rényi entropy of order ``alpha`` (``alpha != 1``)."""
    if abs(alpha - 1.0) < 1e-12:
        return von_neumann(mat, base=base)
    m = _as_matrix(mat)
    vals = np.linalg.eigvalsh((m + m.conj().T) / 2)
    vals = vals[vals > 1e-12]
    if vals.size == 0:
        return 0.0
    return float(np.log(np.sum(vals**alpha)) / ((1 - alpha) * np.log(base)))


def shannon(probabilities: Sequence[float] | dict[str, float], base: float = 2.0) -> float:
    """Shannon entropy of a probability distribution."""
    values = np.array(list(probabilities.values()) if isinstance(probabilities, dict) else probabilities, dtype=float)
    values = values[values > 0]
    if values.size == 0:
        return 0.0
    return float(-np.sum(values * np.log(values)) / np.log(base))


def purity(mat: Any) -> float:
    """``Tr(rho^2)``: 1 for pure, ``1/2^n`` for the maximally mixed state."""
    m = _as_matrix(mat)
    return float(np.real(np.trace(m @ m)))


def linear_entropy(mat: Any) -> float:
    """``1 - Tr(rho^2)``: 0 for pure, ``1 - 1/2^n`` for maximally mixed."""
    return float(1.0 - purity(mat))


def participation_ratio(probabilities: Sequence[float] | dict[str, float]) -> float:
    """``1 / sum_i p_i^2`` — the effective number of populated basis states."""
    values = np.array(list(probabilities.values()) if isinstance(probabilities, dict) else probabilities, dtype=float)
    denom = float(np.sum(values**2))
    return float(1.0 / denom) if denom > 0 else 0.0


def normalized_entropy(mat: Any, num_qubits: int) -> float:
    """``S / n`` — 0 for pure, 1 for maximally mixed."""
    if num_qubits <= 0:
        return 0.0
    return von_neumann(mat) / num_qubits


def entropy_spectrum(mat: Any, threshold: float = 1e-12) -> dict[str, Any]:
    """Eigenvalue spectrum of a density matrix plus its entropy contributions.

    ``-lambda log2 lambda`` per eigenvalue is the *entropy contribution* of each
    Schmidt/eigen mode; plotting it makes it obvious whether entropy comes from
    many small modes or a few large ones.
    """
    m = _as_matrix(mat)
    vals = np.linalg.eigvalsh((m + m.conj().T) / 2)
    vals = np.sort(vals)[::-1]
    kept = vals[vals > threshold]
    contributions = -kept * np.log2(kept)
    return {
        "eigenvalues": [float(v) for v in vals],
        "significant": [float(v) for v in kept],
        "contributions": [float(c) for c in contributions],
        "effective_rank": int(kept.size),
        "entropy": float(np.sum(contributions)),
    }


def max_mixed_entropy(num_qubits: int) -> float:
    """``log2(2^n) = n`` bits — the entropy ceiling for a normalised state."""
    return float(num_qubits)


def _as_matrix(state: Any) -> np.ndarray:
    if isinstance(state, DensityMatrix):
        return state.data
    if isinstance(state, StateVector):
        return state.density_matrix()
    arr = as_complex(state)
    if arr.ndim == 1:
        return np.outer(arr, arr.conj())
    return arr


__all__ = [
    "entropy_spectrum",
    "linear_entropy",
    "max_mixed_entropy",
    "normalized_entropy",
    "participation_ratio",
    "purity",
    "renyi",
    "shannon",
    "von_neumann",
]
