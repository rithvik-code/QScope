"""Density-matrix engine — the exact representation for noisy evolution.

Why QScope keeps two engines instead of one:

* A **pure** state needs ``2^n`` amplitudes.  Ideal simulation should never pay
  for a ``4^n`` matrix.
* A **noisy** state is generally mixed, and pretending it is pure would make
  every fidelity, entropy and entanglement number *wrong*.  So noise goes
  through an honest density matrix, guarded by the memory limits in
  :mod:`qscope.simulator.execution`, and is labelled "exact noisy" in the UI.

The Monte-Carlo trajectory engine (:mod:`qscope.simulator.trajectory`) is the
cheap alternative and is always labelled *approximate*.
"""

from __future__ import annotations

from typing import Any, Sequence

import numpy as np

from qscope.core.gates import gate_spec
from qscope.core.measurement import (
    MeasurementOutcome,
    MeasurementResult,
    marginal_probabilities,
    normalize_probabilities,
    sample_counts,
)
from qscope.core.statevector import (
    PAULI_MATRICES,
    BlochVector,
    StateVector,
    bloch_from_density,
    pauli_action_table,
)
from qscope.core.tensor import (
    ATOL,
    COMPLEX,
    apply_kraus,
    apply_operator,
    basis_label,
    controlled,
    is_close,
    matrix_sqrt,
    partial_trace,
    purity as _purity,
    trace_norm,
    von_neumann_entropy,
)

MAX_QUBITS = 14
"""Practical ceiling for a dense density matrix (``4^14 * 16 B`` ~= 4.3 GiB)."""


