"""Noise models: Kraus channels, calibrated decoherence and readout error.

Parameter conventions (stated explicitly because the literature disagrees):

* **bit / phase / bit-phase flip** — ``rho -> (1-p) rho + p P rho P`` for
  ``P = X, Z, Y``.  ``p`` is the probability that the flip actually happened.
* **depolarizing** — ``rho -> (1-p) rho + p I/2`` for one qubit.  ``p`` is the
  total probability of a non-identity Pauli error, split equally between
  ``X, Y, Z``.  Kraus form ``[sqrt(1-3p/4) I, sqrt(p/4) X, sqrt(p/4) Y,
  sqrt(p/4) Z]``, which is exactly trace preserving (verified in the test suite).
* **amplitude damping** — ``gamma`` is the probability of |1> -> |0> relaxation
  (``T1`` decay):  ``gamma = 1 - exp(-t / T1)``.
* **phase damping** — ``lambda`` multiplies the off-diagonals by ``1 - lambda``
  (``T_phi`` decay): ``lambda = 1 - exp(-t / T_phi)``.
* **thermal relaxation** — amplitude damping with ``gamma = 1 - exp(-t/T1)``
  followed by phase damping with ``1/T_phi = 1/T2 - 1/(2*T1)``.
* **readout error** — *classical* bit flip on sampled counts.  It never touches
  the quantum state, and QScope reports it separately from coherent error.

Anything we cannot justify physically is flagged ``approximate`` in the report
rather than being sold as a device model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

import numpy as np

from qscope.core.measurement import is_trace_preserving
from qscope.core.tensor import COMPLEX

I2 = np.eye(2, dtype=COMPLEX)
X2 = np.array([[0, 1], [1, 0]], dtype=COMPLEX)
Y2 = np.array([[0, -1j], [1j, 0]], dtype=COMPLEX)
Z2 = np.array([[1, 0], [0, -1]], dtype=COMPLEX)

SCOPE_GATE = "gate"
SCOPE_IDLE = "idle"
SCOPE_GLOBAL = "global"
SCOPES = (SCOPE_GATE, SCOPE_IDLE, SCOPE_GLOBAL)


# ---------------------------------------------------------------------------
# Kraus builders
# ---------------------------------------------------------------------------


def _bit_flip_kraus(p: float) -> list[np.ndarray]:
    return [np.sqrt(1 - p) * I2, np.sqrt(p) * X2]


def _phase_flip_kraus(p: float) -> list[np.ndarray]:
    return [np.sqrt(1 - p) * I2, np.sqrt(p) * Z2]


def _bit_phase_flip_kraus(p: float) -> list[np.ndarray]:
    return [np.sqrt(1 - p) * I2, np.sqrt(p) * Y2]


def _depolarizing_kraus(p: float) -> list[np.ndarray]:
    """``rho -> (1-p) rho + p I/2`` (p = probability of a non-identity Pauli)."""
    if not 0.0 <= p <= 1.0:
        raise ValueError("depolarizing probability must be in [0, 1]")
    return [
        np.sqrt(1 - 3 * p / 4 + 0j) * I2,
        np.sqrt(p / 4 + 0j) * X2,
        np.sqrt(p / 4 + 0j) * Y2,
        np.sqrt(p / 4 + 0j) * Z2,
    ]


def _amplitude_damping_kraus(gamma: float) -> list[np.ndarray]:
    g = float(np.clip(gamma, 0.0, 1.0))
    return [
        np.array([[1, 0], [0, np.sqrt(1 - g)]], dtype=COMPLEX),
        np.array([[0, np.sqrt(g)], [0, 0]], dtype=COMPLEX),
    ]


def _phase_damping_kraus(lam: float) -> list[np.ndarray]:
    lam = float(np.clip(lam, 0.0, 1.0))
    return [np.sqrt(1 - lam / 2 + 0j) * I2, np.sqrt(lam / 2 + 0j) * Z2]


def _thermal_relaxation_kraus(t1: float, t2: float, duration: float) -> list[np.ndarray]:
    """Amplitude damping (T1) followed by pure dephasing (T_phi)."""
    if t1 <= 0 or t2 <= 0:
        raise ValueError("T1 and T2 must be positive")
    if t2 > 2 * t1 + 1e-12:
        raise ValueError(
            f"unphysical relaxation: T2={t2:g} > 2*T1={2 * t1:g}. "
            "Physical devices always satisfy T2 <= 2*T1."
        )
    gamma = 1 - np.exp(-duration / t1)
    t_phi = 1.0 / max(1.0 / t2 - 1.0 / (2 * t1), 1e-12)
    lam = 1 - np.exp(-duration / t_phi)
    a0, a1 = _amplitude_damping_kraus(gamma)
    d0, d1 = _phase_damping_kraus(lam)
    # Composition of the two channels: sum over products of Kraus operators.
    return [d0 @ a0, d0 @ a1, d1 @ a0, d1 @ a1]


def _amp_phase_kraus(gamma: float, lam: float) -> list[np.ndarray]:
    a0, a1 = _amplitude_damping_kraus(gamma)
    d0, d1 = _phase_damping_kraus(lam)
    return [d0 @ a0, d0 @ a1, d1 @ a0, d1 @ a1]


KRAUS_BUILDERS: dict[str, tuple[Any, tuple[str, ...], str]] = {
    "bit_flip": (_bit_flip_kraus, ("p",), "Pauli-X error with probability p"),
    "phase_flip": (_phase_flip_kraus, ("p",), "Pauli-Z (dephasing) error with probability p"),
    "bit_phase_flip": (_bit_phase_flip_kraus, ("p",), "Pauli-Y error with probability p"),
    "depolarizing": (_depolarizing_kraus, ("p",), "rho -> (1-p) rho + p I/2"),
    "amplitude_damping": (
        _amplitude_damping_kraus,
        ("gamma",),
        "T1 relaxation: |1> -> |0> with probability gamma",
    ),
    "phase_damping": (_phase_damping_kraus, ("lambda",), "Off-diagonals scaled by (1 - lambda)"),
    "thermal_relaxation": (
        _thermal_relaxation_kraus,
        ("t1", "t2", "duration"),
        "Combined T1 relaxation and T_phi dephasing over a duration",
    ),
    "amplitude_phase": (
        _amp_phase_kraus,
        ("gamma", "lambda"),
        "Amplitude damping (gamma) composed with phase damping (lambda)",
    ),
}
"""Available Kraus channels, their parameter names and their physical meaning."""


def build_kraus(kind: str, params: dict[str, float] | Sequence[float]) -> list[np.ndarray]:
    """Build (and validate) the Kraus operators of a named channel."""
    if kind not in KRAUS_BUILDERS:
        raise KeyError(f"unknown noise channel {kind!r}; available: {sorted(KRAUS_BUILDERS)}")
    builder, names, _ = KRAUS_BUILDERS[kind]
    if isinstance(params, dict):
        values = [float(params[n]) for n in names]
    else:
        values = [float(v) for v in params]
    if len(values) != len(names):
        raise ValueError(f"channel {kind} expects parameters {names}")
    kraus = builder(*values)
    if not is_trace_preserving(kraus):
        raise ValueError(f"channel {kind} is not trace preserving with params {params}")
    return kraus


# ---------------------------------------------------------------------------
# channels and models
# ---------------------------------------------------------------------------


@dataclass
class NoiseChannel:
    """One typed error source, with an explicit scope.

    ``scope='gate'``  — applied on the qubits of a matching gate, right after it.
    ``scope='idle'``  — applied to every qubit *not* touched by the operation
                        (models decoherence while the qubit waits).
    ``scope='global'``— applied once to every qubit at the end of the circuit
                        (state-preparation or readout error).
    """

    kind: str
    params: dict[str, float] = field(default_factory=dict)
    scope: str = SCOPE_GATE
    qubits: list[int] | None = None
    after_gates: list[str] | None = None
    label: str = ""
    approximate: bool = False

    def __post_init__(self) -> None:
        if self.scope not in SCOPES:
            raise ValueError(f"unknown scope {self.scope!r}")
        if self.kind not in KRAUS_BUILDERS:
            raise KeyError(f"unknown channel {self.kind!r}")
        builder, names, _ = KRAUS_BUILDERS[self.kind]
        for name in names:
            if name not in self.params:
                raise ValueError(f"channel {self.kind} needs parameter {name!r}")
        # validates the Kraus set immediately, so a bad model cannot reach a run
        build_kraus(self.kind, self.params)

    @property
    def description(self) -> str:
        _, _, text = KRAUS_BUILDERS[self.kind]
        pretty = ", ".join(f"{k}={v:g}" for k, v in self.params.items())
        return f"{text} ({pretty})"

    def kraus(self, targets: int = 1) -> list[np.ndarray]:
        """Kraus operators for this channel (tensor-powered for multi-qubit targets)."""
        base = build_kraus(self.kind, self.params)
        if targets <= 1:
            return base
        # Independent single-qubit noise on k qubits = channel tensor-powered k times.
        out: list[np.ndarray] = base
        for _ in range(targets - 1):
            out = [np.kron(a, b) for a in out for b in base]
        return out

    def matches_gate(self, gate_name: str) -> bool:
        return self.after_gates is None or gate_name in self.after_gates

    def covers_qubit(self, qubit: int) -> bool:
        return self.qubits is None or qubit in self.qubits

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "params": dict(self.params),
            "scope": self.scope,
            "qubits": list(self.qubits) if self.qubits is not None else None,
            "after_gates": list(self.after_gates) if self.after_gates is not None else None,
            "label": self.label,
            "approximate": self.approximate,
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "NoiseChannel":
        return cls(
            kind=payload["kind"],
            params={k: float(v) for k, v in payload.get("params", {}).items()},
            scope=payload.get("scope", SCOPE_GATE),
            qubits=payload.get("qubits"),
            after_gates=payload.get("after_gates"),
            label=payload.get("label", ""),
            approximate=bool(payload.get("approximate", False)),
        )


@dataclass
class NoiseModel:
    """A complete error model for a simulation.

    The uniform gate-error knobs (``one_qubit_gate_error`` etc.) are depolarising
    channels applied on the gate's own qubits.  ``idle_error`` models per-gate
    decoherence of the qubits that are *waiting*.  Explicit ``channels`` can add
    anything else (T1/T2, correlated errors, targeted qubits).
    """

    name: str = "ideal"
    channels: list[NoiseChannel] = field(default_factory=list)
    readout_error: float = 0.0
    one_qubit_gate_error: float = 0.0
    two_qubit_gate_error: float = 0.0
    multi_qubit_gate_error: float = 0.0
    idle_error: float = 0.0
    description: str = ""
    calibrated: bool = False
    measurement_error_asymmetric: bool = False

    # ------------------------------------------------------------- presets

    @classmethod
    def ideal(cls) -> "NoiseModel":
        return cls(name="ideal", description="No noise: exact unitary evolution.")

    @classmethod
    def depolarizing(cls, p: float, *, qubits: list[int] | None = None) -> "NoiseModel":
        return cls(
            name=f"depolarizing p={p:g}",
            channels=[
                NoiseChannel(
                    "depolarizing",
                    {"p": float(p)},
                    scope=SCOPE_GATE,
                    qubits=qubits,
                    label="depolarizing (per gate)",
                )
            ],
            description=(
                "Depolarising noise applied after every gate on the gate's own qubits. "
                "p is the probability of a non-identity Pauli error on each affected qubit."
            ),
        )

    @classmethod
    def bit_flip(cls, p: float, *, qubits: list[int] | None = None) -> "NoiseModel":
        return cls(
            name=f"bit flip p={p:g}",
            channels=[NoiseChannel("bit_flip", {"p": float(p)}, qubits=qubits, label="bit flip")],
            description="Classical bit-flip error after every gate.",
        )

    @classmethod
    def phase_flip(cls, p: float, *, qubits: list[int] | None = None) -> "NoiseModel":
        return cls(
            name=f"phase flip p={p:g}",
            channels=[NoiseChannel("phase_flip", {"p": float(p)}, qubits=qubits, label="phase flip")],
            description="Dephasing error after every gate.",
        )

    @classmethod
    def amplitude_damping(cls, gamma: float, *, qubits: list[int] | None = None) -> "NoiseModel":
        return cls(
            name=f"amplitude damping gamma={gamma:g}",
            channels=[
                NoiseChannel("amplitude_damping", {"gamma": float(gamma)}, qubits=qubits, label="T1 relaxation")
            ],
            description="Energy relaxation applied after every gate.",
        )

    @classmethod
    def phase_damping(cls, lam: float, *, qubits: list[int] | None = None) -> "NoiseModel":
        return cls(
            name=f"phase damping lambda={lam:g}",
            channels=[NoiseChannel("phase_damping", {"lambda": float(lam)}, qubits=qubits, label="dephasing")],
            description="Pure dephasing applied after every gate.",
        )

    @classmethod
    def thermal(
        cls,
        t1: float,
        t2: float,
        gate_time: float,
        *,
        one_qubit_time: float | None = None,
        two_qubit_time: float | None = None,
        readout_error: float = 0.0,
        qubits: list[int] | None = None,
    ) -> "NoiseModel":
        """Calibrated relaxation/dephasing model with per-gate durations (microseconds)."""
        model = cls(
            name=f"thermal T1={t1:g}us T2={t2:g}us",
            readout_error=float(readout_error),
            calibrated=True,
            description=(
                f"Amplitude damping (T1={t1:g} us) and dephasing "
                f"(T2={t2:g} us) acting for the duration of each gate "
                f"(1q={one_qubit_time or gate_time:g} us, 2q={two_qubit_time or gate_time:g} us)."
            ),
        )
        one_time = one_qubit_time or gate_time
        two_time = two_qubit_time or gate_time
        model.channels.append(
            NoiseChannel(
                "thermal_relaxation",
                {"t1": float(t1), "t2": float(t2), "duration": float(one_time)},
                scope=SCOPE_GATE,
                after_gates=[
                    "I", "X", "Y", "Z", "H", "S", "SDG", "T", "TDG", "SX", "SXDG",
                    "RX", "RY", "RZ", "P", "U2", "U3",
                ],
                label="1q relaxation",
            )
        )
        model.channels.append(
            NoiseChannel(
                "thermal_relaxation",
                {"t1": float(t1), "t2": float(t2), "duration": float(two_time)},
                scope=SCOPE_GATE,
                after_gates=["CNOT", "CX", "CZ", "CY", "CH", "SWAP", "ISWAP", "ISWAPDG", "RXX", "RYY", "RZZ", "RZX"],
                label="2q relaxation",
            )
        )
        if qubits is not None:
            for ch in model.channels:
                ch.qubits = list(qubits)
        return model

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "NoiseModel":
        return cls(
            name=payload.get("name", "custom"),
            channels=[NoiseChannel.from_dict(c) for c in payload.get("channels", [])],
            readout_error=float(payload.get("readout_error", 0.0)),
            one_qubit_gate_error=float(payload.get("one_qubit_gate_error", 0.0)),
            two_qubit_gate_error=float(payload.get("two_qubit_gate_error", 0.0)),
            multi_qubit_gate_error=float(payload.get("multi_qubit_gate_error", 0.0)),
            idle_error=float(payload.get("idle_error", 0.0)),
            description=payload.get("description", ""),
            calibrated=bool(payload.get("calibrated", False)),
            measurement_error_asymmetric=bool(payload.get("measurement_error_asymmetric", False)),
        )

    # -------------------------------------------------------------- queries

    def is_ideal(self) -> bool:
        return (
            not self.channels
            and self.readout_error == 0
            and self.one_qubit_gate_error == 0
            and self.two_qubit_gate_error == 0
            and self.multi_qubit_gate_error == 0
            and self.idle_error == 0
        )

    @property
    def approximate(self) -> bool:
        return any(ch.approximate for ch in self.channels)

    def gate_error_for(self, arity: int) -> float:
        if arity == 1:
            return self.one_qubit_gate_error
        if arity == 2:
            return self.two_qubit_gate_error
        return self.multi_qubit_gate_error

    def gate_channels(self, op: Any, num_qubits: int) -> list[tuple[list[np.ndarray], list[int]]]:
        """Resolve the Kraus channels to apply right after operation ``op``.

        Returns a list of ``(kraus, targets)`` pairs.  Multi-qubit channels are
        only supported with single-qubit targets here; anything else would need a
        correlated Kraus set, which we would rather refuse than approximate.
        """
        out: list[tuple[list[np.ndarray], list[int]]] = []
        involved = list(op.qubits)
        arity = len(list(op.targets)) + len(list(op.controls))

        for channel in self.channels:
            if channel.scope == SCOPE_GATE:
                if op.kind != "gate" or not channel.matches_gate(op.name):
                    continue
                targets = [q for q in involved if channel.covers_qubit(q)] or []
                for q in targets:
                    out.append((channel.kraus(1), [q]))
            elif channel.scope == SCOPE_IDLE:
                idle = [q for q in range(num_qubits) if q not in involved and channel.covers_qubit(q)]
                for q in idle:
                    out.append((channel.kraus(1), [q]))
            elif channel.scope == SCOPE_GLOBAL:
                for q in range(num_qubits):
                    if channel.covers_qubit(q):
                        out.append((channel.kraus(1), [q]))

        uniform = self.gate_error_for(arity) if op.kind == "gate" else 0.0
        if uniform > 0:
            for q in involved:
                out.append((_depolarizing_kraus(uniform), [q]))
        if self.idle_error > 0:
            for q in range(num_qubits):
                if q not in involved:
                    out.append((_depolarizing_kraus(self.idle_error), [q]))
        return out

    def summary(self) -> dict[str, Any]:
        """Human/UI summary with an honest label of what is and isn't modelled."""
        return {
            "name": self.name,
            "ideal": self.is_ideal(),
            "calibrated": self.calibrated,
            "approximate": self.approximate,
            "readout_error": self.readout_error,
            "one_qubit_gate_error": self.one_qubit_gate_error,
            "two_qubit_gate_error": self.two_qubit_gate_error,
            "multi_qubit_gate_error": self.multi_qubit_gate_error,
            "idle_error": self.idle_error,
            "channels": [c.to_dict() for c in self.channels],
            "description": self.description,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "channels": [c.to_dict() for c in self.channels],
            "readout_error": self.readout_error,
            "one_qubit_gate_error": self.one_qubit_gate_error,
            "two_qubit_gate_error": self.two_qubit_gate_error,
            "multi_qubit_gate_error": self.multi_qubit_gate_error,
            "idle_error": self.idle_error,
            "description": self.description,
            "calibrated": self.calibrated,
            "measurement_error_asymmetric": self.measurement_error_asymmetric,
        }

    def descriptive_label(self) -> str:
        """Short tag used in charts and reports: what kind of simulation was run."""
        if self.is_ideal():
            return "IDEAL (unitary)"
        if self.calibrated:
            return "NOISY (calibrated T1/T2)"
        return "NOISY (channel model)"

    def total_error_budget(self, gate_count_1q: int, gate_count_2q: int, depth: int) -> float:
        """Rough depolarising probability that at least one error occurred.

        ``1 - (1-e1)^n1 (1-e2)^n2 (1-e_idle)^(depth*n)``.  Labelled a *budget*
        because it ignores correlation and per-qubit structure — it is a
        first-order estimate, and the report says so.
        """
        from math import pow

        p = (
            pow(max(1 - self.one_qubit_gate_error, 0.0), gate_count_1q)
            * pow(max(1 - self.two_qubit_gate_error, 0.0), gate_count_2q)
        )
        return 1.0 - p


