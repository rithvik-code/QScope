"""Rewriting rules for the optimiser.

Every rule here is an *exact* identity, verified numerically by the optimiser
before the rewritten circuit is accepted.  The rules never cross a measurement,
reset or barrier boundary, because those break the unitary history: cancelling a
gate across a measurement would change what a later conditional gate reads.

The rewriting engine allows a gate to move past neighbours it commutes with, so
``H · X · X · H`` cancels even though the two X gates are not adjacent in the raw
list.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np

from qscope.circuit.circuit import BARRIER, GATE, MEASURE, RESET, Circuit, Operation
from qscope.core.gates import gate_spec, resolve_name
from qscope.core.tensor import ATOL, is_close

ROTATION_GATES = {"RX", "RY", "RZ", "P", "RXX", "RYY", "RZZ", "RZX", "U3", "U2"}
"""Gates whose parameters can be summed when applied back to back."""

FULL_TURN = {
    "P": 2 * np.pi,
    "RZ": 4 * np.pi,
    "RX": 4 * np.pi,
    "RY": 4 * np.pi,
    "RXX": 4 * np.pi,
    "RYY": 4 * np.pi,
    "RZZ": 4 * np.pi,
    "RZX": 4 * np.pi,
}
"""Parameter period after which the gate is the identity.

``P(phi) = diag(1, e^{i phi})`` is exactly periodic in ``2*pi``.  The
``exp(-i theta/2 * H)`` family (``Rx``, ``Ry``, ``Rz``, ``Rxx`` ...) needs
``4*pi``: at ``2*pi`` those gates equal **minus the identity**, so treating them as
the identity would flip the sign of the state vector.  QScope only removes a gate
when the operator is *exactly* the identity — global phase is never exploited, and
neither is entanglement.  Getting this wrong would silently change a circuit, so
each entry is justified per gate rather than assumed.
"""

CLIFFORD_PAIRS: dict[tuple[str, str], str] = {
    # S is diag(1, i), T is diag(1, e^{i pi/4}); both are diagonal so the products
    # below are order independent (keys are sorted pairs).  Only *exact* products
    # are listed: T·Z = -T† differs from T† by a relative phase, so it is
    # deliberately absent.  The test suite re-derives every entry from the gate
    # matrices, so a wrong row cannot survive as silent circuit corruption.
    ("S", "S"): "Z",
    ("SDG", "SDG"): "Z",
    ("S", "SDG"): "I",
    ("T", "T"): "S",
    ("TDG", "TDG"): "SDG",
    ("T", "TDG"): "I",
    ("S", "Z"): "SDG",
    ("SDG", "Z"): "S",
    ("T", "SDG"): "TDG",
    ("S", "TDG"): "T",
    ("Z", "Z"): "I",
    ("H", "H"): "I",
    ("X", "X"): "I",
    ("Y", "Y"): "I",
}
"""Two-gate products that are exactly one named gate (Clifford relations).

