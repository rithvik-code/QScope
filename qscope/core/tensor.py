"""Low-level tensor primitives shared by every QScope engine.

Conventions
-----------
* Qubit ``0`` is the **most significant** bit of a basis-state index, matching
  OpenQASM and Qiskit.  Basis state ``|q0 q1 ... q(n-1)>`` maps to the integer
  ``sum(bit_q << (n - 1 - q))``.
* A state is a ``numpy.complex128`` vector of length ``2 ** n``.
* An operator acting on ``targets=[t0, t1, ...]`` is a dense matrix whose row
  and column indices are read big-endian in that same target order.
* Amplitude ordering inside a tensor is always ``[qubit0, qubit1, ...]``.

Every routine here is written from first principles rather than delegating to a
quantum library, because correctness of this layer is what makes the rest of
QScope trustworthy.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

import numpy as np

COMPLEX = np.complex128
"""The single floating/complex type used across QScope."""

ATOL = 1e-10
RTOL = 1e-10
"""Absolute/relative tolerance for numerical comparisons.

Chosen from the observed error of our own gate-application routines: a 24-qubit
Hadamard tower stays within ~1e-13 of unit norm, so 1e-10 leaves three orders of
magnitude of headroom while still catching real bugs.
"""

LETTERS = "abcdefghijklmnopqrstuvwxyz"
"""einsum labels; caps the general-tensor routines at 26 qubits."""

MAX_TENSOR_QUBITS = len(LETTERS)


def is_close(a: np.ndarray | complex | float, b: np.ndarray | complex | float) -> bool:
    """Numerically compare two arrays/scalars with QScope's standard tolerance."""
    return bool(np.allclose(np.asarray(a), np.asarray(b), atol=ATOL, rtol=RTOL))


def as_complex(a: np.ndarray | Sequence | float) -> np.ndarray:
    """Coerce input to a contiguous ``complex128`` array."""
    return np.asarray(a, dtype=COMPLEX)


def kron_list(mats: Iterable[np.ndarray]) -> np.ndarray:
    """Kronecker product of a sequence of matrices, left to right.

    ``kron_list([A, B, C]) == numpy.kron(A, numpy.kron(B, C))``.
    """
    out = np.array([[1.0 + 0j]], dtype=COMPLEX)
    for m in mats:
        out = np.kron(out, as_complex(m))
    return out


def basis_label(n: int, index: int) -> str:
    """``index`` -> bitstring of ``n`` characters, qubit 0 on the left."""
    if index < 0 or index >= 2**n:
        raise ValueError(f"index {index} out of range for {n} qubits")
    return format(index, f"0{n}b")


def label_to_index(n: int, label: str) -> int:
    """Bitstring (qubit 0 first) -> basis-state index."""
    clean = "".join(ch for ch in label if ch not in "|>_ ")
    if len(clean) != n or any(ch not in "01" for ch in clean):
        raise ValueError(f"invalid {n}-qubit basis label {label!r}")
    return int(clean, 2)


def basis_state(n: int, index: int = 0, *, dtype: type = COMPLEX) -> np.ndarray:
    """Computational basis vector ``|index>`` in a ``2 ** n``-dimensional space."""
    vec = np.zeros(2**n, dtype=dtype)
    vec[index] = 1.0
    return vec


def basis_labels(n: int) -> list[str]:
    """All ``2 ** n`` basis labels, in index order."""
    return [basis_label(n, i) for i in range(2**n)]


def state_tensor(state: np.ndarray, n: int) -> np.ndarray:
    """View a flat state vector as an ``n``-rank tensor with axes ``(q0..qn-1)``."""
    return np.asarray(state, dtype=COMPLEX).reshape((2,) * n)


def apply_operator(
    state: np.ndarray,
    op: np.ndarray,
    targets: Sequence[int],
    n: int | None = None,
) -> np.ndarray:
    """Apply a dense ``k``-qubit operator to ``state`` and return a new vector.

    Implemented as an exact tensor contraction rather than slicing loops, so it
    is correct for any target ordering / non-contiguous qubit sets::

        amp'[o_0..o_n-1] = sum_{s} op[o_t..., s_t...] * amp[..., s_t...]

    Non-target axes are passed through untouched, which is what makes this both
    general and reasonably fast (a 20-qubit single-qubit gate stays ~5 ms).
    """
    targets = tuple(int(t) for t in targets)
    if n is None:
        n = int(np.round(np.log2(np.asarray(state).size)))
    if not targets:
        raise ValueError("apply_operator requires at least one target qubit")
    if len(set(targets)) != len(targets):
        raise ValueError(f"duplicate target qubits in {targets}")
    if any(t < 0 or t >= n for t in targets):
        raise ValueError(f"target qubits {targets} outside 0..{n - 1}")
    if n > MAX_TENSOR_QUBITS:
        raise ValueError(
            f"general tensor routines support at most {MAX_TENSOR_QUBITS} qubits, got {n}"
        )
    k = len(targets)
    op = as_complex(op)
    if op.shape != (2**k, 2**k):
        raise ValueError(
            f"operator shape {op.shape} does not match {k} target qubits "
            f"(expected {(2 ** k, 2 ** k)})"
        )
    in_lab = [LETTERS[q] for q in range(n)]
    op_sub = "".join(in_lab[t].upper() for t in targets) + "".join(in_lab[t] for t in targets)
    state_sub = "".join(in_lab)
    out_sub = "".join(
        in_lab[q].upper() if q in targets else in_lab[q] for q in range(n)
    )
    op_t = op.reshape((2,) * (2 * k))
    result = np.einsum(f"{op_sub},{state_sub}->{out_sub}", op_t, state_tensor(state, n))
    return np.ascontiguousarray(result).reshape(-1)