class DensityMatrix:
    """An ``n``-qubit mixed state as a ``2^n x 2^n`` complex matrix."""

    __slots__ = ("num_qubits", "data")

    def __init__(self, num_qubits: int, data: np.ndarray | None = None) -> None:
        if not 1 <= num_qubits <= MAX_QUBITS:
            raise ValueError(f"num_qubits must be in 1..{MAX_QUBITS}, got {num_qubits}")
        self.num_qubits = num_qubits
        dim = 2**num_qubits
        if data is None:
            rho = np.zeros((dim, dim), dtype=COMPLEX)
            rho[0, 0] = 1.0
            self.data = rho
        else:
            arr = np.asarray(data, dtype=COMPLEX)
            if arr.shape != (dim, dim):
                raise ValueError(f"expected {(dim, dim)} density matrix, got {arr.shape}")
            self.data = np.array(arr, dtype=COMPLEX, copy=True)

    # ------------------------------------------------------------------ build

    @classmethod
    def from_statevector(cls, state: StateVector) -> "DensityMatrix":
        """``rho = |psi><psi|``."""
        return cls(state.num_qubits, state.density_matrix())

    @classmethod
    def maximally_mixed(cls, num_qubits: int) -> "DensityMatrix":
        dim = 2**num_qubits
        return cls(num_qubits, np.eye(dim, dtype=COMPLEX) / dim)

    def copy(self) -> "DensityMatrix":
        clone = DensityMatrix.__new__(DensityMatrix)
        clone.num_qubits = self.num_qubits
        clone.data = self.data.copy()
        return clone

    # ---------------------------------------------------------------- inspect

    @property
    def dimension(self) -> int:
        return 2**self.num_qubits

    def trace(self) -> float:
        return float(np.real(np.trace(self.data)))

    def is_hermitian(self, tol: float = 1e-9) -> bool:
        """``rho == rho^dagger`` within ``tol``."""
        return bool(np.allclose(self.data, self.data.conj().T, atol=tol, rtol=0))

    def is_positive_semidefinite(self, tol: float = 1e-9) -> bool:
        vals = np.linalg.eigvalsh((self.data + self.data.conj().T) / 2)
        return bool(np.min(vals) >= -tol)

    def is_valid(self, tol: float = 1e-9) -> bool:
        """Hermitian, unit trace, positive semi-definite."""
        return (
            self.is_hermitian(tol)
            and abs(self.trace() - 1.0) <= 1e-8
            and self.is_positive_semidefinite(tol)
        )

    def probabilities(self) -> np.ndarray:
        return normalize_probabilities(np.real(np.diag(self.data)))

    def purity(self) -> float:
        """``Tr(rho^2)``: 1 for pure, ``1/2^n`` for maximally mixed."""
        return _purity(self.data)

    def entropy(self, base: float = 2.0) -> float:
        """Von Neumann entropy ``-Tr(rho log rho)`` in the given base."""
        return von_neumann_entropy(self.data, base=base)

    def linear_entropy(self) -> float:
        """``1 - Tr(rho^2)``; 0 for a pure state, ``1 - 1/2^n`` when maximally mixed."""
        return float(1.0 - self.purity())

    def is_pure(self, tol: float = 1e-9) -> bool:
        return abs(self.purity() - 1.0) <= tol

    def dominant_basis(self) -> str:
        return basis_label(self.num_qubits, int(np.argmax(np.diag(self.data).real)))

    def reduced_density(self, keep: Sequence[int]) -> np.ndarray:
        return partial_trace(self.data, self.num_qubits, keep)

    def bloch_vector(self, qubit: int) -> BlochVector:
        return bloch_from_density(self.reduced_density([qubit]))

    def bloch_vectors(self) -> list[BlochVector]:
        return [self.bloch_vector(q) for q in range(self.num_qubits)]

    def expectation_pauli(self, pauli: str) -> float:
        """``Tr(P rho)`` for a Pauli string (qubit 0 first)."""
        pauli = pauli.replace(" ", "").upper()
        if len(pauli) != self.num_qubits:
            raise ValueError(f"Pauli string length {len(pauli)} != {self.num_qubits} qubits")
        flipped, phases = pauli_action_table(pauli, self.num_qubits)
        idx = np.arange(self.dimension)
        value = np.sum(phases * self.data[flipped, idx])
        return float(np.real(value))

    def fidelity_pure(self, state: StateVector) -> float:
        """``<psi|rho|psi>`` — fidelity against a pure target."""
        psi = state.data
        return float(np.real(np.conjugate(psi) @ (self.data @ psi)))

    def fidelity(self, other: "DensityMatrix") -> float:
        """Uhlmann fidelity ``(Tr sqrt(sqrt(rho) sigma sqrt(rho)))^2``."""
        if other.num_qubits != self.num_qubits:
            raise ValueError("fidelity requires matching qubit counts")
        sqrt_rho = matrix_sqrt(self.data)
        inner = sqrt_rho @ other.data @ sqrt_rho
        return float(np.real(np.trace(matrix_sqrt(inner))) ** 2)

    def trace_distance(self, other: "DensityMatrix") -> float:
        """``0.5 * ||rho - sigma||_1`` in ``[0, 1]``."""
        if other.num_qubits != self.num_qubits:
            raise ValueError("trace distance requires matching qubit counts")
        return 0.5 * trace_norm(self.data - other.data)

    def to_pure(self) -> StateVector | None:
        """Recover the state vector when the state is pure (else ``None``)."""
        if not self.is_pure(1e-8):
            return None
        vals, vecs = np.linalg.eigh((self.data + self.data.conj().T) / 2)
        vec = vecs[:, int(np.argmax(vals))]
        psi = StateVector(self.num_qubits, vec)
        psi.normalize()
        return psi

    # ------------------------------------------------------------------ evolve

    def apply_unitary(self, matrix: np.ndarray, targets: Sequence[int]) -> "DensityMatrix":
        """``rho -> U rho U^dagger`` (in place)."""
        self.data = apply_kraus(self.data, [np.asarray(matrix, dtype=COMPLEX)], targets, self.num_qubits)
        return self

    def apply_gate(self, name: str, targets: Sequence[int], params: Sequence[float] = ()) -> "DensityMatrix":
        """Apply a named gate (in place)."""
        targets = tuple(int(t) for t in targets)
        spec = gate_spec(name)
        if spec.num_qubits == -1:
            mat = spec.matrix(params, num_qubits=len(targets))
        else:
            if len(targets) != spec.num_qubits:
                raise ValueError(f"gate {name} acts on {spec.num_qubits} qubits, got {len(targets)}")
            mat = spec.matrix(params)
        return self.apply_unitary(mat, targets)

    def apply_controlled(
        self,
        name: str,
        controls: Sequence[int],
        targets: Sequence[int],
        params: Sequence[float] = (),
    ) -> "DensityMatrix":
        targets = tuple(int(t) for t in targets)
        controls = tuple(int(c) for c in controls)
        spec = gate_spec(name)
        inner = spec.matrix(params, num_qubits=len(targets)) if spec.num_qubits == -1 else spec.matrix(params)
        mat = controlled(inner, len(controls))
        return self.apply_unitary(mat, list(controls) + list(targets))

    def apply_channel(self, kraus: Sequence[np.ndarray], targets: Sequence[int]) -> "DensityMatrix":
        """Apply an arbitrary quantum channel (in place)."""
        self.data = apply_kraus(self.data, list(kraus), targets, self.num_qubits)
        return self

    def partial_reset(self, qubit: int, probability: float) -> "DensityMatrix":
        """Weak reset channel: with ``probability`` set ``qubit`` to ``|0>``.

        Models "measurement then discard, occasionally", which is the dominant
        error in many mid-circuit-measurement experiments.
        """
        if not 0.0 <= probability <= 1.0:
            raise ValueError("probability must be in [0, 1]")
        k0 = np.sqrt(1 - probability) * np.eye(2, dtype=COMPLEX)
        k1 = np.sqrt(probability) * np.array([[1, 0], [0, 0]], dtype=COMPLEX)
        return self.apply_channel([k0, k1], [qubit])

    def dephase(self, qubit: int, probability: float) -> "DensityMatrix":
        """Dephasing channel: zero the off-diagonals of ``qubit`` with weight ``p``."""
        if not 0.0 <= probability <= 1.0:
            raise ValueError("probability must be in [0, 1]")
        k0 = np.sqrt(1 - probability / 2) * np.eye(2, dtype=COMPLEX)
        k1 = np.sqrt(probability / 2) * np.array([[1, 0], [0, -1]], dtype=COMPLEX)
        return self.apply_channel([k0, k1], [qubit])

    # ------------------------------------------------------------------ measure

    def measure_qubit(
        self,
        qubit: int,
        rng: np.random.Generator | None = None,
        outcome: int | None = None,
    ) -> MeasurementOutcome:
        """Projective measurement + Kraus collapse of the density matrix."""
        rng = rng or np.random.default_rng()
        diag = np.real(np.diag(self.data))
        shift = self.num_qubits - 1 - qubit
        idx = np.arange(self.dimension)
        zero = ((idx >> shift) & 1) == 0
        p0 = float(np.sum(diag[zero]))
        if outcome is None:
            outcome = 0 if rng.random() < p0 else 1
        probability = p0 if outcome == 0 else 1.0 - p0
        if probability < ATOL:
            raise ValueError(f"outcome {outcome} on qubit {qubit} is impossible")
        projector = np.zeros(self.dimension, dtype=COMPLEX)
        projector[idx[zero]] = 1.0 if outcome == 0 else 0.0
        projector[idx[~zero]] = 1.0 if outcome == 1 else 0.0
        P = np.diag(projector)
        self.data = (P @ self.data @ P) / probability
        return MeasurementOutcome(
            qubits=(qubit,),
            outcome=int(outcome),
            label=str(int(outcome)),
            probability=probability,
        )

    def sample(
        self,
        shots: int,
        rng: np.random.Generator | None = None,
        qubits: Sequence[int] | None = None,
        readout_error: float = 0.0,
        *,
        keep_memory: bool = True,
    ) -> MeasurementResult:
        """Sample measurements from the diagonal of ``rho``."""
        from qscope.core.measurement import apply_readout_error

        rng = rng or np.random.default_rng()
        qubits = list(range(self.num_qubits)) if qubits is None else sorted({int(q) for q in qubits})
        marginals = marginal_probabilities(self.probabilities(), self.num_qubits, qubits)
        labels = sorted(marginals)
        counts, memory = sample_counts([marginals[l] for l in labels], shots, rng, labels=labels)
        if readout_error > 0:
            counts, _ = apply_readout_error(counts, len(qubits), readout_error, rng)
        return MeasurementResult(
            qubits=qubits,
            shots=shots,
            counts=counts,
            ideal_probabilities=marginals,
            memory=memory if keep_memory else [],
            readout_error=readout_error,
        )

    # ------------------------------------------------------------------ export

    def to_dict(self, term_limit: int | None = 64) -> dict[str, Any]:
        """Serialisable snapshot (builds a state vector when the state is pure)."""
        diag = np.real(np.diag(self.data))
        probs = normalize_probabilities(diag)
        order = np.argsort(probs)[::-1]
        terms = [
            {
                "basis": basis_label(self.num_qubits, int(i)),
                "index": int(i),
                "probability": float(probs[i]),
                "real": float(np.sqrt(max(probs[i], 0.0))),
                "imag": 0.0,
                "magnitude": float(np.sqrt(max(probs[i], 0.0))),
                "phase": 0.0,
            }
            for i in order[:term_limit]
            if probs[i] > 1e-12
        ]
        pure = self.to_pure()
        return {
            "num_qubits": self.num_qubits,
            "dimension": self.dimension,
            "representation": "density_matrix",
            "is_pure": self.is_pure(1e-8),
            "trace": self.trace(),
            "purity": self.purity(),
            "entropy": self.entropy(),
            "linear_entropy": self.linear_entropy(),
            "probabilities": [{"basis": basis_label(self.num_qubits, int(i)), "probability": float(probs[i])} for i in order[:term_limit] if probs[i] > 1e-12],
            "amplitudes": terms,
            "bloch": [b.to_dict() for b in self.bloch_vectors()],
            "dominant_basis": self.dominant_basis(),
            "coherence": float(np.sum(np.abs(self.data)) - np.sum(np.abs(np.diag(self.data)))),
            "pure_state_vector": pure.to_dict(term_limit=term_limit) if pure is not None else None,
        }

    def pretty(self, threshold: float = 1e-9) -> str:
        """Human-readable diagonal, e.g. ``0.5000|00> + 0.5000|11>`` (+ coherences)."""
        probs = normalize_probabilities(np.real(np.diag(self.data)))
        parts = [
            f"{p:.4f}|{basis_label(self.num_qubits, i)}>"
            for i, p in enumerate(probs)
            if p > threshold
        ]
        return " + ".join(parts) if parts else "0"

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"DensityMatrix({self.num_qubits}q, purity={self.purity():.4f})"


def pauli_basis_decomposition(rho: np.ndarray, n: int) -> dict[str, float]:
    """Expand a density matrix in the Pauli basis: ``rho = sum_P c_P P``.

    Coefficients are ``c_P = Tr(P rho) / 2^n``; the identity term is 1/2^n by
    normalisation.  Used by the noise observatory to show *which* Pauli
    components a channel is destroying.
    """
    from itertools import product

    out: dict[str, float] = {}
    for string in product("IXYZ", repeat=n):
        label = "".join(string)
        matrix = PAULI_MATRICES[label[0]]
        for ch in label[1:]:
            matrix = np.kron(matrix, PAULI_MATRICES[ch])
        out[label] = float(np.real(np.trace(matrix @ rho)) / 2**n)
    return out


__all__ = ["MAX_QUBITS", "DensityMatrix", "pauli_basis_decomposition"]
