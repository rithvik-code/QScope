"""Gate library: exact matrices, inverses and structural metadata.

Every gate QScope can execute is described by a :class:`GateSpec`, which carries
the matrix builder, the parameter names, and the *structural* facts the
optimizer needs (is it self-inverse? is it diagonal? what is its adjoint?).

Hard-coded metadata (instead of deriving it numerically at runtime) keeps the
optimizer honest and fast, and the test-suite verifies the metadata against the
matrices so the tables can never drift.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from qscope.core.tensor import COMPLEX, controlled, is_close, kron_list

Builder = Callable[..., np.ndarray]


@dataclass(frozen=True)
class GateSpec:
    """Static description of a quantum operation.

    Attributes
    ----------
    name:
        Canonical (upper-case) gate name used everywhere in QScope.
    num_qubits:
        Arity.  ``-1`` marks a variable-arity gate (currently only ``MCX``).
    params:
        Names of the real parameters, in matrix-builder order.
    self_inverse:
        ``U^2 = I`` — safe to cancel two adjacent applications.
    diagonal:
        ``U`` is diagonal in the computational basis, so it commutes with every
        other diagonal gate (the optimizer uses this to move gates around).
    dagger:
        Name of the adjoint gate, when it has a distinct name.
    phase_dagger:
        For parameterized gates: the parameter map implementing the adjoint
        (e.g. ``RX(t)^dagger = RX(-t)``).
    controlled_only:
        True when the gate's matrix is defined as a controlled operation.
    """

    name: str
    num_qubits: int
    params: tuple[str, ...] = ()
    builder: Builder = field(default=lambda: np.eye(2, dtype=COMPLEX), repr=False)
    self_inverse: bool = False
    diagonal: bool = False
    dagger: str | None = None
    phase_dagger: Callable[[Sequence[float]], Sequence[float]] | None = None
    display: str | None = None
    category: str = "single-qubit"
    description: str = ""
    custom: bool = False

    def matrix(self, params: Sequence[float] = (), *, num_qubits: int | None = None) -> np.ndarray:
        """Build the dense matrix for these parameters.

        Fixed-arity gates call ``builder(*params)``; variable-arity gates (arity
        ``-1``) call ``builder(num_qubits, *params)``.
        """
        arity = self.num_qubits if num_qubits is None else num_qubits
        if arity < 1:
            raise ValueError(f"gate {self.name} needs an explicit qubit count")
        if len(params) != len(self.params):
            raise ValueError(
                f"gate {self.name} expects {len(self.params)} parameter(s) "
                f"{list(self.params)}, got {len(params)}"
            )
        if self.num_qubits == -1:
            mat = self.builder(arity, *params)
        else:
            mat = self.builder(*params)
        mat = np.asarray(mat, dtype=COMPLEX)
        expected = 2**arity
        if mat.shape != (expected, expected):
            raise ValueError(
                f"gate {self.name} built shape {mat.shape}, expected {(expected, expected)}"
            )
        return mat


# ---------------------------------------------------------------------------
# matrix builders
# ---------------------------------------------------------------------------

I2 = np.eye(2, dtype=COMPLEX)
X2 = np.array([[0, 1], [1, 0]], dtype=COMPLEX)
Y2 = np.array([[0, -1j], [1j, 0]], dtype=COMPLEX)
Z2 = np.array([[1, 0], [0, -1]], dtype=COMPLEX)
H2 = np.array([[1, 1], [1, -1]], dtype=COMPLEX) / np.sqrt(2)
S2 = np.array([[1, 0], [0, 1j]], dtype=COMPLEX)
SDG2 = np.array([[1, 0], [0, -1j]], dtype=COMPLEX)
T2 = np.array([[1, 0], [0, np.exp(1j * np.pi / 4)]], dtype=COMPLEX)
TDG2 = np.array([[1, 0], [0, np.exp(-1j * np.pi / 4)]], dtype=COMPLEX)
SX2 = np.array([[1 + 1j, 1 - 1j], [1 - 1j, 1 + 1j]], dtype=COMPLEX) / 2
SWAP4 = np.array([[1, 0, 0, 0], [0, 0, 1, 0], [0, 1, 0, 0], [0, 0, 0, 1]], dtype=COMPLEX)
ISWAP4 = np.array([[1, 0, 0, 0], [0, 0, 1j, 0], [0, 1j, 0, 0], [0, 0, 0, 1]], dtype=COMPLEX)
ISWAPDG4 = ISWAP4.conj().T.copy()


def _rx(theta: float) -> np.ndarray:
    c, s = np.cos(theta / 2), np.sin(theta / 2)
    return np.array([[c, -1j * s], [-1j * s, c]], dtype=COMPLEX)


def _ry(theta: float) -> np.ndarray:
    c, s = np.cos(theta / 2), np.sin(theta / 2)
    return np.array([[c, -s], [s, c]], dtype=COMPLEX)


def _rz(theta: float) -> np.ndarray:
    return np.array(
        [[np.exp(-1j * theta / 2), 0], [0, np.exp(1j * theta / 2)]], dtype=COMPLEX
    )


def _p(phi: float) -> np.ndarray:
    """Phase gate U1(phi) = diag(1, e^{i phi})."""
    return np.array([[1, 0], [0, np.exp(1j * phi)]], dtype=COMPLEX)


def _u3(theta: float, phi: float, lam: float) -> np.ndarray:
    """Generic single-qubit unitary U3(theta, phi, lambda)."""
    c, s = np.cos(theta / 2), np.sin(theta / 2)
    return np.array(
        [
            [c, -np.exp(1j * lam) * s],
            [np.exp(1j * phi) * s, np.exp(1j * (phi + lam)) * c],
        ],
        dtype=COMPLEX,
    )


def _u2(phi: float, lam: float) -> np.ndarray:
    return _u3(np.pi / 2, phi, lam)


def _rxx(theta: float) -> np.ndarray:
    c, s = np.cos(theta / 2), np.sin(theta / 2)
    return np.array(
        [
            [c, 0, 0, -1j * s],
            [0, c, -1j * s, 0],
            [0, -1j * s, c, 0],
            [-1j * s, 0, 0, c],
        ],
        dtype=COMPLEX,
    )


def _ryy(theta: float) -> np.ndarray:
    c, s = np.cos(theta / 2), np.sin(theta / 2)
    return np.array(
        [
            [c, 0, 0, 1j * s],
            [0, c, -1j * s, 0],
            [0, -1j * s, c, 0],
            [1j * s, 0, 0, c],
        ],
        dtype=COMPLEX,
    )


def _rzz(theta: float) -> np.ndarray:
    return np.diag(
        [np.exp(-1j * theta / 2), np.exp(1j * theta / 2), np.exp(1j * theta / 2), np.exp(-1j * theta / 2)]
    ).astype(COMPLEX)


def _rzx(theta: float) -> np.ndarray:
    """RZX(theta) = exp(-i theta/2 * Z tensor X)."""
    c, s = np.cos(theta / 2), np.sin(theta / 2)
    return np.array(
        [
            [c, -1j * s, 0, 0],
            [-1j * s, c, 0, 0],
            [0, 0, c, 1j * s],
            [0, 0, 1j * s, c],
        ],
        dtype=COMPLEX,
    )


def _negate(params: Sequence[float]) -> tuple[float, ...]:
    return tuple(-p for p in params)


def _u3_dagger(params: Sequence[float]) -> tuple[float, ...]:
    theta, phi, lam = params
    return (-theta, -lam, -phi)


def _u2_dagger(params: Sequence[float]) -> tuple[float, ...]:
    phi, lam = params
    return (-lam, -phi)


def _mcx_builder(num_qubits: int) -> np.ndarray:
    """Multi-controlled X: ``num_qubits - 1`` controls and one target."""
    if num_qubits < 2:
        raise ValueError("MCX needs at least 2 qubits")
    return controlled(X2, num_qubits - 1)


def _build_registry() -> dict[str, GateSpec]:
    specs: list[GateSpec] = [
        GateSpec("I", 1, builder=lambda: I2, self_inverse=True, diagonal=True,
                 display="I", description="Identity. Useful as a delay/marker."),
        GateSpec("X", 1, builder=lambda: X2, self_inverse=True, display="X",
                 description="Pauli-X, the quantum NOT. Rotates the Bloch vector by pi about x."),
        GateSpec("Y", 1, builder=lambda: Y2, self_inverse=True, display="Y",
                 description="Pauli-Y. Rotates the Bloch vector by pi about y."),
        GateSpec("Z", 1, builder=lambda: Z2, self_inverse=True, diagonal=True, display="Z",
                 description="Pauli-Z. Flips the sign of |1>; diagonal and self-inverse."),
        GateSpec("H", 1, builder=lambda: H2, self_inverse=True, display="H",
                 description="Hadamard. Creates an equal superposition from a basis state."),
        GateSpec("S", 1, builder=lambda: S2, diagonal=True, dagger="SDG", display="S",
                 description="Phase gate, pi/2 about z. S^2 = Z."),
        GateSpec("SDG", 1, builder=lambda: SDG2, diagonal=True, dagger="S", display="S†",
                 description="Adjoint of S."),
        GateSpec("T", 1, builder=lambda: T2, diagonal=True, dagger="TDG", display="T",
                 description="pi/8 gate, pi/4 about z. T^2 = S."),
        GateSpec("TDG", 1, builder=lambda: TDG2, diagonal=True, dagger="T", display="T†",
                 description="Adjoint of T."),
        GateSpec("SX", 1, builder=lambda: SX2, dagger="SXDG", display="√X",
                 description="Square root of X."),
        GateSpec("SXDG", 1, builder=lambda: SX2.conj().T.copy(), dagger="SX", display="√X†",
                 description="Adjoint of the square root of X."),
        GateSpec("RX", 1, params=("theta",), builder=_rx, display="Rx",
                 phase_dagger=_negate, description="Rotation about the x axis by theta."),
        GateSpec("RY", 1, params=("theta",), builder=_ry, display="Ry",
                 phase_dagger=_negate, description="Rotation about the y axis by theta."),
        GateSpec("RZ", 1, params=("theta",), builder=_rz, diagonal=True, display="Rz",
                 phase_dagger=_negate, description="Rotation about the z axis by theta."),
        GateSpec("P", 1, params=("phi",), builder=_p, diagonal=True, display="P",
                 phase_dagger=_negate, description="Phase gate diag(1, e^{i phi})."),
        GateSpec("U3", 1, params=("theta", "phi", "lambda"), builder=_u3, display="U3",
                 phase_dagger=_u3_dagger,
                 description="Most general single-qubit unitary (ZYZ Euler angles)."),
        GateSpec("U2", 1, params=("phi", "lambda"), builder=_u2, display="U2",
                 phase_dagger=_u2_dagger, description="U3 with theta = pi/2."),
        GateSpec("RXX", 2, params=("theta",), builder=_rxx, display="Rxx",
                 phase_dagger=_negate, category="two-qubit",
                 description="exp(-i theta/2 X⊗X) — native on many trapped-ion devices."),
        GateSpec("RYY", 2, params=("theta",), builder=_ryy, display="Ryy",
                 phase_dagger=_negate, category="two-qubit",
                 description="exp(-i theta/2 Y⊗Y)."),
        GateSpec("RZZ", 2, params=("theta",), builder=_rzz, diagonal=True, display="Rzz",
                 phase_dagger=_negate, category="two-qubit",
                 description="exp(-i theta/2 Z⊗Z) — the QAOA/ZNE workhorse interaction."),
        GateSpec("RZX", 2, params=("theta",), builder=_rzx, display="Rzx",
                 phase_dagger=_negate, category="two-qubit",
                 description="Cross-resonance interaction exp(-i theta/2 Z⊗X)."),
        GateSpec("CNOT", 2, builder=lambda: controlled(X2, 1), self_inverse=True,
                 display="●⊕", category="entangling",
                 description="Controlled-X. The canonical entangling gate."),
        GateSpec("CX", 2, builder=lambda: controlled(X2, 1), self_inverse=True,
                 display="●⊕", category="entangling",
                 description="Alias of CNOT."),
        GateSpec("CZ", 2, builder=lambda: controlled(Z2, 1), self_inverse=True, diagonal=True,
                 display="●Z", category="entangling",
                 description="Controlled-Z. Diagonal, so all CZ gates commute."),
        GateSpec("CY", 2, builder=lambda: controlled(Y2, 1), self_inverse=True,
                 display="●Y", category="entangling", description="Controlled-Y."),
        GateSpec("CH", 2, builder=lambda: controlled(H2, 1), self_inverse=True,
                 display="●H", category="entangling", description="Controlled-Hadamard."),
        GateSpec("SWAP", 2, builder=lambda: SWAP4, self_inverse=True,
                 display="⇄", category="two-qubit",
                 description="Exchanges two qubits."),
        GateSpec("ISWAP", 2, builder=lambda: ISWAP4, dagger="ISWAPDG", display="iSWAP",
                 category="two-qubit", description="Exchanges |01> and |10> with a phase i."),
        GateSpec("ISWAPDG", 2, builder=lambda: ISWAPDG4, dagger="ISWAP", display="iSWAP†",
                 category="two-qubit", description="Adjoint of iSWAP."),
        GateSpec("TOFFOLI", 3, builder=lambda: controlled(X2, 2), self_inverse=True,
                 display="Toffoli", category="three-qubit",
                 description="Doubly-controlled X (CCX)."),
        GateSpec("CCX", 3, builder=lambda: controlled(X2, 2), self_inverse=True,
                 display="Toffoli", category="three-qubit", description="Alias of TOFFOLI."),
        GateSpec("CCZ", 3, builder=lambda: controlled(Z2, 2), self_inverse=True, diagonal=True,
                 display="CCZ", category="three-qubit",
                 description="Doubly-controlled Z — all-to-all coupling for phase oracles."),
        GateSpec("CSWAP", 3, builder=lambda: controlled(SWAP4, 1), self_inverse=True,
                 display="Fredkin", category="three-qubit",
                 description="Controlled SWAP (Fredkin)."),
        GateSpec("MCX", -1, builder=_mcx_builder, self_inverse=True,
                 display="MCX", category="multi-qubit",
                 description="Multi-controlled X for any number of controls."),
    ]
    return {spec.name: spec for spec in specs}


REGISTRY: dict[str, GateSpec] = _build_registry()

ALIASES: dict[str, str] = {
    "CX": "CNOT",
    "CCX": "TOFFOLI",
    "U1": "P",
    "PHASE": "P",
    "SDG": "SDG",
    "S†": "SDG",
    "Sdg": "SDG",
    "T†": "TDG",
    "SXDG": "SXDG",
    "ID": "I",
}


def register_custom_gate(name: str, matrix: np.ndarray, num_qubits: int | None = None) -> GateSpec:
    """Register a user-supplied unitary so circuits can reference it by name.

    The matrix is validated for unitarity on registration — garbage in the gate
    library would silently break every downstream metric, so we refuse it here.
    """
    key = name.strip().upper()
    if not key or not key.replace("_", "").isalnum():
        raise ValueError(f"invalid gate name {name!r}")
    mat = np.asarray(matrix, dtype=COMPLEX)
    if mat.ndim != 2 or mat.shape[0] != mat.shape[1]:
        raise ValueError("custom gate matrix must be square")
    dim = mat.shape[0]
    k = int(round(np.log2(dim)))
    if 2**k != dim:
        raise ValueError("custom gate dimension must be a power of two")
    if num_qubits is not None and num_qubits != k:
        raise ValueError(f"num_qubits={num_qubits} contradicts a {dim}x{dim} matrix")
    if not is_close(mat.conj().T @ mat, np.eye(dim, dtype=COMPLEX)):
        raise ValueError(f"custom gate {key} is not unitary")
    spec = GateSpec(
        key,
        k,
        builder=lambda _m=mat: _m,
        custom=True,
        category="custom",
        display=key,
        description="User-defined unitary.",
        self_inverse=is_close(mat @ mat, np.eye(dim, dtype=COMPLEX)),
        diagonal=is_close(mat, np.diag(np.diag(mat))),
        dagger=f"{key}DG",
    )
    REGISTRY[key] = spec
    return spec


def resolve_name(name: str) -> str:
    """Canonicalise a user-supplied gate name."""
    key = name.strip().upper()
    key = ALIASES.get(key, key)
    if key not in REGISTRY:
        raise KeyError(f"unknown gate {name!r}")
    return key


def gate_spec(name: str) -> GateSpec:
    """Look up a :class:`GateSpec`, raising ``KeyError`` for unknown gates."""
    return REGISTRY[resolve_name(name)]


def gate_matrix(name: str, params: Sequence[float] = (), *, num_qubits: int | None = None) -> np.ndarray:
    """Dense matrix for the named gate."""
    return gate_spec(name).matrix(params, num_qubits=num_qubits)


def gate_arity(name: str, params: Sequence[float] = (), *, num_qubits: int | None = None) -> int:
    """Number of qubits the gate acts on (resolving variable-arity gates)."""
    spec = gate_spec(name)
    if spec.num_qubits != -1:
        return spec.num_qubits
    if num_qubits is None:
        raise ValueError(f"gate {name} has variable arity; pass num_qubits")
    return num_qubits


def inverse_gate(name: str, params: Sequence[float] = ()) -> tuple[str, tuple[float, ...]]:
    """Adjoint of a gate as ``(name, params)``.

    Used by algorithm builders (QPE, teleportation, state preparation) and by
    the optimizer when it wants to cancel a gate by inserting its inverse.
    """
    spec = gate_spec(name)
    if spec.custom:
        dag_name = spec.dagger or f"{spec.name}DG"
        if dag_name not in REGISTRY:
            mat = spec.matrix(params)
            register_custom_gate(dag_name, mat.conj().T)
        return dag_name, ()
    if spec.phase_dagger is not None:
        return spec.name, tuple(spec.phase_dagger(params))
    if spec.dagger is not None:
        return spec.dagger, ()
    if spec.self_inverse:
        return spec.name, tuple(params)
    raise ValueError(f"no adjoint defined for gate {name}")


def controlled_version(name: str, params: Sequence[float] = (), controls: int = 1) -> np.ndarray:
    """``controlled`` wrapper used for hardware/oracle construction."""
    inner = gate_matrix(name, params)
    return controlled(inner, controls)


def gate_catalog() -> list[dict[str, Any]]:
    """Serialisable gate palette for the frontend."""
    out: list[dict[str, Any]] = []
    for spec in sorted(REGISTRY.values(), key=lambda s: (s.category, s.name)):
        if spec.name in {"CX", "CCX"}:
            continue  # aliases, hidden from the palette
        out.append(
            {
                "name": spec.name,
                "display": spec.display or spec.name,
                "num_qubits": spec.num_qubits,
                "params": list(spec.params),
                "self_inverse": spec.self_inverse,
                "diagonal": spec.diagonal,
                "category": spec.category,
                "custom": spec.custom,
                "description": spec.description,
                "matrix": np.round(np.asarray(spec.matrix((0.0,) * len(spec.params) if spec.params else (), num_qubits=max(spec.num_qubits, 1) if spec.num_qubits != -1 else 2), dtype=COMPLEX), 6).tolist()
                if spec.num_qubits != -1
                else None,
            }
        )
    return out


GATE_CATALOG: list[str] = sorted(REGISTRY)

__all__ = [
    "ALIASES",
    "GATE_CATALOG",
    "I2",
    "REGISTRY",
    "GateSpec",
    "X2",
    "Y2",
    "Z2",
    "controlled_version",
    "gate_arity",
    "gate_catalog",
    "gate_matrix",
    "gate_spec",
    "inverse_gate",
    "kron_list",
    "register_custom_gate",
    "resolve_name",
]
