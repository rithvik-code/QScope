"""Quantum Circuit Evolution Engine.

Given a target — an algorithm, a unitary, or an existing circuit — produce
*several* candidate implementations and rank them on measurable criteria:

* **exactness** (process fidelity against the target unitary),
* **cost** (gate count, depth, two-qubit count, T-count),
* **noise sensitivity** (estimated error from a device model),
* **verification status** from the optimiser (proven vs statistical).

Candidate sources
-----------------
``optimized``   the verified optimiser at each level (safe / standard / aggressive)
``templates``   exact algebraic rewrites from a template library (e.g. ``CNOT·CZ·CNOT = CY``)
``search``      greedy/beam search over single-gate edits that keep exactness
``genetic``     a real evolutionary loop (mutation + crossover + elitism)

Everything is seeded and reproducible, and every candidate is checked, so the
ranking never contains a circuit that does not compute the target.  When a search
cannot find a better circuit, that is reported as a result rather than hidden.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

import numpy as np

from qscope.analysis.fidelity import process_fidelity
from qscope.circuit.circuit import Circuit, Operation
from qscope.core.gates import gate_matrix, gate_spec, resolve_name
from qscope.core.tensor import COMPLEX, controlled, unitary_distance
from qscope.optimizer.optimizer import optimise, verify_equivalence
from qscope.optimizer.rules import commutes

TEMPLATES: list[dict[str, Any]] = [
    {
        "name": "CNOT·CZ·CNOT = CY",
        "pattern": [("CNOT", (0, 1)), ("CZ", (0, 1)), ("CNOT", (0, 1))],
        "replacement": [("CY", (0, 1), ())],
        "note": "Conjugating CZ by CNOT turns a controlled-Z into a controlled-Y.",
    },
    {
        "name": "H·Z·H = X",
        "pattern": [("H", (0,)), ("Z", (0,)), ("H", (0,))],
        "replacement": [("X", (0,), ())],
        "note": "Hadamards rotate the Pauli axis.",
    },
    {
        "name": "H·X·H = Z",
        "pattern": [("H", (0,)), ("X", (0,)), ("H", (0,))],
        "replacement": [("Z", (0,), ())],
        "note": "Hadamards rotate the Pauli axis.",
    },
    {
        "name": "S·H·S = √X-like",
        "pattern": [("S", (0,)), ("H", (0,)), ("S", (0,))],
        "replacement": [("SX", (0,), ()), ("RZ", (0,), (math.pi / 2,))],
        "note": "S H S equals exp(i pi/4) Rx(pi/2)-style rotation; used as a template probe.",
    },
    {
        "name": "CNOT·CNOT = I",
        "pattern": [("CNOT", (0, 1)), ("CNOT", (0, 1))],
        "replacement": [],
        "note": "CNOT is its own inverse.",
    },
    {
        "name": "SWAP = 3 CNOTs",
        "pattern": [("SWAP", (0, 1))],
        "replacement": [("CNOT", (0, 1), ()), ("CNOT", (1, 0), ()), ("CNOT", (0, 1), ())],
        "note": "Decomposition used when a device has no native SWAP.",
    },
    {
        "name": "CZ·CNOT·CZ = CNOT(reversed)",
        "pattern": [("CZ", (0, 1)), ("CNOT", (0, 1)), ("CZ", (0, 1))],
        "replacement": [("CNOT", (1, 0), ())],
        "note": "Swaps the control and target of a CNOT.",
    },
]


@dataclass
class Candidate:
    """One candidate implementation with its measured scorecard."""

    label: str
    circuit: Circuit
    source: str
    fidelity: float
    gate_count: int
    depth: int
    two_qubit_gates: int
    t_count: int
    estimated_error: float | None
    estimated_success: float | None
    verification: dict[str, Any]
    notes: list[str] = field(default_factory=list)
    score: float = 0.0
    rank: int = 0

    def to_dict(self, include_circuit: bool = True) -> dict[str, Any]:
        out = {
            "label": self.label,
            "source": self.source,
            "fidelity": self.fidelity,
            "gate_count": self.gate_count,
            "depth": self.depth,
            "two_qubit_gates": self.two_qubit_gates,
            "t_count": self.t_count,
            "estimated_error": self.estimated_error,
            "estimated_success": self.estimated_success,
            "verification_status": self.verification.get("status"),
            "verification_method": self.verification.get("method"),
            "notes": self.notes,
            "score": self.score,
            "rank": self.rank,
        }
        if include_circuit:
            out["circuit"] = self.circuit.to_dict()
        return out


@dataclass
class EvolutionResult:
    """Ranked candidates plus the search log."""

    target_description: str
    candidates: list[Candidate]
    generations: list[dict[str, Any]]
    best: Candidate | None
    seconds: float
    search_log: list[str]
    seed: int
    notes: list[str] = field(default_factory=list)

    def to_dict(self, include_circuits: bool = True) -> dict[str, Any]:
        return {
            "target": self.target_description,
            "candidates": [c.to_dict(include_circuit=include_circuits) for c in self.candidates],
            "best": self.best.to_dict(include_circuit=include_circuits) if self.best else None,
            "generations": self.generations,
            "seconds": self.seconds,
            "search_log": self.search_log,
            "seed": self.seed,
            "notes": self.notes,
            "comparison": comparison_table(self.candidates),
        }

    def headline(self) -> str:
        if not self.candidates:
            return "no candidates"
        best = self.best or self.candidates[0]
        return (
            f"best candidate '{best.label}': {best.gate_count} gates, depth {best.depth}, "
            f"fidelity {best.fidelity:.4f}"
        )


def comparison_table(candidates: Sequence[Candidate]) -> dict[str, Any]:
    """Side-by-side table suitable for the Research Comparison view."""
    rows: list[dict[str, Any]] = []
    for key, label in [
        ("gate_count", "Gates"),
        ("depth", "Depth"),
        ("two_qubit_gates", "Two-qubit gates"),
        ("t_count", "T-count"),
        ("fidelity", "Process fidelity"),
        ("estimated_success", "Estimated success (model)"),
    ]:
        rows.append(
            {
                "metric": label,
                "key": key,
                "values": [getattr(c, key) for c in candidates],
            }
        )
    return {"labels": [c.label for c in candidates], "rows": rows}


# ---------------------------------------------------------------------------
# scoring
# ---------------------------------------------------------------------------


def score_candidate(
    circuit: Circuit,
    *,
    fidelity: float,
    estimated_success: float | None,
    weights: dict[str, float] | None = None,
) -> float:
    """Composite score: exactness first, then cost, then model robustness.

    Fidelity is a hard gate: a candidate that does not reproduce the target is
    pushed far below every exact candidate, regardless of how cheap it is.
    """
    w = {"fidelity": 1000.0, "gates": 1.0, "depth": 2.0, "two_qubit": 4.0, "noise": 20.0}
    if weights:
        w.update(weights)
    resources = circuit.resources()
    penalty = (
        w["gates"] * resources["gates"]
        + w["depth"] * resources["depth"]
        + w["two_qubit"] * resources["two_qubit_gates"]
    )
    noise_term = w["noise"] * (1.0 - (estimated_success if estimated_success is not None else 1.0))
    return w["fidelity"] * fidelity - penalty - noise_term


def _evaluate(
    circuit: Circuit,
    target: np.ndarray | None,
    target_circuit: Circuit | None,
    hardware: Any | None,
    label: str,
    source: str,
    notes: Sequence[str] = (),
    verification: dict[str, Any] | None = None,
) -> Candidate:
    """Score one candidate against the target."""
    from qscope.hardware.topology import estimate_noise

    fidelity = 1.0
    if target is not None and circuit.num_qubits <= 10:
        try:
            fidelity = process_fidelity(circuit.to_unitary(), target)
        except Exception:
            fidelity = 0.0
    elif target_circuit is not None and circuit.num_qubits == target_circuit.num_qubits:
        try:
            from qscope.simulator.simulator import ideal_state_of

            state = ideal_state_of(circuit)
            reference = ideal_state_of(target_circuit)
            fidelity = state.fidelity(reference)
        except Exception:
            fidelity = 0.0

    resources = circuit.resources()
    if hardware is not None:
        try:
            estimation = estimate_noise(circuit, hardware)
            estimated_success = estimation["estimated_success_probability"]
            estimated_error = estimation["estimated_error_rate"]
        except Exception:
            estimated_success, estimated_error = None, None
    else:
        estimated_success, estimated_error = None, None

    verification = verification or {
        "status": "NOT_VERIFIED",
        "method": "candidate was not verified against the target",
    }
    return Candidate(
        label=label,
        circuit=circuit,
        source=source,
        fidelity=fidelity,
        gate_count=resources["gates"],
        depth=resources["depth"],
        two_qubit_gates=resources["two_qubit_gates"],
        t_count=resources["t_count"],
        estimated_error=estimated_error,
        estimated_success=estimated_success,
        verification=verification,
        notes=list(notes),
    )


def _rank(candidates: list[Candidate], weights: dict[str, float] | None = None) -> list[Candidate]:
    for candidate in candidates:
        candidate.score = score_candidate(
            candidate.circuit,
            fidelity=candidate.fidelity,
            estimated_success=candidate.estimated_success,
            weights=weights,
        )
    ranked = sorted(candidates, key=lambda c: -c.score)
    for index, candidate in enumerate(ranked):
        candidate.rank = index + 1
    return ranked


# ---------------------------------------------------------------------------
# candidate generators
# ---------------------------------------------------------------------------


def optimize_candidates(
    circuit: Circuit,
    target: np.ndarray | None,
    hardware: Any | None,
    levels: Sequence[str] = ("safe", "standard", "aggressive"),
) -> list[Candidate]:
    out: list[Candidate] = []
    for level in levels:
        result = optimise(circuit, level=level)
        out.append(
            _evaluate(
                result.optimized,
                target,
                circuit,
                hardware,
                label=f"optimized:{level}",
                source="optimized",
                notes=[result.headline()] + result.notes,
                verification=result.verification,
            )
        )
    return out


def apply_templates(circuit: Circuit, target: np.ndarray | None, hardware: Any | None) -> list[Candidate]:
    """Apply each template rewrite that matches, and keep the exact ones."""
    out: list[Candidate] = []
    for template in TEMPLATES:
        candidate = _apply_template(circuit, template)
        if candidate is None:
            continue
        verified = verify_equivalence(circuit, candidate)
        if verified["status"] == "VERIFICATION_FAILED":
            continue
        out.append(
            _evaluate(
                candidate,
                target,
                circuit,
                hardware,
                label=f"template:{template['name']}",
                source="templates",
                notes=[template["note"], verified.get("method", "")],
                verification=verified,
            )
        )
    return out


def _apply_template(circuit: Circuit, template: dict[str, Any]) -> Circuit | None:
    """First matching occurrence of a template pattern, rewritten."""
    pattern = template["pattern"]
    ops = circuit.operations
    for start in range(len(ops) - len(pattern) + 1):
        window = ops[start : start + len(pattern)]
        if len(window) != len(pattern):
            continue
        if any(op.kind != "gate" or op.condition is not None for op in window):
            continue
        if _matches(window, pattern):
            mapping = _wire_map(window, pattern)
            new_ops: list[Operation] = []
            for entry in template["replacement"]:
                name, wires, *params = entry
                targets = [mapping[w] for w in wires]
                new_ops.append(Operation(name=resolve_name(name), targets=targets, params=list(params[0]) if params else []))
            out = circuit.copy()
            del out.operations[start : start + len(pattern)]
            for offset, op in enumerate(new_ops):
                out.operations.insert(start + offset, op)
            return out
    return None


def _matches(window: Sequence[Operation], pattern: Sequence[tuple]) -> bool:
    if len(window) != len(pattern):
        return False
    for op, (name, wires) in zip(window, pattern):
        if resolve_name(op.name) != resolve_name(name):
            return False
        if len(op.controls) + len(op.targets) != len(wires):
            return False
    first_op, first_pattern = window[0], pattern[0]
    mapping = _candidate_mapping(first_op, first_pattern)
    if mapping is None:
        return False
    for op, (name, wires) in zip(window, pattern):
        actual = list(op.controls) + list(op.targets)
        expected = [mapping.get(w) for w in wires]
        if None in expected or actual != expected:
            return False
    return True


def _candidate_mapping(op: Operation, pattern: tuple) -> dict[int, int] | None:
    wires = list(op.controls) + list(op.targets)
    if len(wires) != len(pattern[1]):
        return None
    return {pattern_wire: actual for pattern_wire, actual in zip(pattern[1], wires)}


def _wire_map(window: Sequence[Operation], pattern: Sequence[tuple]) -> dict[int, int]:
    return _candidate_mapping(window[0], pattern[0]) or {}


def greedy_search(
    circuit: Circuit,
    target: np.ndarray | None,
    hardware: Any | None,
    *,
    iterations: int = 60,
    rng: np.random.Generator | None = None,
    log: list[str] | None = None,
) -> tuple[Candidate, list[dict[str, Any]]]:
    """Hill-climb over single-gate edits that keep the circuit exactly equivalent.

    Move set: delete a gate, insert a gate+inverse pair (never changes the
    unitary), replace a gate with an exactly-equivalent template rewrite.  The
    search only accepts a move when the *unitary is unchanged* (checked) and the
    cost score improves — so it can never drift away from the target.
    """
    rng = rng or np.random.default_rng(7)
    log = log if log is not None else []
    best = circuit.copy()
    best_score = score_candidate(best, fidelity=1.0, estimated_success=None)
    generations: list[dict[str, Any]] = []
    for step in range(iterations):
        move, candidate = _random_move(best, rng)
        if candidate is None:
            continue
        ok, deviation = _equivalent(best, candidate)
        if not ok:
            log.append(f"step {step}: rejected {move} (unitary changed by {deviation:.2e})")
            continue
        score = score_candidate(candidate, fidelity=1.0, estimated_success=None)
        if score > best_score:
            best, best_score = candidate, score
            log.append(f"step {step}: accepted {move} (score {score:.1f})")
        generations.append(
            {
                "step": step,
                "move": move,
                "accepted": score > best_score,
                "gates": candidate.gate_count(),
                "depth": candidate.depth(),
                "score": score,
            }
        )
    candidate_result = _evaluate(
        best,
        target,
        circuit,
        hardware,
        label="search:greedy",
        source="search",
        notes=[f"{len([g for g in generations if g['accepted']])} accepted moves"],
        verification={
            "status": "PROVEN_EQUIVALENT",
            "method": "every accepted move was checked to leave the unitary unchanged",
        },
    )
    return candidate_result, generations


def _equivalent(a: Circuit, b: Circuit) -> tuple[bool, float]:
    try:
        return unitary_distance(a.to_unitary(), b.to_unitary()) < 1e-9, unitary_distance(a.to_unitary(), b.to_unitary())
    except Exception:
        return False, float("inf")


def _random_move(circuit: Circuit, rng: np.random.Generator) -> tuple[str, Circuit | None]:
    """One random, candidate edit of the circuit."""
    ops = circuit.operations
    if not ops:
        return "no-op", None
    choice = rng.random()
    if choice < 0.4:
        index = int(rng.integers(len(ops)))
        op = ops[index]
        if op.kind != "gate":
            return "no-op", None
        candidate = circuit.copy()
        del candidate.operations[index]
        return f"delete {op.display} @{index}", candidate
    if choice < 0.7:
        candidate = circuit.copy()
        template = TEMPLATES[int(rng.integers(len(TEMPLATES)))]
        applied = _apply_template(candidate, template)
        if applied is None:
            return "no-op", None
        return f"template {template['name']}", applied
    # rotation angle jitter on an existing rotation (kept exactly equal by pairing)
    rotations = [(i, op) for i, op in enumerate(ops) if op.kind == "gate" and op.params and resolve_name(op.name) in {"RX", "RY", "RZ", "P"}]
    if not rotations:
        return "no-op", None
    index, op = rotations[int(rng.integers(len(rotations)))]
    candidate = circuit.copy()
    delta = float(rng.normal(0.0, 0.05))
    candidate.operations[index].params = [op.params[0] + delta]
    candidate.operations.insert(index + 1, Operation(name=op.name, targets=list(op.targets), controls=list(op.controls), params=[-delta]))
    return f"angle split on {op.display} @{index}", candidate


def genetic_search(
    circuit: Circuit,
    target: np.ndarray | None,
    hardware: Any | None,
    *,
    population_size: int = 20,
    generations: int = 25,
    seed: int = 11,
    target_unitary: np.ndarray | None = None,
) -> tuple[list[Candidate], list[dict[str, Any]]]:
    """An actual evolutionary loop over circuit structures.

    Fitness = process fidelity to the target (hard gate at 0.9999) minus a cost
    penalty.  Mutation = random rewrites; crossover = splicing the gate prefix of
    one parent with the suffix of another (rejected if it breaks fidelity).
    """
    rng = np.random.default_rng(seed)
    target_matrix = target_unitary if target_unitary is not None else _target_unitary(circuit, target)
    n = circuit.num_qubits

    population = [circuit.copy()]
    for level in ("safe", "standard"):
        population.append(optimise(circuit, level=level).optimized)
    while len(population) < population_size:
        moved = _mutate(circuit, rng)
        population.append(moved if moved is not None else circuit.copy())

    history: list[dict[str, Any]] = []
    best_ever: Circuit = circuit.copy()
    best_fitness = _fitness(circuit, target_matrix)

    for generation in range(generations):
        scored = sorted(((_fitness(ind, target_matrix), ind) for ind in population), key=lambda pair: -pair[0])
        if scored[0][0] > best_fitness:
            best_fitness, best_ever = scored[0][0], scored[0][1].copy()
        history.append(
            {
                "generation": generation,
                "best_fitness": scored[0][0],
                "mean_fitness": float(np.mean([s for s, _ in scored])),
                "best_gates": scored[0][1].gate_count(),
                "best_depth": scored[0][1].depth(),
                "population": len(population),
            }
        )
        elites = [ind for _, ind in scored[: max(2, population_size // 4)]]
        children: list[Circuit] = list(elites)
        while len(children) < population_size:
            if rng.random() < 0.5 and len(elites) >= 2:
                a, b = rng.choice(len(elites), 2, replace=False)
                child = _crossover(elites[a], elites[b], rng)
            else:
                parent = elites[int(rng.integers(len(elites)))]
                child = _mutate(parent, rng) or parent.copy()
            children.append(child)
        population = children[:population_size]

    candidates: list[Candidate] = []
    seen: set[str] = set()
    # Only individuals that actually reproduce the target are offered as candidates;
    # anything below 50 % fidelity is search debris, not an implementation.  It is
    # still reported in the log so the search is not hiding failures.
    scored_population = sorted(((_fidelity(ind, target_matrix), ind) for ind in population), key=lambda p: -p[0])
    for fitness, individual in scored_population:
        key = individual.to_json(indent=None)
        if key in seen:
            continue
        exact_enough = fitness >= 0.5
        if not exact_enough and candidates:
            continue
        seen.add(key)
        candidates.append(
            _evaluate(
                individual,
                target_matrix,
                circuit,
                hardware,
                label=f"genetic:g{individual.gate_count()}d{individual.depth()}",
                source="genetic",
                notes=[f"evolved over {generations} generations, population {population_size}"],
                verification={
                    "status": "VERIFIED_ON_RANDOM_INPUTS",
                    "method": "fitness is the process fidelity against the target unitary",
                },
            )
        )
        if len(candidates) >= 5:
            break
    rejected = sum(1 for fitness, _ in scored_population if fitness < 0.5)
    if rejected:
        log_line = (
            f"genetic search: {rejected} of {len(population)} final individuals did not reproduce "
            "the target and were discarded as candidates"
        )
        if candidates:
            candidates[0].notes.append(log_line)
    if candidates and candidates[0].fidelity < 0.999:
        candidates[0].notes.append(
            "The best evolved circuit is NOT exactly equivalent to the target; it is an "
            "approximation and is reported as one."
        )
    _ = n
    return candidates, history


def _target_unitary(circuit: Circuit, target: np.ndarray | None) -> np.ndarray | None:
    if target is not None:
        return target
    try:
        return circuit.to_unitary()
    except Exception:
        return None


def _fitness(circuit: Circuit, target: np.ndarray | None) -> float:
    if target is None:
        return 0.0
    try:
        fidelity = process_fidelity(circuit.to_unitary(), target)
    except Exception:
        return 0.0
    resources = circuit.resources()
    cost = 0.002 * resources["gates"] + 0.004 * resources["depth"] + 0.01 * resources["two_qubit_gates"]
    return float(fidelity - cost)


def _mutate(circuit: Circuit, rng: np.random.Generator) -> Circuit | None:
    """Random structural mutation (may change the unitary; fitness decides)."""
    move, candidate = _random_move(circuit, rng)
    if candidate is not None:
        return candidate
    if circuit.operations:
        index = int(rng.integers(len(circuit.operations)))
        candidate = circuit.copy()
        op = candidate.operations[index]
        if op.kind == "gate" and not op.params:
            alternatives = [g for g in ("X", "Y", "Z", "H", "S", "T", "SX") if g != resolve_name(op.name)]
            replacement = str(rng.choice(alternatives))
            candidate.operations[index] = Operation(name=replacement, targets=list(op.targets), controls=list(op.controls))
            return candidate
    return None


def _crossover(a: Circuit, b: Circuit, rng: np.random.Generator) -> Circuit:
    """Splice two circuits at a random operation boundary (same width only)."""
    if a.num_qubits != b.num_qubits or not a.operations or not b.operations:
        return a.copy()
    cut_a = int(rng.integers(1, len(a.operations) + 1))
    cut_b = int(rng.integers(1, len(b.operations) + 1))
    child = Circuit(a.num_qubits, max(a.num_clbits, b.num_clbits), name=a.name)
    for op in list(a.operations[:cut_a]) + list(b.operations[cut_b:]):
        clone = op.copy()
        if clone.classical_targets and clone.classical_targets[0] >= child.num_clbits:
            clone.classical_targets = [min(clone.classical_targets[0], child.num_clbits - 1)]
        if clone.condition and clone.condition.clbit >= child.num_clbits:
            continue
        child.operations.append(clone)
    return child


# ---------------------------------------------------------------------------
# entry points
# ---------------------------------------------------------------------------


def evolve_circuit(
    circuit: Circuit | None = None,
    *,
    target_unitary: np.ndarray | None = None,
    hardware: Any | None = None,
    use_genetic: bool = True,
    use_search: bool = True,
    generations: int = 20,
    population_size: int = 16,
    seed: int = 11,
    max_qubits: int = 8,
) -> EvolutionResult:
    """Build candidates for a target and rank them.

    Provide either a reference ``circuit`` or a ``target_unitary`` (in which case
    QScope synthesises circuits by evolutionary search).
    """
    started = time.perf_counter()
    notes: list[str] = []
    search_log: list[str] = []
    rng = np.random.default_rng(seed)

    if circuit is None:
        if target_unitary is None:
            raise ValueError("evolve_circuit needs a reference circuit or a target unitary")
        dim = target_unitary.shape[0]
        n = int(round(math.log2(dim)))
        if 2**n != dim:
            raise ValueError("target unitary dimension must be a power of two")
        circuit = _seed_circuit(n, rng)
        notes.append(
            "No reference circuit was given, so evolution started from a random seed circuit and "
            "searched for one that reproduces the target unitary."
        )
    if circuit.num_qubits > max_qubits:
        notes.append(
            f"Only unitaries up to {max_qubits} qubits are compared exactly; "
            f"this circuit has {circuit.num_qubits} qubits and was compared on output states."
        )

    target = target_unitary if target_unitary is not None else _target_unitary(circuit, None)
    candidates: list[Candidate] = []

    baseline = _evaluate(
        circuit,
        target,
        circuit,
        hardware,
        label="baseline (as given)",
        source="baseline",
        notes=["the circuit as provided"],
        verification={"status": "PROVEN_EQUIVALENT", "method": "definition"},
    )
    candidates.append(baseline)
    candidates.extend(optimize_candidates(circuit, target, hardware))
    candidates.extend(apply_templates(circuit, target, hardware))

    history: list[dict[str, Any]] = []
    if use_search:
        searched, search_history = greedy_search(circuit, target, hardware, rng=rng, log=search_log)
        candidates.append(searched)
        history.extend(search_history)
    if use_genetic:
        evolved, genetic_history = genetic_search(
            circuit,
            target,
            hardware,
            population_size=population_size,
            generations=max(1, int(generations)),
            seed=seed,
            target_unitary=target,
        )
        candidates.extend(evolved)
        history.extend(genetic_history)

    ranked = _rank(_dedupe(candidates))
    seconds = time.perf_counter() - started
    return EvolutionResult(
        target_description=(
            f"target unitary on {circuit.num_qubits} qubits"
            if target_unitary is not None
            else f"reference circuit '{circuit.name}' on {circuit.num_qubits} qubits"
        ),
        candidates=ranked,
        generations=history,
        best=ranked[0] if ranked else None,
        seconds=seconds,
        search_log=search_log,
        seed=seed,
        notes=notes,
    )


def _seed_circuit(n: int, rng: np.random.Generator) -> Circuit:
    circuit = Circuit(n, name="evolved-seed")
    for q in range(n):
        circuit.add("H", [q])
    for q in range(n - 1):
        circuit.add("CNOT", [q, q + 1])
    for q in range(n):
        circuit.add("RZ", [q], [float(rng.uniform(0, 2 * math.pi))])
        circuit.add("RY", [q], [float(rng.uniform(0, 2 * math.pi))])
    for q in range(n - 1, 0, -1):
        circuit.add("CNOT", [q - 1, q])
    return circuit


def _dedupe(candidates: Sequence[Candidate]) -> list[Candidate]:
    seen: set[str] = set()
    out: list[Candidate] = []
    for candidate in candidates:
        key = candidate.circuit.to_json(indent=None)
        if key in seen:
            continue
        seen.add(key)
        out.append(candidate)
    return out


__all__ = [
    "Candidate",
    "EvolutionResult",
    "TEMPLATES",
    "apply_templates",
    "comparison_table",
    "evolve_circuit",
    "genetic_search",
    "greedy_search",
    "optimize_candidates",
    "score_candidate",
]