``S·S = Z``, ``T·T = S``, ``S·Z = S†``, ``T·S† = T†``, ``T·T† = I``, ...  Every
entry is verified against the gate matrices in the test suite, so a wrong entry
cannot survive as a silent circuit corruption.
"""


@dataclass
class RuleMatch:
    """A single applicable rewrite."""

    rule: str
    indices: list[int]
    replacement: list[Operation]
    description: str
    reasoning: str


# ---------------------------------------------------------------------------
# predicates
# ---------------------------------------------------------------------------


def is_diagonal(op: Operation) -> bool:
    """True when the operation is diagonal in the computational basis."""
    if op.kind != GATE:
        return False
    try:
        spec = gate_spec(op.name)
    except KeyError:
        return False
    if op.controls:
        # Controlled-diagonal is diagonal only if the inner gate is diagonal too.
        return spec.diagonal
    return spec.diagonal


def commutes(a: Operation, b: Operation) -> bool:
    """Whether ``a`` may be swapped with ``b`` without changing the circuit.

    Three sound cases: disjoint qubits; two diagonal gates (they always commute);
    and a control/target pair with no overlap where one is diagonal *and* the
    other's operator is diagonal on the shared wire — which we conservatively
    approximate by requiring both to be diagonal.  Anything else returns False:
    refusing to reorder is always safe, reordering wrongly is not.
    """
    if not set(a.qubits) & set(b.qubits):
        return True
    if is_diagonal(a) and is_diagonal(b):
        return True
    return False


def same_wires(a: Operation, b: Operation) -> bool:
    return list(a.controls) == list(b.controls) and list(a.targets) == list(b.targets)


def can_shift_past(ops: Sequence[Operation], start: int, end: int) -> bool:
    """True when ``ops[start]`` commutes with every operation strictly before ``end``."""
    gate = ops[start]
    return all(commutes(gate, ops[k]) for k in range(start + 1, end))


# ---------------------------------------------------------------------------
# segments
# ---------------------------------------------------------------------------


def aligned_segments(circuit: Circuit) -> list[list[Operation]]:
    """Split a circuit into segments whose *ordinals always align*.

    ``segment_bounds`` drops empty segments, which makes segment ``k`` of a
    rewritten circuit correspond to a different segment ``k`` of the original as
    soon as a whole segment is simplified away — fatal for per-rewrite
    verification.  This variant keeps an entry for every gap between dividers, so
    ``segments(original)[k]`` and ``segments(working)[k]`` always describe the same
    slice of the circuit.
    """
    segments: list[list[Operation]] = [[]]
    for op in circuit.operations:
        if op.kind in (MEASURE, RESET, BARRIER):
            segments.append([])
        elif op.kind == GATE:
            segments[-1].append(op)
    return segments


def segment_bounds(ops: Sequence[Operation]) -> list[tuple[int, int]]:
    """Split the operation list into unitary segments.

    A measurement, reset or barrier ends the current segment: the optimiser is
    only allowed to rewrite *inside* one segment, which is what keeps
    measurement-dependent behaviour identical.
    """
    bounds: list[tuple[int, int]] = []
    start = 0
    for i, op in enumerate(ops):
        if op.kind in (MEASURE, RESET, BARRIER):
            if i > start:
                bounds.append((start, i))
            start = i + 1
    if len(ops) > start:
        bounds.append((start, len(ops)))
    return bounds


# ---------------------------------------------------------------------------
# rules
# ---------------------------------------------------------------------------


def find_cancellation(ops: Sequence[Operation]) -> RuleMatch | None:
    """Find ``G`` followed by ``G^-1`` (or an involutive ``G`` twice)."""
    n = len(ops)
    for i in range(n):
        a = ops[i]
        if a.kind != GATE or a.condition is not None:
            continue
        for j in range(i + 1, n):
            b = ops[j]
            if b.kind != GATE:
                break
            if b.condition is not None:
                break
            if same_wires(a, b) and _is_inverse(a, b):
                if can_shift_past(ops, i, j):
                    return RuleMatch(
                        rule="cancel_inverse_pair",
                        indices=[i, j],
                        replacement=[],
                        description=f"{a.display} · {b.display} = I",
                        reasoning=(
                            f"{a.display} and {b.display} are mutual inverses on the same wires and "
                            f"{'the gates between them commute with ' + a.display if j > i + 1 else 'they are adjacent'}, "
                            "so both can be removed."
                        ),
                    )
    return None


def find_clifford_pair(ops: Sequence[Operation]) -> RuleMatch | None:
    """Find two adjacent (modulo commuting gates) gates with a known product."""
    for i in range(len(ops)):
        a = ops[i]
        if a.kind != GATE or a.condition is not None or a.params:
            continue
        for j in range(i + 1, len(ops)):
            b = ops[j]
            if b.kind != GATE or b.condition is not None:
                break
            if not same_wires(a, b):
                continue
            key = tuple(sorted((resolve_name(a.name), resolve_name(b.name))))
            if key not in CLIFFORD_PAIRS:
                continue
            if not can_shift_past(ops, i, j):
                continue
            result = CLIFFORD_PAIRS[key]
            if result == "I":
                replacement: list[Operation] = []
                text = f"{a.display} · {b.display} = I"
            else:
                replacement = [
                    Operation(name=result, targets=list(a.targets), controls=list(a.controls), kind=GATE)
                ]
                text = f"{a.display} · {b.display} = {result}"
            return RuleMatch(
                rule="clifford_product",
                indices=[i, j],
                replacement=replacement,
                description=text,
                reasoning=(
                    f"The product of {a.display} and {b.display} on the same wires is exactly "
                    f"{result if result != 'I' else 'the identity'}."
                ),
            )
    return None


def find_rotation_merge(ops: Sequence[Operation]) -> RuleMatch | None:
    """Merge two rotations of the same family and target into one."""
    for i in range(len(ops)):
        a = ops[i]
        if a.kind != GATE or a.condition is not None:
            continue
        family = resolve_name(a.name)
        if family not in {"RX", "RY", "RZ", "P", "RXX", "RYY", "RZZ", "RZX"} or len(a.params) != 1:
            continue
        for j in range(i + 1, len(ops)):
            b = ops[j]
            if b.kind != GATE or b.condition is not None:
                break
            if resolve_name(b.name) != family or not same_wires(a, b) or len(b.params) != 1:
                continue
            if not can_shift_past(ops, i, j):
                continue
            total = float(a.params[0] + b.params[0])
            period = FULL_TURN[family]
            wrapped = total % period
            if abs(wrapped) < ATOL or abs(wrapped - period) < ATOL:
                replacement: list[Operation] = []
                text = f"{family}({a.params[0]:.4g}) · {family}({b.params[0]:.4g}) = I"
                reasoning = (
                    f"The two rotations add to {total:.6g}, which is a full period "
                    f"({period:.6g}) of {family}, so the pair is the identity."
                )
            else:
                merged = a.copy()
                merged.params = [wrapped]
                replacement = [merged]
                text = (
                    f"{family}({a.params[0]:.4g}) · {family}({b.params[0]:.4g}) = "
                    f"{family}({wrapped:.4g})"
                )
                reasoning = (
                    f"Rotations about the same axis on the same qubits compose additively: "
                    f"{a.params[0]:.6g} + {b.params[0]:.6g} = {total:.6g}, kept modulo {period:.6g}."
                )
            return RuleMatch(
                rule="merge_rotations",
                indices=[i, j],
                replacement=replacement,
                description=text,
                reasoning=reasoning,
            )
    return None


def find_identity_rotation(ops: Sequence[Operation]) -> RuleMatch | None:
    """Remove a rotation whose angle is zero (or a full period)."""
    for i, op in enumerate(ops):
        if op.kind != GATE or op.condition is not None:
            continue
        family = resolve_name(op.name)
        if family not in ROTATION_GATES or len(op.params) != 1:
            continue
        period = FULL_TURN.get(family)
        value = float(op.params[0])
        if period is not None and (abs(value % period) < ATOL or abs(value % period - period) < ATOL):
            return RuleMatch(
                rule="drop_identity_rotation",
                indices=[i],
                replacement=[],
                description=f"{op.display} = I",
                reasoning=f"A {family} rotation of {value:.6g} is a full period ({period:.6g}).",
            )
        if abs(value) < ATOL:
            return RuleMatch(
                rule="drop_identity_rotation",
                indices=[i],
                replacement=[],
                description=f"{op.display} = I",
                reasoning="A rotation by zero is the identity.",
            )
    return None


def find_unitary_identity(ops: Sequence[Operation]) -> RuleMatch | None:
    """Remove a gate whose matrix is numerically the identity.

    Catches things the symbolic rules miss (``U3(0, phi, -phi)``, a cancelled
    ``H·Z·H`` written by hand, and anything else that is the identity up to a
    global phase).
    """
    for i, op in enumerate(ops):
        if op.kind != GATE or op.condition is not None:
            continue
        arity = op.arity + len(op.controls)
        if arity > 3:
            continue
        try:
            spec = gate_spec(op.name)
            inner = (
                spec.matrix(op.params, num_qubits=op.arity)
                if spec.num_qubits == -1
                else spec.matrix(op.params)
            )
        except Exception:
            continue
        if op.controls:
            from qscope.core.tensor import controlled

            inner = controlled(inner, len(op.controls), control_values=op.control_values)
        dim = inner.shape[0]
        if is_close(inner, np.eye(dim, dtype=complex)):
            return RuleMatch(
                rule="drop_unitary_identity",
                indices=[i],
                replacement=[],
                description=f"{op.display} = I",
                reasoning="The gate's matrix equals the identity within numerical tolerance.",
            )
    return None


def _is_inverse(a: Operation, b: Operation) -> bool:
    """Whether ``b`` is the adjoint of ``a`` on the same wires."""
    from qscope.core.gates import inverse_gate

    try:
        name, params = inverse_gate(resolve_name(a.name), a.params)
    except ValueError:
        return False
    if resolve_name(b.name) != name:
        return False
    if len(params) != len(b.params):
        return False
    return all(abs(float(p) - float(q)) < 1e-9 for p, q in zip(params, b.params))


def find_redundant_qubits(circuit: Circuit) -> list[int]:
    """Qubits that no operation touches (candidates for compaction)."""
    return circuit.unused_qubits()


def compact_qubits(circuit: Circuit) -> tuple[Circuit, dict[int, int]]:
    """Remove unused wires, returning the new circuit and the qubit mapping.

    The mapping is returned so that trace/metric output from before and after can
    still be compared wire by wire — relabelling without reporting the mapping
    would make the two results silently incomparable.
    """
    used = circuit.used_qubits()
    if len(used) == circuit.num_qubits:
        return circuit, {q: q for q in used}
    mapping = {old: new for new, old in enumerate(used)}
    new_circuit = Circuit(
        len(used),
        circuit.num_clbits,
        name=circuit.name,
        description=circuit.description,
        qubit_labels=[circuit.qubits.label(q) for q in used],
        clbit_labels=circuit.clbits.labels,
        metadata={**circuit.metadata, "compacted_from": circuit.num_qubits, "qubit_map": mapping},
    )
    for op in circuit.operations:
        clone = op.copy()
        clone.targets = [mapping[q] for q in clone.targets]
        clone.controls = [mapping[c] for c in clone.controls]
        new_circuit.operations.append(clone)
    return new_circuit, mapping


def find_opportunities(circuit: Circuit) -> list[dict[str, object]]:
    """Read-only audit of what *could* be improved, without changing anything."""
    findings: list[dict[str, object]] = []
    ops = circuit.operations
    for start, end in segment_bounds(ops):
        segment = ops[start:end]
        match = find_cancellation(segment)
        if match:
            findings.append(
                {
                    "kind": "cancelling_gates",
                    "severity": "high",
                    "indices": [start + i for i in match.indices],
                    "description": f"{match.description} — two gates annihilate each other",
                    "reasoning": match.reasoning,
                }
            )
        match = find_clifford_pair(segment)
        if match:
            findings.append(
                {
                    "kind": "redundant_gates",
                    "severity": "medium",
                    "indices": [start + i for i in match.indices],
                    "description": f"{match.description} — replaceable by one gate",
                    "reasoning": match.reasoning,
                }
            )
        match = find_rotation_merge(segment)
        if match:
            findings.append(
                {
                    "kind": "unnecessary_rotations",
                    "severity": "medium",
                    "indices": [start + i for i in match.indices],
                    "description": f"{match.description} — rotations can be composed",
                    "reasoning": match.reasoning,
                }
            )
        match = find_identity_rotation(segment)
        if match:
            findings.append(
                {
                    "kind": "unnecessary_rotations",
                    "severity": "low",
                    "indices": [start + i for i in match.indices],
                    "description": f"{match.description} — no effect on the state",
                    "reasoning": match.reasoning,
                }
            )
        match = find_unitary_identity(segment)
        if match:
            findings.append(
                {
                    "kind": "redundant_gates",
                    "severity": "low",
                    "indices": [start + i for i in match.indices],
                    "description": f"{match.description}",
                    "reasoning": match.reasoning,
                }
            )

    unused = find_redundant_qubits(circuit)
    if unused:
        findings.append(
            {
                "kind": "unused_qubits",
                "severity": "low",
                "indices": [],
                "description": f"{len(unused)} qubit(s) are never used: {unused}",
                "reasoning": "Compacting removes the idle wires entirely (simulation cost is 2^n).",
            }
        )

    depth = circuit.depth()
    gates = circuit.gate_count()
    if gates and depth > 0 and gates / depth > 3:
        findings.append(
            {
                "kind": "excessive_depth",
                "severity": "info",
                "indices": [],
                "description": f"{gates} gates over {depth} layers ({gates / depth:.1f} gates per layer)",
                "reasoning": (
                    "High serial gate density means little parallelism is available; "
                    "check whether the algorithm can expose more concurrency."
                ),
            }
        )
    repeated = {k: v for k, v in circuit.gate_histogram().items() if v > 2}
    if repeated:
        findings.append(
            {
                "kind": "repeated_operations",
                "severity": "info",
                "indices": [],
                "description": "; ".join(f"{k}×{v}" for k, v in list(repeated.items())[:5]),
                "reasoning": "Frequently repeated gates are the best candidates for a custom unitary or native-gate rewrite.",
            }
        )
    return findings


__all__ = [
    "CLIFFORD_PAIRS",
    "FULL_TURN",
    "ROTATION_GATES",
    "RuleMatch",
    "aligned_segments",
    "can_shift_past",
    "commutes",
    "compact_qubits",
    "find_cancellation",
    "find_clifford_pair",
    "find_identity_rotation",
    "find_opportunities",
    "find_redundant_qubits",
    "find_rotation_merge",
    "find_unitary_identity",
    "is_diagonal",
    "same_wires",
    "segment_bounds",
]
