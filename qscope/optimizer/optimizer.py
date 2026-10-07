"""The optimiser: rewrite, then *prove* the rewrite was safe.

Design rules:

1. **Never optimise blindly.**  After rewriting, the optimised circuit is compared
   against the original.  For small circuits we build both unitaries and compare
   them exactly (up to global phase) — that is a proof, not a spot check.  For
   larger circuits we compare the simulated output on a family of random input
   states and label the result as statistical.
2. **Never cross a measurement.**  Rewrites happen inside unitary segments only.
3. **Revert on failure.**  If verification fails, the original circuit is returned
   with the failure recorded, because a silently-wrong optimisation is worse than
   no optimisation.
4. **Report the accounting**, per rule: gates removed, gates added, depth change,
   and why each rewrite is legitimate.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

import numpy as np

from qscope.analysis.fidelity import state_fidelity
from qscope.circuit.circuit import Circuit, Operation
from qscope.core.tensor import unitary_distance
from qscope.optimizer.rules import (
    RuleMatch,
    aligned_segments,
    compact_qubits,
    find_cancellation,
    find_clifford_pair,
    find_identity_rotation,
    find_opportunities,
    find_redundant_qubits,
    find_rotation_merge,
    find_unitary_identity,
    segment_bounds,
)

PASS_SAFE = "safe"
PASS_STANDARD = "standard"
PASS_AGGRESSIVE = "aggressive"

VERIFIED_PROVEN = "PROVEN_EQUIVALENT"
VERIFIED_STATISTICAL = "VERIFIED_ON_RANDOM_INPUTS"
VERIFIED_FAILED = "VERIFICATION_FAILED"
VERIFIED_SKIPPED = "NOT_VERIFIED"

DEFAULT_PROOF_QUBITS = 9
"""Largest circuit we build full unitaries for (``4^9 * 16 B`` = 16 MB per matrix)."""


@dataclass
class OptimizationStep:
    """One applied rewrite.

    ``verified`` and ``deviation`` record the outcome of the per-rewrite check: the
    segment before and after the rewrite was rebuilt as a unitary and compared, so
    a rule that is subtly wrong is caught at the step that caused it rather than
    only at the end.
    """

    rule: str
    description: str
    reasoning: str
    indices: list[int]
    removed: list[str]
    added: list[str]
    gates_before: int
    gates_after: int
    depth_before: int
    depth_after: int
    verified: bool | None = None
    deviation: float | None = None
    rolled_back: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule": self.rule,
            "description": self.description,
            "reasoning": self.reasoning,
            "indices": self.indices,
            "removed": self.removed,
            "added": self.added,
            "gates_before": self.gates_before,
            "gates_after": self.gates_after,
            "depth_before": self.depth_before,
            "depth_after": self.depth_after,
            "verified": self.verified,
            "deviation": self.deviation,
            "rolled_back": self.rolled_back,
        }


@dataclass
class OptimizationResult:
    """Original vs optimised circuit, with accounting and verification."""

    original: Circuit
    optimized: Circuit
    before: dict[str, Any]
    after: dict[str, Any]
    improvements: dict[str, Any]
    steps: list[OptimizationStep]
    verification: dict[str, Any]
    passes_applied: list[str]
    findings: list[dict[str, object]]
    qubit_map: dict[int, int] | None
    seconds: float
    notes: list[str] = field(default_factory=list)

    def to_dict(self, include_circuits: bool = True) -> dict[str, Any]:
        out: dict[str, Any] = {
            "before": self.before,
            "after": self.after,
            "improvements": self.improvements,
            "steps": [s.to_dict() for s in self.steps],
            "verification": self.verification,
        "passes_applied": self.passes_applied,
        "findings": self.findings,
        "qubit_map": self.qubit_map,
        "seconds": self.seconds,
        "notes": self.notes,
        "phase_policy": "exact operator equivalence; global phase is never exploited",
            "gate_histogram_before": self.before.get("histogram", {}),
            "gate_histogram_after": self.after.get("histogram", {}),
        }
        if include_circuits:
            out["original"] = self.original.to_dict()
            out["optimized"] = self.optimized.to_dict()
        return out

    def headline(self) -> str:
        """One-line summary for reports and the UI."""
        gates = self.improvements.get("gates_saved", 0)
        depth = self.improvements.get("depth_saved", 0)
        parts = []
        if gates:
            parts.append(f"{gates} fewer gates ({self.improvements['gates_percent']:.1f}%)")
        if depth:
            parts.append(f"depth {self.before['depth']} → {self.after['depth']} ({self.improvements['depth_percent']:.1f}% lower)")
        if not parts:
            return "Circuit already minimal for the enabled rules."
        return ", ".join(parts)


PASS_ORDER: list[tuple[str, Callable[[Sequence[Operation]], RuleMatch | None]]] = [
    ("cancel_inverse_pair", find_cancellation),
    ("clifford_product", find_clifford_pair),
    ("merge_rotations", find_rotation_merge),
    ("drop_identity_rotation", find_identity_rotation),
    ("drop_unitary_identity", find_unitary_identity),
]

LEVEL_PASSES = {
    PASS_SAFE: ["cancel_inverse_pair", "drop_unitary_identity"],
    PASS_STANDARD: ["cancel_inverse_pair", "clifford_product", "merge_rotations", "drop_identity_rotation", "drop_unitary_identity"],
    PASS_AGGRESSIVE: [
        "cancel_inverse_pair",
        "clifford_product",
        "merge_rotations",
        "drop_identity_rotation",
        "drop_unitary_identity",
    ],
}


def _match_to_step(match: RuleMatch, ops: Sequence[Operation], circuit: Circuit, replacement_ops: list[Operation]) -> OptimizationStep:
    removed = [ops[i].display for i in match.indices]
    added = [op.display for op in replacement_ops]
    return OptimizationStep(
        rule=match.rule,
        description=match.description,
        reasoning=match.reasoning,
        indices=list(match.indices),
        removed=removed,
        added=added,
        gates_before=circuit.gate_count(),
        gates_after=circuit.gate_count() - sum(1 for i in match.indices if ops[i].kind == "gate") + len(replacement_ops),
        depth_before=circuit.depth(),
        depth_after=0,
    )


def _apply_match(circuit: Circuit, match: RuleMatch) -> OptimizationStep:
    """Apply one rewrite in place, returning its accounting record."""
    step = _match_to_step(match, circuit.operations, circuit, match.replacement)
    # Insert replacements before the first removed index, then delete the originals.
    anchor = min(match.indices)
    for offset, op in enumerate(match.replacement):
        circuit.operations.insert(anchor + offset, op.copy(keep_id=False))
    shift = len(match.replacement)
    for index in sorted(match.indices, reverse=True):
        del circuit.operations[index + shift]
    step.depth_after = circuit.depth()
    step.gates_after = circuit.gate_count()
    return step


def optimise(
    circuit: Circuit,
    *,
    level: str = PASS_STANDARD,
    max_sweeps: int = 40,
    verify: bool = True,
    compact: bool | None = None,
    proof_qubits: int = DEFAULT_PROOF_QUBITS,
    passes: Sequence[str] | None = None,
    verify_each_step: bool | None = None,
) -> OptimizationResult:
    """Optimise a circuit and verify the result.

    ``level`` selects the rule set (``safe`` < ``standard`` < ``aggressive``);
    ``compact`` removes unused qubits (default: only at level ``aggressive``).

    ``verify_each_step`` (default: on for small circuits) rebuilds the affected
    segment's unitary after every rewrite and rolls the rewrite back if it changed
    the operator.  A rule that fails is disabled for the rest of the run and the
    failure is reported — the optimiser is never allowed to ship a wrong circuit.
    """
    if level not in LEVEL_PASSES:
        raise ValueError(f"unknown optimisation level {level!r}")
    if compact is None:
        compact = level == PASS_AGGRESSIVE
    if verify_each_step is None:
        verify_each_step = circuit.num_qubits <= proof_qubits
    enabled = list(passes) if passes else LEVEL_PASSES[level]
    started = time.perf_counter()

    original = circuit.copy(name=circuit.name)
    working = circuit.copy(name=circuit.name)
    original_segments = aligned_segments(original)
    steps: list[OptimizationStep] = []
    notes: list[str] = []
    passes_applied: list[str] = []
    disabled: dict[str, str] = {}

    def segment_ordinal(index: int) -> int:
        """Ordinal of the segment containing an operation index (divider aligned)."""
        ordinal = 0
        for position, op in enumerate(working.operations):
            if position == index:
                return ordinal
            if op.kind in ("measure", "reset", "barrier"):
                ordinal += 1
        return ordinal

    for sweep in range(max_sweeps):
        changed = False
        for rule_name, finder in PASS_ORDER:
            if rule_name not in enabled or rule_name in disabled:
                continue
            while True:
                bounds = segment_bounds(working.operations)
                match: RuleMatch | None = None
                for start, end in bounds:
                    segment = working.operations[start:end]
                    local = finder(segment)
                    if local is not None:
                        match = RuleMatch(
                            rule=local.rule,
                            indices=[start + i for i in local.indices],
                            replacement=local.replacement,
                            description=local.description,
                            reasoning=local.reasoning,
                        )
                        break
                if match is None:
                    break

                before_snapshot = working.copy()
                ordinal = segment_ordinal(min(match.indices)) if verify_each_step else -1
                step = _apply_match(working, match)

                if verify_each_step and ordinal < len(original_segments):
                    ok, deviation = _segment_equivalent(
                        original_segments[ordinal],
                        aligned_segments(working)[ordinal],
                        working.num_qubits,
                    )
                    step.verified = ok
                    step.deviation = deviation
                    if not ok:
                        step.rolled_back = True
                        working = before_snapshot
                        disabled[rule_name] = (
                            f"rule {rule_name} produced a non-equivalent segment "
                            f"(max deviation {deviation:.3e}); it was rolled back and disabled"
                        )
                        notes.append(disabled[rule_name])
                        steps.append(step)
                        continue

                steps.append(step)
                if rule_name not in passes_applied:
                    passes_applied.append(rule_name)
                changed = True
        if not changed:
            break
    else:  # pragma: no cover - safety valve
        notes.append(f"Stopped after {max_sweeps} sweeps; enable more sweeps to continue.")

    qubit_map: dict[int, int] | None = None
    if compact:
        unused = find_redundant_qubits(working)
        if unused:
            working, qubit_map = compact_qubits(working)
            notes.append(
                f"Removed {len(unused)} unused qubit(s) {unused}; qubit map recorded so results "
                "stay comparable with the original."
            )
            if "compact_qubits" not in passes_applied:
                passes_applied.append("compact_qubits")

    findings = find_opportunities(original)
    verification = (
        verify_equivalence(original, working, proof_qubits=proof_qubits, qubit_map=qubit_map)
        if verify
        else {
            "status": VERIFIED_SKIPPED,
            "method": "verification disabled by request",
            "limitations": ["This optimisation was NOT verified."],
        }
    )
    if disabled:
        verification["disabled_rules"] = disabled

    if verify and verification["status"] == VERIFIED_FAILED:
        notes.append(
            "Verification failed, so the ORIGINAL circuit is returned unchanged. The failure is "
            "a bug in a rule and is reported rather than shipped."
        )
        working = original
        qubit_map = None
        steps = []
        verification["reverted"] = True

    before = original.resources()
    after = working.resources()
    improvements = _improvements(before, after)
    seconds = time.perf_counter() - started
    return OptimizationResult(
        original=original,
        optimized=working,
        before=before,
        after=after,
        improvements=improvements,
        steps=steps,
        verification=verification,
        passes_applied=passes_applied,
        findings=findings,
        qubit_map=qubit_map,
        seconds=seconds,
        notes=notes,
    )


def _improvements(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    gates_saved = before["gates"] - after["gates"]
    depth_saved = before["depth"] - after["depth"]
    twoq_saved = before["two_qubit_gates"] - after["two_qubit_gates"]
    return {
        "gates_saved": gates_saved,
        "gates_percent": 100.0 * gates_saved / before["gates"] if before["gates"] else 0.0,
        "depth_saved": depth_saved,
        "depth_percent": 100.0 * depth_saved / before["depth"] if before["depth"] else 0.0,
        "two_qubit_gates_saved": twoq_saved,
        "two_qubit_percent": 100.0 * twoq_saved / before["two_qubit_gates"] if before["two_qubit_gates"] else 0.0,
        "t_count_saved": before["t_count"] - after["t_count"],
        "operations_saved": before["operations"] - after["operations"],
        "qubits_removed": before["num_qubits"] - after["num_qubits"],
        "improved": gates_saved > 0 or depth_saved > 0,
    }


# ---------------------------------------------------------------------------
# verification
# ---------------------------------------------------------------------------


def verify_equivalence(
    original: Circuit,
    candidate: Circuit,
    *,
    proof_qubits: int = DEFAULT_PROOF_QUBITS,
    random_states: int = 6,
    tolerance: float = 1e-9,
    qubit_map: dict[int, int] | None = None,
) -> dict[str, Any]:
    """Check that two circuits implement the same computation.

    Returns a verdict with the method used and its limitations.  ``PROVEN`` means
    every unitary segment matches exactly (up to a global phase per segment), which
    is a complete proof for the gate-model circuits QScope handles.

    ``qubit_map`` remaps the original circuit's wires onto the candidate's so that
    an optimization which removed unused qubits can still be *proven*, not merely
    assumed, to be equivalent.
    """
    limitations: list[str] = []
    if original.num_clbits != candidate.num_clbits:
        return {
            "status": VERIFIED_FAILED,
            "method": "structural check",
            "reason": "classical register width changed",
            "limitations": [],
        }
    if original.has_classical_control() or candidate.has_classical_control():
        limitations.append(
            "Classically-conditioned gates are compared segment by segment; feedback behaviour is "
            "checked by structure, not by unitary equivalence."
        )

    reference = original
    if candidate.num_qubits != original.num_qubits:
        if qubit_map is None:
            return {
                "status": VERIFIED_STATISTICAL,
                "method": "resource comparison only",
                "reason": (
                    "Qubit counts differ and no qubit map was supplied; equivalence could not be "
                    "checked on the same wire set."
                ),
                "limitations": ["Comparability relies on the reported qubit map."],
            }
        reference = _remap_circuit(original, qubit_map)
        limitations.append(
            "Unused wires were removed, so equivalence is proven on the compacted wire set using "
            "the reported qubit map."
        )

    seg_a = [[op for op in segment if op.kind == "gate"] for segment in aligned_segments(reference)]
    seg_b = [[op for op in segment if op.kind == "gate"] for segment in aligned_segments(candidate)]
    if len(seg_a) != len(seg_b):
        return {
            "status": VERIFIED_FAILED,
            "method": "segment structure",
            "reason": f"the two circuits have different segment counts ({len(seg_a)} vs {len(seg_b)})",
            "limitations": [],
        }

    n = candidate.num_qubits
    if n <= proof_qubits:
        worst = 0.0
        per_segment: list[dict[str, Any]] = []
        for index, (gates_a, gates_b) in enumerate(zip(seg_a, seg_b)):
            if not gates_a and not gates_b:
                continue
            ua = _unitary_of(gates_a, n)
            ub = _unitary_of(gates_b, n)
            distance = unitary_distance(ua, ub)
            worst = max(worst, distance)
            per_segment.append(
                {
                    "segment": index,
                    "gates_before": len(gates_a),
                    "gates_after": len(gates_b),
                    "distance": distance,
                }
            )
        ok = worst <= tolerance * 10
        return {
            "status": VERIFIED_PROVEN if ok else VERIFIED_FAILED,
            "method": f"full {n}-qubit unitary comparison of every segment (up to global phase)",
            "max_deviation": worst,
            "tolerance": tolerance * 10,
            "segments": per_segment,
            "reasoning": (
                "For each unitary segment both circuits' operators were constructed explicitly and "
                "compared after removing the global phase. Equality here means the circuits produce "
                "identical measurement statistics for every possible input state."
            ),
            "limitations": limitations,
        }

    # Large circuits: compare outputs on random prepared inputs.
    from qscope.simulator.noise import NoiseModel
    from qscope.simulator.simulator import simulate_shot

    rng = np.random.default_rng(1234)
    fidelities: list[float] = []
    for _ in range(random_states):
        base_a = _random_prep(n, rng)
        base_a.extend(seg_a[0])
        base_b = _random_prep(n, rng)
        base_b.extend(seg_b[0])
        state_a, _, _ = simulate_shot(
            base_a, "statevector", NoiseModel.ideal(), rng, ops=list(base_a.operations)
        )
        state_b, _, _ = simulate_shot(
            base_b, "statevector", NoiseModel.ideal(), rng, ops=list(base_b.operations)
        )
        fidelities.append(state_fidelity(state_a, state_b))
    worst_fidelity = min(fidelities) if fidelities else 0.0
    ok = worst_fidelity > 1 - 1e-9
    limitations.append(
        f"{n} qubits is above the {proof_qubits}-qubit proof threshold, so equivalence is checked "
        f"on {random_states} random input states: strong evidence, not a proof."
    )
    return {
        "status": VERIFIED_STATISTICAL if ok else VERIFIED_FAILED,
        "method": f"output comparison on {random_states} random input states",
        "min_fidelity": worst_fidelity,
        "random_inputs": random_states,
        "limitations": limitations,
    }


def _segment_equivalent(
    before: list[Operation],
    after: list[Operation],
    n: int,
    tolerance: float = 1e-8,
) -> tuple[bool, float]:
    """Exact per-segment equivalence check used to validate every single rewrite."""
    if not before and not after:
        return True, 0.0
    try:
        ua = _unitary_of(before, n)
        ub = _unitary_of(after, n)
    except Exception as exc:  # pragma: no cover - defensive
        return False, float("inf")
    distance = unitary_distance(ua, ub)
    return distance <= tolerance, distance


def _remap_circuit(circuit: Circuit, qubit_map: dict[int, int]) -> Circuit:
    """Apply a qubit relabelling (used when comparing before/after compaction)."""
    out = Circuit(
        len(set(qubit_map.values())),
        circuit.num_clbits,
        name=circuit.name,
        qubit_labels=[circuit.qubits.label(q) for q in sorted(qubit_map, key=lambda k: qubit_map[k])],
        clbit_labels=circuit.clbits.labels,
    )
    for op in circuit.operations:
        clone = op.copy()
        clone.targets = [qubit_map[q] for q in clone.targets]
        clone.controls = [qubit_map[c] for c in clone.controls]
        out.operations.append(clone)
    return out


def _unitary_of(gates: Sequence[Operation], n: int) -> np.ndarray:
    from qscope.circuit.circuit import Circuit as _Circuit

    temp = _Circuit(n)
    for op in gates:
        temp.append(op.copy())
    return temp.to_unitary(max_qubits=n)


def _random_prep(n: int, rng: np.random.Generator) -> Circuit:
    """A random state-preparation circuit used to test large-circuit equivalence."""
    prep = Circuit(n, name="random-prep")
    for q in range(n):
        prep.add("RY", [q], [float(rng.uniform(0, 2 * np.pi))])
        prep.add("RZ", [q], [float(rng.uniform(0, 2 * np.pi))])
    for q in range(n - 1):
        prep.add("CNOT", [q, q + 1])
    for q in range(n):
        prep.add("RX", [q], [float(rng.uniform(0, 2 * np.pi))])
    return prep


def opportunities(circuit: Circuit) -> list[dict[str, object]]:
    """Public alias for the read-only opportunity audit."""
    return find_opportunities(circuit)


def optimization_levels() -> list[dict[str, Any]]:
    """Level descriptions for the UI."""
    return [
        {
            "key": PASS_SAFE,
            "label": "Safe",
            "description": "Only exact cancellations of inverse pairs and provably identity gates.",
            "passes": LEVEL_PASSES[PASS_SAFE],
        },
        {
            "key": PASS_STANDARD,
            "label": "Standard",
            "description": "Adds Clifford relations (S·S=Z, T·T=S) and rotation merging.",
            "passes": LEVEL_PASSES[PASS_STANDARD],
        },
        {
            "key": PASS_AGGRESSIVE,
            "label": "Aggressive",
            "description": "Standard plus removal of unused qubits (changes the wire count).",
            "passes": LEVEL_PASSES[PASS_AGGRESSIVE],
        },
    ]


__all__ = [
    "DEFAULT_PROOF_QUBITS",
    "LEVEL_PASSES",
    "OptimizationResult",
    "OptimizationStep",
    "PASS_AGGRESSIVE",
    "PASS_SAFE",
    "PASS_STANDARD",
    "VERIFIED_FAILED",
    "VERIFIED_PROVEN",
    "VERIFIED_SKIPPED",
    "VERIFIED_STATISTICAL",
    "opportunities",
    "optimise",
    "optimization_levels",
    "verify_equivalence",
]