def noise_model_catalog() -> list[dict[str, Any]]:
    """Available channel types and parameter metadata for the UI."""
    return [
        {
            "kind": kind,
            "params": list(names),
            "description": text,
            "defaults": {name: (0.01 if name in {"p"} else 0.05 if name in {"gamma", "lambda"} else 1.0) for name in names},
        }
        for kind, (_, names, text) in KRAUS_BUILDERS.items()
    ]


def combine_models(*models: NoiseModel) -> NoiseModel:
    """Merge several models into one (used by experiments that stack error sources)."""
    channels: list[NoiseChannel] = []
    for m in models:
        channels.extend(NoiseChannel.from_dict(c.to_dict()) for c in m.channels)
    return NoiseModel(
        name=" + ".join(m.name for m in models),
        channels=channels,
        readout_error=sum(m.readout_error for m in models),
        one_qubit_gate_error=sum(m.one_qubit_gate_error for m in models),
        two_qubit_gate_error=sum(m.two_qubit_gate_error for m in models),
        multi_qubit_gate_error=sum(m.multi_qubit_gate_error for m in models),
        idle_error=sum(m.idle_error for m in models),
        description="Logical OR of the combined error sources (first-order).",
        calibrated=all(m.calibrated for m in models),
        approximate=any(m.approximate for m in models),
    )


__all__ = [
    "KRAUS_BUILDERS",
    "NoiseChannel",
    "NoiseModel",
    "SCOPE_GATE",
    "SCOPE_GLOBAL",
    "SCOPE_IDLE",
    "SCOPES",
    "build_kraus",
    "combine_models",
    "noise_model_catalog",
]