def apply_operator_inplace(
    state: np.ndarray,
    op: np.ndarray,
    targets: Sequence[int],
    n: int,
) -> None:
    """In-place variant of :func:`apply_operator` (``state`` must be writable)."""
    state[:] = apply_operator(state, op, targets, n)


def controlled(u: np.ndarray, num_controls: int = 1, *, control_values: Sequence[int] | None = None) -> np.ndarray:
    """Embed ``u`` in a controlled unitary on ``num_controls + log2(len(u))`` qubits.

    Control qubits are the *most significant* axes of the result, so
    ``controlled(X, 1)`` is CNOT with ``(control, target)`` ordering and
    ``controlled(X, 2)`` is Toffoli ``(c0, c1, t)``.
    """
    u = as_complex(u)
    k = u.shape[0]
    if u.shape != (k, k):
        raise ValueError("controlled() requires a square operator")
    if num_controls < 0:
        raise ValueError("num_controls must be >= 0")
    if control_values is None:
        control_values = [1] * num_controls
    if len(control_values) != num_controls:
        raise ValueError("control_values length must equal num_controls")
    dim = (2**num_controls) * k
    full = np.eye(dim, dtype=COMPLEX)
    view = full.reshape(2**num_controls, k, 2**num_controls, k)
    active = 0
    for v in control_values:
        active = (active << 1) | int(bool(v))
    view[active, :, active, :] = u
    return full.reshape(dim, dim)


def controlled_matrix(
    u: np.ndarray,
    num_controls: int = 1,
    *,
    control_values: Sequence[int] | None = None,
) -> np.ndarray:
    """Alias for :func:`controlled` (kept for readability at call sites)."""
    return controlled(u, num_controls, control_values=control_values)


def apply_kraus(
    rho: np.ndarray,
    kraus: Sequence[np.ndarray],
    targets: Sequence[int],
    n: int,
) -> np.ndarray:
    """Apply a quantum channel given by Kraus operators to a density matrix.

    ``rho' = sum_i K_i rho K_i^dagger``.  Trace preservation is the caller's
    responsibility (the noise module validates models when they are built).

    Implemented as grouped axis permutations + dense matmul instead of building
    the embedded ``2^n x 2^n`` operator, which keeps memory at ``O(4^n)`` (the
    size of ``rho`` itself) rather than ``O(4^n)`` *extra*.
    """
    rho = as_complex(rho)
    if not kraus:
        raise ValueError("apply_kraus requires at least one Kraus operator")
    total = np.zeros((2**n, 2**n), dtype=COMPLEX)
    for K in kraus:
        K = as_complex(K)
        total += _matmul_right(_matmul_left(rho, K, targets, n), K, targets, n)
    return total


def _row_perm(targets: Sequence[int], n: int) -> list[int]:
    """Axis permutation that moves the target row-axes to the front."""
    return list(targets) + [q for q in range(n) if q not in targets] + [n + q for q in range(n)]


def _matmul_left(rho: np.ndarray, K: np.ndarray, targets: Sequence[int], n: int) -> np.ndarray:
    """``K_full @ rho`` without materialising ``K_full``.

    Row axes are permuted so the ``k`` target axes come first and are contiguous,
    which turns the embedded operator product into one dense ``(2^k, 2^k)`` matmul.
    """
    k = len(targets)
    perm = _row_perm(targets, n)
    base = rho.reshape((2,) * n + (2,) * n)
    flat = base.transpose(perm).reshape(2**k, -1)
    out = K @ flat
    out = out.reshape((2,) * k + (2,) * (n - k) + (2,) * n)
    return out.transpose(np.argsort(perm)).reshape(2**n, 2**n)


