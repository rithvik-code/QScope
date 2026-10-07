"""Exact state-vector engine.

A ``StateVector`` holds ``2 ** n`` complex amplitudes and knows how to evolve
them, inspect them and measure them.  All evolution is *in place* (with an
explicit :meth:`StateVector.copy`) because the debugger snapshots states at every
step and copying twice per gate would double the cost of tracing a long circuit.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterator, Sequence

import numpy as np

from qscope.core.gates import gate_spec
from qscope.core.measurement import (
    MeasurementOutcome,
    MeasurementResult,
    collapse_statevector,
    marginal_probabilities,
    normalize_probabilities,
    sample_counts,
)
from qscope.core.tensor import (
    ATOL,
    COMPLEX,
    apply_operator,
    basis_label,
    basis_state,
    controlled,
    label_to_index,
)

MAX_QUBITS = 30
"""Hard ceiling for state-vector allocation (``2 ** 30`` amplitudes = 16 GiB)."""

PAULI_MATRICES = {
    "I": np.array([[1, 0], [0, 1]], dtype=COMPLEX),
    "X": np.array([[0, 1], [1, 0]], dtype=COMPLEX),
    "Y": np.array([[0, -1j], [1j, 0]], dtype=COMPLEX),
    "Z": np.array([[1, 0], [0, -1]], dtype=COMPLEX),
}


@dataclass(frozen=True)
class BlochVector:
    """Bloch coordinates of a (possibly reduced) qubit state."""

    x: float
    y: float
    z: float

    @property
    def length(self) -> float:
        """``|r| <= 1``; strictly less than 1 means the qubit is entangled or mixed."""
        return float(np.sqrt(self.x**2 + self.y**2 + self.z**2))

    @property
    def theta(self) -> float:
        """Polar angle in radians (0 = |0>, pi = |1>)."""
        return float(np.arccos(np.clip(self.z, -1.0, 1.0)))

    @property
    def phi(self) -> float:
        """Azimuthal angle in radians, in ``(-pi, pi]``."""
        return float(np.arctan2(self.y, self.x))

    def to_dict(self) -> dict[str, Any]:
        return {
            "x": self.x,
            "y": self.y,
            "z": self.z,
            "length": self.length,
            "theta": self.theta,
            "phi": self.phi,
        }


class StateVector:
    """A pure ``n``-qubit state as an exact complex amplitude vector."""

    __slots__ = ("num_qubits", "data")

    def __init__(self, num_qubits: int, data: np.ndarray | Sequence[complex] | None = None) -> None:
        if not 1 <= num_qubits <= MAX_QUBITS:
            raise ValueError(f"num_qubits must be in 1..{MAX_QUBITS}, got {num_qubits}")
        self.num_qubits = num_qubits
        dim = 2**num_qubits
        if data is None:
            self.data = basis_state(num_qubits, 0)
        else:
            arr = np.asarray(data, dtype=COMPLEX)
            if arr.ndim != 1 or arr.size != dim:
                raise ValueError(f"expected {dim} amplitudes, got shape {arr.shape}")
            self.data = np.array(arr, dtype=COMPLEX, copy=True)

    # ------------------------------------------------------------------ build

    @classmethod
    def zero_state(cls, num_qubits: int) -> "StateVector":
        """``|0...0>``."""
        return cls(num_qubits)

    @classmethod
    def from_basis(cls, num_qubits: int, index: int) -> "StateVector":
        """Computational basis state by integer index."""
        return cls(num_qubits, basis_state(num_qubits, index))

    @classmethod
    def from_label(cls, label: str) -> "StateVector":
        """Computational basis state from a bitstring, qubit 0 leftmost."""
        clean = "".join(ch for ch in label if ch in "01")
        n = len(clean)
        return cls(n, basis_state(n, label_to_index(n, clean)))

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "StateVector":
        """Rebuild from the amplitude map produced by :meth:`terms`."""
        n = int(payload["num_qubits"])
        vec = cls(n)
        for basis, amp in payload.get("amplitudes", {}).items():
            vec.data[label_to_index(n, basis)] = complex(amp[0], amp[1]) if isinstance(amp, (list, tuple)) else complex(amp)
        vec.normalize()
        return vec

    def copy(self) -> "StateVector":
        """Deep copy (used by the tracer to snapshot every step)."""
        clone = StateVector.__new__(StateVector)
        clone.num_qubits = self.num_qubits
        clone.data = self.data.copy()
        return clone

    # ---------------------------------------------------------------- inspect

    @property
    def dimension(self) -> int:
        return 2**self.num_qubits

    def norm(self) -> float:
        return float(np.linalg.norm(self.data))

    def is_normalized(self, tol: float = 1e-9) -> bool:
        """Whether ``<psi|psi> = 1`` within ``tol``."""
        return abs(self.norm() - 1.0) <= tol

    def normalize(self) -> "StateVector":
        n = self.norm()
        if n < ATOL:
            raise ValueError("cannot normalise a zero state vector")
        self.data /= n
        return self

    def amplitudes(self) -> np.ndarray:
        return self.data

    def amplitude(self, basis: str | int) -> complex:
        idx = label_to_index(self.num_qubits, basis) if isinstance(basis, str) else int(basis)
        return complex(self.data[idx])

    def set_amplitude(self, basis: str | int, value: complex) -> None:
        idx = label_to_index(self.num_qubits, basis) if isinstance(basis, str) else int(basis)
        self.data[idx] = complex(value)

    def probabilities(self) -> np.ndarray:
        """Born probabilities ``|a_i|^2`` (not renormalised)."""
        return np.abs(self.data) ** 2

    def normalized_probabilities(self) -> np.ndarray:
        return normalize_probabilities(self.probabilities())

    def probability(self, basis: str | int) -> float:
        idx = label_to_index(self.num_qubits, basis) if isinstance(basis, str) else int(basis)
        return float(abs(self.data[idx]) ** 2)

    def phase(self, basis: str | int) -> float:
        idx = label_to_index(self.num_qubits, basis) if isinstance(basis, str) else int(basis)
        return float(np.angle(self.data[idx]))

    def phases(self) -> np.ndarray:
        return np.angle(self.data)

    def support(self, threshold: float = 1e-9) -> list[int]:
        """Indices whose probability exceeds ``threshold`` (the *coherent support*)."""
        return [int(i) for i in np.nonzero(self.probabilities() > threshold)[0]]

    def nonzero_count(self, threshold: float = 1e-9) -> int:
        return len(self.support(threshold))

    def purity(self) -> float:
        """1.0 for any normalised pure state (a sanity check, not a metric here)."""
        return self.norm() ** 4

    def density_matrix(self) -> np.ndarray:
        """``|psi><psi|`` as a ``2^n x 2^n`` matrix.

        Costs ``4^n`` memory: callers handling more than ~13 qubits should use
        :meth:`reduced_density` or :meth:`entanglement_entropy`, which never build it.
        """
        return np.outer(self.data, self.data.conj())

    def reduced_density(self, keep: Sequence[int]) -> np.ndarray:
        """Reduced density matrix on ``keep`` via tensor contraction (not partial trace).

        ``rho = M M^dagger`` where ``M`` is the state reshaped to
        ``(2^|keep|, 2^n / 2^|keep|)`` with the kept axes first.  This avoids ever
        materialising the ``4^n`` full density matrix, so a 20-qubit reduced
        state stays a 160 MB operation instead of a terabyte one.
        """
        keep = sorted({int(q) for q in keep})
        if any(q < 0 or q >= self.num_qubits for q in keep):
            raise ValueError(f"keep={keep} outside 0..{self.num_qubits - 1}")
        if not keep:
            return np.array([[1.0]], dtype=COMPLEX)
        rest = [q for q in range(self.num_qubits) if q not in keep]
        tensor = self.data.reshape((2,) * self.num_qubits)
        permuted = np.transpose(tensor, [*keep, *rest])
        mat = permuted.reshape(2 ** len(keep), 2 ** len(rest))
        return np.ascontiguousarray(mat @ mat.conj().T)

    def entropy(self, base: float = 2.0) -> float:
        """Von Neumann entropy of the whole state.

        Exactly 0 for a normalised pure state (a state vector is pure by
        construction) — computed analytically rather than by diagonalising a
        ``4^n`` matrix we would only do it to get zero from.
        """
        return 0.0

    def entanglement_entropy(self, keep: Sequence[int], base: float = 2.0) -> float:
        """Von Neumann entropy of the reduced state on ``keep``.

        For a globally pure state this is the entanglement entropy of the
        ``keep`` / ``rest`` bipartition (Schmidt entropy): 0 iff the bipartition
        is a product state.  Computed from the Schmidt coefficients via SVD, so
        it stays affordable at large ``n``.
        """
        coeffs = self.schmidt_coefficients(keep)
        probs = coeffs**2
        probs = probs[probs > 1e-15]
        if probs.size == 0:
            return 0.0
        return float(-np.sum(probs * np.log(probs)) / np.log(base))

    def schmidt_coefficients(self, keep: Sequence[int]) -> np.ndarray:
        """Singular values of the ``keep``/``rest`` bipartition, descending.

        The kept axes are moved to the front *by permutation*, so the split works
        for arbitrary qubit sets (``keep=[0, 2]`` is a different matrix from
        ``keep=[0, 1]`` and must not be confused with one).
        """
        keep = sorted({int(q) for q in keep})
        rest = [q for q in range(self.num_qubits) if q not in keep]
        if not keep or not rest:
            return np.array([1.0])
        tensor = self.data.reshape((2,) * self.num_qubits)
        mat = np.transpose(tensor, [*keep, *rest]).reshape(2 ** len(keep), 2 ** len(rest))
        return np.linalg.svd(mat, compute_uv=False)

    def schmidt_rank(self, keep: Sequence[int], tol: float = 1e-9) -> int:
        """Number of non-zero Schmidt coefficients (1 = separable for this split)."""
        coeffs = self.schmidt_coefficients(keep)
        return int(np.sum(coeffs > tol))

    def bloch_vector(self, qubit: int) -> BlochVector:
        """Bloch vector of ``qubit``, computed from its reduced density matrix.

        For an entangled qubit the vector is *shorter* than 1 — that is the
        physically correct signature, and QScope displays the length so a
        partially-mixed reduced state is never mistaken for a pure one.
        """
        rho = self.reduced_density([qubit])
        return bloch_from_density(rho)

    def bloch_vectors(self) -> list[BlochVector]:
        return [self.bloch_vector(q) for q in range(self.num_qubits)]

    def expectation_pauli(self, pauli: str) -> float:
        """``<psi| P |psi>`` for a Pauli string such as ``"XZ"`` (qubit 0 first)."""
        pauli = pauli.replace(" ", "").upper()
        if len(pauli) != self.num_qubits:
            raise ValueError(f"Pauli string length {len(pauli)} != {self.num_qubits} qubits")
        flipped, phases = pauli_action_table(pauli, self.num_qubits)
        amps = self.data
        value = np.sum(np.conj(amps[flipped]) * phases * amps)
        return float(np.real(value))

    def pauli_expectations(self) -> dict[str, float]:
        """All non-trivial single-qubit Pauli expectations (tracer/UI helper)."""
        out: dict[str, float] = {}
        for q in range(self.num_qubits):
            for p in "XYZ":
                s = ["I"] * self.num_qubits
                s[q] = p
                out[f"{p}{q}"] = self.expectation_pauli("".join(s))
        return out

    def fidelity(self, other: "StateVector") -> float:
        """``|<psi|phi>|^2`` — the standard pure-state fidelity."""
        if other.num_qubits != self.num_qubits:
            raise ValueError("fidelity requires matching qubit counts")
        overlap = np.vdot(self.data, other.data)
        return float(abs(overlap) ** 2)

    def overlap(self, other: "StateVector") -> complex:
        """``<psi|phi>`` (complex, keeping the phase information)."""
        return complex(np.vdot(self.data, other.data))

    def dominant_basis(self) -> str:
        """Label of the most probable basis state."""
        return basis_label(self.num_qubits, int(np.argmax(self.probabilities())))

    def most_probable(self, count: int = 5) -> list[tuple[str, float]]:
        probs = self.probabilities()
        order = np.argsort(probs)[::-1][:count]
        return [(basis_label(self.num_qubits, int(i)), float(probs[i])) for i in order]

    # ------------------------------------------------------------------- evolve

    def apply_matrix(self, matrix: np.ndarray, targets: Sequence[int]) -> "StateVector":
        """Apply a dense operator (in place)."""
        self.data = apply_operator(self.data, matrix, targets, self.num_qubits)
        return self

    def apply_gate(
        self,
        name: str,
        targets: Sequence[int],
        params: Sequence[float] = (),
    ) -> "StateVector":
        """Apply a named gate (in place)."""
        targets = tuple(int(t) for t in targets)
        spec = gate_spec(name)
        if spec.num_qubits == -1:
            mat = spec.matrix(params, num_qubits=len(targets))
        else:
            if len(targets) != spec.num_qubits:
                raise ValueError(f"gate {name} acts on {spec.num_qubits} qubits, got {len(targets)}")
            mat = spec.matrix(params)
        return self.apply_matrix(mat, targets)

    def apply_controlled(
        self,
        name: str,
        controls: Sequence[int],
        targets: Sequence[int],
        params: Sequence[float] = (),
        control_values: Sequence[int] | None = None,
    ) -> "StateVector":
        """Apply ``name`` on ``targets`` conditioned on ``controls`` (in place)."""
        targets = tuple(int(t) for t in targets)
        controls = tuple(int(c) for c in controls)
        spec = gate_spec(name)
        inner = spec.matrix(params, num_qubits=len(targets)) if spec.num_qubits == -1 else spec.matrix(params)
        mat = controlled(inner, len(controls), control_values=control_values)
        return self.apply_matrix(mat, list(controls) + list(targets))

    def apply_unitary_sqrt(
        self, name: str, targets: Sequence[int], params: Sequence[float] = (), power: float = 0.5
    ) -> "StateVector":
        """Apply ``U ** power`` for a unitary gate via the spectral decomposition.

        Used by the time-machine "fractional step" view so a user can watch, say,
        a Hadamard being applied 25 %, 50 %, 75 % of the way.
        """
        spec = gate_spec(name)
        mat = spec.matrix(params)
        vals, vecs = np.linalg.eig(mat)
        powered = (vecs * (vals**power)) @ np.linalg.inv(vecs)
        return self.apply_matrix(powered, targets)

    # ------------------------------------------------------------------ measure

    def measure_qubit(
        self,
        qubit: int,
        rng: np.random.Generator | None = None,
        outcome: int | None = None,
    ) -> MeasurementOutcome:
        """Projectively measure one qubit, collapse the state and report ``p``."""
        rng = rng or np.random.default_rng()
        if outcome is None:
            p0 = float(np.sum(self.probabilities()[_zero_mask(self.num_qubits, qubit)]))
            outcome = 0 if rng.random() < p0 else 1
        collapsed, probability = collapse_statevector(self.data, self.num_qubits, qubit, outcome)
        if probability < ATOL:
            raise ValueError(
                f"outcome {outcome} on qubit {qubit} has probability {probability:.3e}; "
                "refusing to collapse"
            )
        self.data = collapsed / np.sqrt(probability)
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
        """Sample ``shots`` readouts without disturbing the state.

        ``readout_error`` is applied classically *after* sampling, so the
        reported ideal probabilities remain the true Born probabilities.
        """
        from qscope.core.measurement import apply_readout_error

        rng = rng or np.random.default_rng()
        qubits = list(range(self.num_qubits)) if qubits is None else sorted({int(q) for q in qubits})
        probs = self.normalized_probabilities()
        marginals = marginal_probabilities(probs, self.num_qubits, qubits)
        labels = sorted(marginals)
        counts, memory = sample_counts(
            [marginals[l] for l in labels], shots, rng, labels=labels
        )
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

    def terms(self, threshold: float = 1e-9, limit: int | None = None) -> list[dict[str, Any]]:
        """Serialisable amplitude table (basis, real, imag, magnitude, phase)."""
        out: list[dict[str, Any]] = []
        for idx in self.support(threshold):
            amp = complex(self.data[idx])
            out.append(
                {
                    "basis": basis_label(self.num_qubits, idx),
                    "index": idx,
                    "real": float(amp.real),
                    "imag": float(amp.imag),
                    "magnitude": float(abs(amp)),
                    "probability": float(abs(amp) ** 2),
                    "phase": float(np.angle(amp)),
                }
            )
        out.sort(key=lambda t: t["probability"], reverse=True)
        if limit is not None and limit < len(out):
            # Keep the largest terms but always report the true total probability.
            head = out[:limit]
            head.append(
                {
                    "basis": f"... (+{len(out) - limit} more)",
                    "index": -1,
                    "real": 0.0,
                    "imag": 0.0,
                    "magnitude": 0.0,
                    "probability": float(sum(t["probability"] for t in out[limit:])),
                    "phase": 0.0,
                    "aggregate": True,
                }
            )
            return head
        return out

    def to_dict(self, term_limit: int | None = 64) -> dict[str, Any]:
        """Full serialisable snapshot used by the API and the tracer."""
        probs = self.probabilities()
        return {
            "num_qubits": self.num_qubits,
            "dimension": self.dimension,
            "norm": self.norm(),
            "is_normalized": self.is_normalized(),
            "nonzero_amplitudes": self.nonzero_count(),
            "amplitudes": self.terms(limit=term_limit),
            "probability_max": float(np.max(probs)),
            "probability_min": float(np.min(probs)),
            "probability_total": float(np.sum(probs)),
            "bloch": [b.to_dict() for b in self.bloch_vectors()],
            "purity": self.purity(),
            "entropy": self.entropy(),
            "dominant_basis": self.dominant_basis(),
        }

    def pretty(self, threshold: float = 1e-9) -> str:
        """Human-readable Dirac notation, e.g. ``0.7071|00> + 0.7071|11>``."""
        parts: list[str] = []
        for t in self.terms(threshold):
            if t.get("aggregate"):
                continue
            mag, phase = t["magnitude"], t["phase"]
            if abs(phase) < 1e-12:
                coeff = f"{mag:.4f}"
            elif abs(abs(phase) - np.pi) < 1e-9:
                coeff = f"-{mag:.4f}"
            else:
                coeff = f"{mag:.4f}e^{phase:+.3f}i"
            parts.append(f"{coeff}|{t['basis']}>")
        return " + ".join(parts) if parts else "0"

    def __len__(self) -> int:
        return self.dimension

    def __iter__(self) -> Iterator[complex]:
        return iter(self.data)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"StateVector({self.num_qubits}q, {len(self.support())} terms)"


def _zero_mask(n: int, qubit: int) -> np.ndarray:
    """Boolean mask over basis indices where ``qubit`` reads 0."""
    shift = n - 1 - qubit
    idx = np.arange(2**n)
    return ((idx >> shift) & 1) == 0


def bloch_from_density(rho: np.ndarray) -> BlochVector:
    """Bloch coordinates from a single-qubit density matrix.

    ``r_i = Tr(sigma_i rho)`` — computed with the actual Pauli matrices so the
    signs cannot drift out of sync with the rest of the code base.
    """
    rho = np.asarray(rho, dtype=COMPLEX)
    if rho.shape != (2, 2):
        raise ValueError("bloch_from_density expects a 2x2 density matrix")
    values = [float(np.real(np.trace(PAULI_MATRICES[p] @ rho))) for p in "XYZ"]
    return BlochVector(*values)


def pauli_action_table(pauli: str, n: int) -> tuple[np.ndarray, np.ndarray]:
    """Precompute ``P|i> = phase_i |flip_i>`` for a Pauli string.

    ``X`` flips a bit, ``Y`` flips and multiplies by ``+i`` on ``|0>`` / ``-i`` on
    ``|1>``, ``Z`` multiplies by ``-1`` on ``|1>``.  Returned arrays are indexed by
    input basis index, so expectation values are a single vectorised sum.
    """
    indices = np.arange(2**n)
    flipped = indices.copy()
    phases = np.ones(2**n, dtype=COMPLEX)
    for q, p in enumerate(pauli):
        shift = n - 1 - q
        bits = (indices >> shift) & 1
        if p == "I":
            continue
        if p in ("X", "Y"):
            flipped ^= 1 << shift
        if p == "Y":
            phases = phases * np.where(bits == 0, 1j, -1j)
        elif p == "Z":
            phases = phases * np.where(bits == 0, 1.0, -1.0)
        elif p not in ("X", "Y", "I"):
            raise ValueError(f"unknown Pauli axis {p!r}")
    return flipped, phases


__all__ = [
    "MAX_QUBITS",
    "PAULI_MATRICES",
    "BlochVector",
    "StateVector",
    "bloch_from_density",
    "pauli_action_table",
]
