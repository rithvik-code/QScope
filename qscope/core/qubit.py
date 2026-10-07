"""Qubit and classical-bit register bookkeeping.

These are lightweight descriptions of *what a wire is*, not of state.  The
simulation engines deliberately do not depend on them (they work on raw index
arrays) so that the hot loops stay allocation-free.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence


@dataclass(frozen=True)
class Qubit:
    """A single logical qubit wire."""

    index: int
    label: str = ""

    @property
    def name(self) -> str:
        return self.label or f"q{self.index}"


@dataclass(frozen=True)
class Clbit:
    """A single classical bit wire."""

    index: int
    label: str = ""

    @property
    def name(self) -> str:
        return self.label or f"c{self.index}"


class QubitRegister:
    """An ordered collection of qubits with stable labels.

    Labels survive compaction/reordering, which the optimizer needs: after
    removing an unused wire the remaining qubits keep their names, so trace
    output stays comparable across "before" and "after" runs.
    """

    def __init__(self, num_qubits: int, labels: Sequence[str] | None = None) -> None:
        if num_qubits < 1:
            raise ValueError("a register needs at least one qubit")
        if num_qubits > 30:
            raise ValueError("QScope refuses to allocate more than 30 qubit wires")
        if labels is not None and len(labels) != num_qubits:
            raise ValueError("label count must match num_qubits")
        self.num_qubits = num_qubits
        self._labels = list(labels) if labels else [f"q{i}" for i in range(num_qubits)]

    @property
    def qubits(self) -> list[Qubit]:
        return [Qubit(i, self._labels[i]) for i in range(self.num_qubits)]

    @property
    def labels(self) -> list[str]:
        return list(self._labels)

    def label(self, index: int) -> str:
        return self._labels[index]

    def index_of(self, label: str) -> int:
        try:
            return self._labels.index(label)
        except ValueError as exc:  # pragma: no cover - defensive
            raise KeyError(f"unknown qubit label {label!r}") from exc

    def subset(self, keep: Sequence[int]) -> "QubitRegister":
        keep = list(keep)
        return QubitRegister(len(keep), [self._labels[i] for i in keep])

    def to_dict(self) -> dict[str, Any]:
        return {"num_qubits": self.num_qubits, "labels": self.labels}

    def __len__(self) -> int:  # pragma: no cover - trivial
        return self.num_qubits

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"QubitRegister({self.num_qubits}, {self._labels})"


class ClassicalRegister:
    """Classical bits produced by measurement."""

    def __init__(self, num_bits: int, labels: Sequence[str] | None = None) -> None:
        if num_bits < 0:
            raise ValueError("negative register size")
        self.num_bits = num_bits
        self._labels = list(labels) if labels else [f"c{i}" for i in range(num_bits)]
        self._bits: list[int] = [0] * num_bits

    def write(self, index: int, value: int) -> None:
        if not 0 <= index < self.num_bits:
            raise IndexError(f"classical bit {index} out of range")
        self._bits[index] = int(bool(value))

    def read(self, index: int) -> int:
        return self._bits[index]

    def value(self) -> int:
        out = 0
        for b in self._bits:
            out = (out << 1) | b
        return out

    def label(self) -> str:
        return "".join(str(b) for b in self._bits)

    def reset(self) -> None:
        self._bits = [0] * self.num_bits

    @property
    def bits(self) -> list[int]:
        return list(self._bits)

    @property
    def labels(self) -> list[str]:
        return list(self._labels)

    def to_dict(self) -> dict[str, Any]:
        return {
            "num_bits": self.num_bits,
            "labels": self.labels,
            "value": self.label(),
        }


__all__ = ["Clbit", "ClassicalRegister", "Qubit", "QubitRegister"]