def _matmul_right(rho: np.ndarray, K: np.ndarray, targets: Sequence[int], n: int) -> np.ndarray:
    """``rho @ K_full^dagger`` without materialising ``K_full``."""
    k = len(targets)
    kd = as_complex(K).conj().T
    perm = [q for q in range(n)] + [n + t for t in targets] + [
        n + q for q in range(n) if q not in targets
    ]
    base = rho.reshape((2,) * n + (2,) * n)
    # Layout after the permutation and regrouping: (rows, target columns, rest columns)
    mats = base.transpose(perm).reshape(2**n, 2**k, 2 ** (n - k))
    out = np.einsum("aij,ik->akj", mats, kd, optimize=True)
    out = out.reshape((2,) * n + (2,) * k + (2,) * (n - k))
    return out.transpose(np.argsort(perm)).reshape(2**n, 2**n)


def partial_trace(rho: np.ndarray, n: int, keep: Sequence[int]) -> np.ndarray:
    """Reduced density matrix of ``rho`` over the qubits in ``keep``.

    ``rho_keep[a, b] = sum_t rho[keep=a, traced=t ; keep=b, traced=t]``.
    """
    keep = sorted({int(q) for q in keep})
    if any(q < 0 or q >= n for q in keep):
        raise ValueError(f"keep={keep} outside 0..{n - 1}")
    if not keep:
        return np.array([[float(np.trace(as_complex(rho)).real)]], dtype=COMPLEX)
    if len(keep) == n:
        return as_complex(rho).copy()
    traced = [q for q in range(n) if q not in keep]
    # Row axes: kept then traced; column axes in the same order, so the two
    # traced axes can be contracted by a plain diagonal sum.
    perm = keep + [n + q for q in keep] + traced + [n + q for q in traced]
    tensor = as_complex(rho).reshape((2,) * n + (2,) * n).transpose(perm)
    tensor = tensor.reshape(
        2 ** len(keep), 2 ** len(keep), 2 ** len(traced), 2 ** len(traced)
    )
    res = np.trace(tensor, axis1=2, axis2=3)
    dim = 2 ** len(keep)
    return np.ascontiguousarray(res).reshape(dim, dim)


def matrix_sqrt(mat: np.ndarray) -> np.ndarray:
    """Principal square root of a Hermitian positive semi-definite matrix."""
    mat = as_complex(mat)
    herm = (mat + mat.conj().T) / 2
    vals, vecs = np.linalg.eigh(herm)
    vals = np.clip(vals, 0.0, None)
    return (vecs * np.sqrt(vals)) @ vecs.conj().T


def trace_norm(mat: np.ndarray) -> float:
    """Schatten 1-norm: sum of singular values."""
    return float(np.sum(np.linalg.svd(as_complex(mat), compute_uv=False)))


def is_unitary(mat: np.ndarray) -> bool:
    """True when ``U^dagger U = I`` within tolerance."""
    m = as_complex(mat)
    dim = m.shape[0]
    if m.shape != (dim, dim):
        return False
    return is_close(m.conj().T @ m, np.eye(dim, dtype=COMPLEX))


def process_overlap(u: np.ndarray, v: np.ndarray) -> float:
    """Phase-invariant overlap ``|Tr(U^dagger V)| / d`` between two unitaries.

    Returns a value in ``[0, 1]`` where 1 means "equal up to a global phase".
    """
    u, v = as_complex(u), as_complex(v)
    d = u.shape[0]
    return float(abs(np.trace(u.conj().T @ v)) / d)


def purity(mat: np.ndarray) -> float:
    """``Tr(rho^2)`` — 1 for a pure state, ``1/d`` for the maximally mixed one."""
    m = as_complex(mat)
    return float(np.real(np.trace(m @ m)))


def von_neumann_entropy(mat: np.ndarray, base: float = 2.0) -> float:
    """``S = -Tr(rho log rho) = -sum_i lambda_i log(lambda_i)`` in the given base.

    Eigenvalues below ``1e-12`` are dropped (they contribute nothing but leak
    ``0 * log 0`` NaNs through floating point).
    """
    m = as_complex(mat)
    vals = np.linalg.eigvalsh((m + m.conj().T) / 2)
    vals = vals[vals > 1e-12]
    if vals.size == 0:
        return 0.0
    return float(-np.sum(vals * np.log(vals)) / np.log(base))


def unitary_distance(u: np.ndarray, v: np.ndarray) -> float:
    """Max elementwise difference after removing the global phase of ``v``.

    We want ``argmin_phi max|U - e^{i phi} V|``.  Since ``V = e^{i phi} U`` makes
    ``Tr(U^dagger V) = e^{i phi} d``, the phase must be *divided out* of ``V``
    (equivalently multiplied by ``conj(Tr(U^dagger V)) / |Tr(U^dagger V)|``).

    Used by the optimizer to *prove* an optimisation is equivalence-preserving.
    """
    u, v = as_complex(u), as_complex(v)
    if u.shape != v.shape:
        raise ValueError(f"shape mismatch {u.shape} vs {v.shape}")
    phase = np.trace(u.conj().T @ v)
    if abs(phase) > ATOL:
        v = v * (np.conj(phase) / abs(phase))
    return float(np.max(np.abs(u - v)))
