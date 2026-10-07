"""Measurement primitives: projective readout, shot sampling and readout error.

QScope distinguishes three things that are easy to conflate:

* **Probabilities** — exact Born-rule probabilities of the current state.
* **Counts** — integers obtained by sampling those probabilities ``shots`` times.
* **Readout error** — a *classical* bit-flip applied to sampled counts; it never
  changes the quantum state, only what the instrument reports.

Keeping those apart matters: a noisy histogram with an ideal state is a readout
problem, not a decoherence problem, and QScope labels it that way.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Sequence

import numpy as np

from qscope.core.tensor import ATOL, COMPLEX, basis_label, is_close


@dataclass
class MeasurementOutcome:
    """Result of a single projective measurement."""

    qubits: tuple[int, ...]
    outcome: int
    label: str
    probability: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "qubits": list(self.qubits),
            "outcome": self.outcome,
            "label": self.label,
            "probability": self.probability,
        }


@dataclass
class MeasurementResult:
    """Aggregated shot results for a set of measured qubits."""

    qubits: list[int]
    shots: int
    counts: dict[str, int]
    ideal_probabilities: dict[str, float]
    memory: list[str] = field(default_factory=list)
    readout_error: float = 0.0

    @property
    def sampled_probabilities(self) -> dict[str, float]:
        total = sum(self.counts.values()) or 1
        return {k: v / total for k, v in self.counts.items()}

    def entropy(self, base: float = 2.0) -> float:
        """Shannon entropy of the *sampled* distribution (diagnostic only)."""
        probs = np.array(list(self.sampled_probabilities.values()), dtype=float)
        probs = probs[probs > 0]
        return float(-np.sum(probs * np.log(probs)) / np.log(base))

    def to_dict(self, include_memory: bool = False) -> dict[str, Any]:
        out: dict[str, Any] = {
            "qubits": self.qubits,
            "shots": self.shots,
            "counts": self.counts,
            "ideal_probabilities": self.ideal_probabilities,
            "sampled_probabilities": self.sampled_probabilities,
            "readout_error": self.readout_error,
            "entropy": self.entropy(),
        }
        if include_memory:
            out["memory"] = self.memory
        return out


def normalize_probabilities(probs: np.ndarray) -> np.ndarray:
    """Clip negatives (rounding noise) and renormalise a probability vector."""
    p = np.clip(np.asarray(probs, dtype=float), 0.0, None)
    total = p.sum()
    if total <= 0:
        raise ValueError("probability vector sums to zero")
    return p / total


def sample_counts(
    probabilities: Sequence[float] | np.ndarray,
    shots: int,
    rng: np.random.Generator,
    labels: Sequence[str] | None = None,
    *,
    threshold: float = 1e-12,
) -> tuple[dict[str, int], list[str]]:
    """Sample ``shots`` outcomes from ``probabilities``.

    Uses a single multinomial draw per shot-group rather than ``shots`` separate
    random calls: for 100k shots on 20 qubits that is ~10 ms instead of seconds.

    Returns ``(counts, memory)`` where ``memory`` is the raw shot list (kept
    because experiment reports need it for reproducibility checks, but trimmed
    by callers for large shot counts).
    """
    if shots <= 0:
        raise ValueError("shots must be positive")
    probs = normalize_probabilities(probabilities)
    if labels is None:
        n = int(round(np.log2(len(probs))))
        labels = [basis_label(n, i) for i in range(len(probs))]
    idx = np.arange(len(probs))
    keep = probs > threshold
    if not np.any(keep):
        keep = np.array([int(np.argmax(probs))])
    kept_probs = probs[keep]
    kept_probs = kept_probs / kept_probs.sum()
    draws = rng.multinomial(shots, kept_probs)
    counts: dict[str, int] = {}
    memory: list[str] = []
    for position, count in zip(np.nonzero(keep)[0], draws):
        if count == 0:
            continue
        label = labels[int(position)]
        counts[label] = int(count)
        memory.extend([label] * int(count))
    for label in labels:
        counts.setdefault(label, 0)
    return counts, memory


def marginal_probabilities(
    probabilities: Sequence[float] | np.ndarray,
    n: int,
    qubits: Sequence[int],
) -> dict[str, float]:
    """Born probabilities of the computational-basis values of ``qubits``."""
    probs = normalize_probabilities(probabilities)
    qubits = sorted({int(q) for q in qubits})
    acc: dict[str, float] = {}
    mask = [n - 1 - q for q in qubits]
    for index, p in enumerate(probs):
        if p < ATOL:
            continue
        label = "".join(str((index >> m) & 1) for m in mask)
        acc[label] = acc.get(label, 0.0) + float(p)
    return dict(sorted(acc.items()))


def apply_readout_error(
    counts: dict[str, int],
    num_bits: int,
    error: float,
    rng: np.random.Generator,
    *,
    symmetric: bool = True,
) -> tuple[dict[str, int], float]:
    """Apply classical readout error to sampled counts.

    Each bit is flipped independently with probability ``error`` when
    ``symmetric`` is true (a depolarised readout channel); otherwise only
    ``1 -> 0`` flips occur, which is the usual asymmetry of superconducting
    readout.  Returns ``(new_counts, effective_error)``.
    """
    if error <= 0 or not counts:
        return counts, 0.0
    corrupted: Counter[str] = Counter()
    for label, count in counts.items():
        for _ in range(count):
            bits = list(label)
            for i, ch in enumerate(bits):
                if symmetric:
                    if rng.random() < error:
                        bits[i] = "1" if ch == "0" else "0"
                elif ch == "1" and rng.random() < error:
                    bits[i] = "0"
            corrupted["".join(bits)] += 1
    return dict(corrupted), float(error)


def collapse_statevector(
    state: np.ndarray,
    n: int,
    qubit: int,
    outcome: int,
) -> tuple[np.ndarray, float]:
    """Projectively measure ``qubit`` in the computational basis.

    Returns ``(collapsed_state, probability)``.  The state is *not* renormalised
    here; the caller divides by ``sqrt(probability)`` so that the probability
    that was reported is the one actually used.
    """
    probs = np.abs(state) ** 2
    mask = [n - 1 - qubit]
    p = 0.0
    new = np.zeros_like(state)
    for index, amp in enumerate(state):
        bit = (index >> mask[0]) & 1
        if bit == outcome:
            new[index] = amp
            p += probs[index]
    return new, float(p)


def tensor_block_diagonal(blocks: Sequence[np.ndarray]) -> np.ndarray:
    """Block-diagonal matrix from same-shaped PSD blocks (Kraus validation helper)."""
    dim = sum(b.shape[0] for b in blocks)
    out = np.zeros((dim, dim), dtype=COMPLEX)
    offset = 0
    for b in blocks:
        k = b.shape[0]
        out[offset : offset + k, offset : offset + k] = b
        offset += k
    return out


def is_trace_preserving(kraus: Sequence[np.ndarray]) -> bool:
    """Check ``sum_i K_i^dagger K_i = I`` within tolerance."""
    if not kraus:
        return False
    total = sum(k.conj().T @ k for k in kraus)
    return is_close(total, np.eye(total.shape[0], dtype=COMPLEX))


__all__ = [
    "MeasurementOutcome",
    "MeasurementResult",
    "apply_readout_error",
    "collapse_statevector",
    "is_trace_preserving",
    "marginal_probabilities",
    "normalize_probabilities",
    "sample_counts",
    "tensor_block_diagonal",
]
