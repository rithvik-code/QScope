"""Algorithm laboratory.

Each entry returns a *complete, executable* QScope circuit plus everything a
research report needs to state what should happen: the analytic success
probability where one exists, the register that carries the answer, the classical
expectation, and the assumptions behind it.

Nothing here is a novelty claim — these are standard algorithms.  Their value in
QScope is that they all run through the same pipeline (trace, optimize, noise,
metrics, reports) as any hand-built circuit, so an algorithm is a *starting
point for experiments*, not a demo.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Sequence

import numpy as np

from qscope.circuit.circuit import Circuit, Condition


@dataclass
class AlgorithmSpec:
    """A named, runnable algorithm with its expectations attached."""

    key: str
    name: str
    circuit: Circuit
    description: str
    category: str
    difficulty: str
    parameters: dict[str, Any] = field(default_factory=dict)
    explanation: list[str] = field(default_factory=list)
    steps: list[str] = field(default_factory=list)
    expected_outcome: dict[str, Any] = field(default_factory=dict)
    solution_register: str | None = None
    analytic: dict[str, Any] = field(default_factory=dict)
    complexity: str = ""
    tags: list[str] = field(default_factory=list)
    references: list[str] = field(default_factory=list)

    def to_dict(self, include_circuit: bool = True) -> dict[str, Any]:
        out = {
            "key": self.key,
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "difficulty": self.difficulty,
            "parameters": self.parameters,
            "explanation": self.explanation,
            "steps": self.steps,
            "expected_outcome": self.expected_outcome,
            "solution_register": self.solution_register,
            "analytic": self.analytic,
            "complexity": self.complexity,
            "tags": self.tags,
            "references": self.references,
            "resources": self.circuit.resources(),
        }
        if include_circuit:
            out["circuit"] = self.circuit.to_dict()
        return out


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _phase_oracle(circuit: Circuit, marked: str, qubits: Sequence[int]) -> None:
    """Flip the sign of ``|marked>`` using X-conjugation plus a multi-controlled Z."""
    zeros = [q for q, bit in zip(qubits, marked) if bit == "0"]
    for q in zeros:
        circuit.add("X", [q])
    if len(qubits) == 2:
        circuit.add("CZ", list(qubits))
    elif len(qubits) == 3:
        circuit.add("CCZ", list(qubits))
    elif len(qubits) >= 4:
        last = qubits[-1]
        circuit.add("H", [last])
        circuit.add("MCX", list(qubits))
        circuit.add("H", [last])
    else:
        circuit.add("Z", list(qubits))
    for q in zeros:
        circuit.add("X", [q])


def _diffusion(circuit: Circuit, qubits: Sequence[int]) -> None:
    """Grover diffusion: ``2|s><s| - I`` in the computational basis."""
    for q in qubits:
        circuit.add("H", [q])
        circuit.add("X", [q])
    if len(qubits) == 2:
        circuit.add("CZ", list(qubits))
    elif len(qubits) == 3:
        circuit.add("CCZ", list(qubits))
    elif len(qubits) >= 4:
        last = qubits[-1]
        circuit.add("H", [last])
        circuit.add("MCX", list(qubits))
        circuit.add("H", [last])
    for q in qubits:
        circuit.add("X", [q])
        circuit.add("H", [q])


def _inverse_qft(circuit: Circuit, qubits: Sequence[int]) -> None:
    """Inverse QFT, built as the literal adjoint of the QFT circuit.

    Rather than re-deriving the reversed phase schedule by hand (an easy place to
    get the bit order wrong), this takes the forward QFT circuit and applies the
    adjoint of every gate in reverse order.  The test suite checks it against
    ``F^dagger`` directly, and ``QFT^dagger . QFT = I``.
    """
    from qscope.core.gates import inverse_gate

    template = Circuit(len(qubits))
    _qft(template, list(range(len(qubits))))
    for op in reversed(template.operations):
        name, params = inverse_gate(op.name, op.params)
        circuit.add(
            name,
            [qubits[t] for t in op.targets],
            params,
            controls=[qubits[c] for c in op.controls],
        )


def _qft(circuit: Circuit, qubits: Sequence[int]) -> None:
    n = len(qubits)
    if n > 1:
        for i in range(n // 2):
            circuit.add("SWAP", [qubits[i], qubits[n - 1 - i]])
    for i in reversed(range(n)):
        target = qubits[i]
        circuit.add("H", [target])
        for j in reversed(range(i)):
            control = qubits[j]
            angle = math.pi / (2 ** (i - j))
            circuit.add("P", [target], [angle], controls=[control])


# ---------------------------------------------------------------------------
# algorithms
# ---------------------------------------------------------------------------


def bell_state(variant: str = "phi_plus") -> AlgorithmSpec:
    """Two-qubit maximally entangled state."""
    circuit = Circuit(2, 2, name=f"bell_{variant}", description="Bell state preparation")
    circuit.add("H", [0])
    circuit.add("CNOT", [0, 1])
    if variant == "psi_minus":
        circuit.add("X", [0])
        circuit.add("Z", [0])
    circuit.metadata.update({"algorithm": "bell_state", "solution_register": "both qubits"})
    circuit.measure_all()
    return AlgorithmSpec(
        key="bell_state",
        name="Bell state",
        circuit=circuit,
        description="Prepare a maximally entangled two-qubit state with one Hadamard and one CNOT.",
        category="Foundations",
        difficulty="beginner",
        parameters={"variant": variant},
        explanation=[
            "H puts q0 into (|0> + |1>)/sqrt(2).",
            "CNOT entangles them: the pair becomes (|00> + |11>)/sqrt(2).",
            "Neither qubit has a definite value on its own; only the correlation does.",
        ],
        steps=["H(q0)", "CNOT(q0, q1)", "measure both"],
        expected_outcome={"counts": {"00": 0.5, "11": 0.5}, "entanglement": "maximal (concurrence 1)"},
        solution_register="both qubits",
        analytic={"probabilities": {"00": 0.5, "11": 0.5}, "concurrence": 1.0, "schmidt_rank": 2},
        complexity="2 gates, depth 2",
        tags=["entanglement", "foundations"],
        references=["Nielsen & Chuang, section 1.3.7"],
    )


def ghz_state(num_qubits: int = 3) -> AlgorithmSpec:
    """``( |0...0> + |1...1> ) / sqrt(2)`` on ``n`` qubits."""
    if num_qubits < 2:
        raise ValueError("GHZ needs at least 2 qubits")
    circuit = Circuit(num_qubits, num_qubits, name=f"ghz_{num_qubits}")
    circuit.add("H", [0])
    for q in range(1, num_qubits):
        circuit.add("CNOT", [q - 1, q])
    circuit.measure_all()
    circuit.metadata.update({"algorithm": "ghz", "solution_register": "all qubits"})
    return AlgorithmSpec(
        key="ghz_state",
        name=f"GHZ state ({num_qubits} qubits)",
        circuit=circuit,
        description="Maximally entangled n-qubit state: all-zeros and all-ones superposed.",
        category="Foundations",
        difficulty="beginner",
        parameters={"num_qubits": num_qubits},
        explanation=[
            "One Hadamard creates the superposition; the CNOT ladder copies the correlation down the line.",
            "Every single-qubit reduced state is maximally mixed, so the Bloch vectors shrink to zero.",
            "The two-qubit reduced states are classically correlated but not entangled — a counter-intuitive fact.",
        ],
        steps=["H(q0)", "CNOT ladder", "measure all"],
        expected_outcome={"counts": {"0" * num_qubits: 0.5, "1" * num_qubits: 0.5}},
        solution_register="all qubits",
        analytic={
            "probabilities": {"0" * num_qubits: 0.5, "1" * num_qubits: 0.5},
            "single_qubit_entropy": 1.0,
            "pairwise_concurrence": 0.0,
        },
        complexity=f"{num_qubits} gates, depth {num_qubits}",
        tags=["entanglement", "foundations", "scaling"],
        references=["Greenberger, Horne, Zeilinger (1989)"],
    )


def teleportation(theta: float = math.pi / 3) -> AlgorithmSpec:
    """Quantum teleportation of ``Ry(theta)|0>`` using one Bell pair and 2 classical bits."""
    circuit = Circuit(3, 2, name="teleportation", description="Teleport an unknown qubit state")
    circuit.add("RY", [0], [theta])  # the state to teleport
    circuit.add("H", [1])
    circuit.add("CNOT", [1, 2])  # Bell pair on (1, 2)
    circuit.add("CNOT", [0, 1])
    circuit.add("H", [0])
    circuit.measure(0, 0)
    circuit.measure(1, 1)
    circuit.add("X", [2], condition=Condition(1, 1))
    circuit.add("Z", [2], condition=Condition(0, 1))
    # q2 carries the teleported state.  It is deliberately left unmeasured: the
    # point of the protocol is the *state* on q2, and the analysis compares it
    # against the input state rather than against a bitstring.
    circuit.metadata.update({"algorithm": "teleportation", "solution_register": "q2"})
    return AlgorithmSpec(
        key="teleportation",
        name="Quantum teleportation",
        circuit=circuit,
        description="Transfer a qubit state using a shared Bell pair and two classical bits.",
        category="Protocols",
        difficulty="intermediate",
        parameters={"theta": theta},
        explanation=[
            "A Bell pair is shared between the sender (q1) and receiver (q2).",
            "A Bell-basis measurement on (q0, q1) collapses the pair and yields two classical bits.",
            "The classical bits select an X and/or Z correction on q2, restoring the original state.",
            f"Because Ry({theta:.4f})|0> = cos({theta / 2:.4f})|0> + sin({theta / 2:.4f})|1>, q2 should end in exactly that state.",
        ],
        steps=["prepare state on q0", "Bell pair on (q1,q2)", "Bell measurement on (q0,q1)",
               "classically controlled X and Z on q2"],
        expected_outcome={"q2_state": "cos(theta/2)|0> + sin(theta/2)|1>"},
        solution_register="q2",
        analytic={
            "theta": theta,
            "expected_amplitudes": [math.cos(theta / 2), math.sin(theta / 2)],
            "note": "The classical bits are random; the *state* is deterministic given the corrections.",
        },
        complexity="5 gates + 2 measurements, depth 4",
        tags=["protocol", "mid-circuit measurement", "classical control"],
        references=["Bennett et al. (1993)"],
    )


def deutsch_jozsa(num_qubits: int = 3, oracle: str = "balanced", mask: str | None = None) -> AlgorithmSpec:
    """Deutsch–Jozsa with ``n`` input qubits and one ancilla.

    ``oracle='balanced'`` implements ``f(x) = a · x mod 2`` for a non-zero mask
    ``a``, which is guaranteed balanced.  ``oracle='constant'`` implements ``f = 0``.
    """
    if num_qubits < 1:
        raise ValueError("Deutsch-Jozsa needs at least one input qubit")
    secret = mask or ("1" * num_qubits if num_qubits > 1 else "1")
    if oracle == "balanced" and set(secret) == {"0"}:
        raise ValueError("a balanced oracle needs at least one non-zero mask bit")
    n_total = num_qubits + 1
    ancilla = num_qubits
    circuit = Circuit(n_total, num_qubits, name=f"deutsch_jozsa_{num_qubits}")
    circuit.add("X", [ancilla])
    circuit.add("H", [ancilla])
    for q in range(num_qubits):
        circuit.add("H", [q])
    if oracle == "balanced":
        for index, bit in enumerate(secret):
            if bit == "1":
                circuit.add("CNOT", [index, ancilla])
    for q in range(num_qubits):
        circuit.add("H", [q])
    for q in range(num_qubits):
        circuit.measure(q, q)
    balanced = oracle == "balanced"
    circuit.metadata.update({"algorithm": "deutsch_jozsa", "solution_register": "input register"})
    return AlgorithmSpec(
        key="deutsch_jozsa",
        name=f"Deutsch-Jozsa ({num_qubits} qubits)",
        circuit=circuit,
        description="Decide with one oracle query whether f is constant or balanced.",
        category="Oracle algorithms",
        difficulty="intermediate",
        parameters={"num_qubits": num_qubits, "oracle": oracle, "mask": secret},
        explanation=[
            "The ancilla is prepared in |-> so the oracle writes f(x) into the phase (phase kickback).",
            "Hadamards map that phase pattern back into the computational basis.",
            "A constant function leaves all input qubits at |0...0>; a balanced function never does.",
        ],
        steps=["ancilla -> |->", "H on inputs", "phase oracle U_f", "H on inputs", "measure inputs"],
        expected_outcome={
            "decision": "balanced" if balanced else "constant",
            "certainty": 1.0,
        },
        solution_register="input register",
        analytic={
            "oracle": oracle,
            "mask": secret,
            "probability_all_zeros": 1.0 if not balanced else 0.0,
            "classical_queries_needed": 2 ** (num_qubits - 1) + 1,
            "quantum_queries_needed": 1,
        },
        complexity=f"{2 * num_qubits + 2} gates, depth 4",
        tags=["oracle", "speedup (query model)"],
        references=["Deutsch & Jozsa (1992)"],
    )


def bernstein_vazirani(secret: str = "101") -> AlgorithmSpec:
    """Recover a hidden bitstring in a single oracle query."""
    if not secret or any(ch not in "01" for ch in secret):
        raise ValueError("secret must be a non-empty binary string")
    n = len(secret)
    circuit = Circuit(n + 1, n, name=f"bernstein_vazirani_{n}")
    circuit.add("X", [n])
    circuit.add("H", [n])
    for q in range(n):
        circuit.add("H", [q])
    for index, bit in enumerate(secret):
        if bit == "1":
            circuit.add("CNOT", [index, n])
    for q in range(n):
        circuit.add("H", [q])
        circuit.measure(q, q)
    circuit.metadata.update({"algorithm": "bernstein_vazirani", "solution_register": "input register"})
    return AlgorithmSpec(
        key="bernstein_vazirani",
        name="Bernstein-Vazirani",
        circuit=circuit,
        description="Find the secret string s with a single query to f(x) = s·x mod 2.",
        category="Oracle algorithms",
        difficulty="intermediate",
        parameters={"secret": secret},
        explanation=[
            "Each controlled-NOT implements one bit of the inner product s·x.",
            "Phase kickback converts the oracle into phase factors e^{i pi s·x}.",
            "The final Hadamard layer interferes all other answers away, leaving exactly |s>.",
        ],
        steps=["ancilla -> |->", "H on inputs", "CNOTs for each 1 in the secret", "H on inputs", "measure"],
        expected_outcome={"measured_bitstring": secret, "probability": 1.0},
        solution_register="input register",
        analytic={
            "secret": secret,
            "probability_secret": 1.0,
            "classical_queries_needed": n,
            "quantum_queries_needed": 1,
        },
        complexity=f"{2 * n + 3} gates, depth 4",
        tags=["oracle", "speedup (query model)"],
        references=["Bernstein & Vazirani (1993)"],
    )


def grover(num_qubits: int = 4, marked: str | None = None, iterations: int | None = None) -> AlgorithmSpec:
    """Grover search over ``2^n`` items for one marked item."""
    if num_qubits < 2:
        raise ValueError("Grover needs at least 2 qubits (and 3+ for a non-trivial distribution)")
    marked = marked or "1" * num_qubits
    if len(marked) != num_qubits or any(ch not in "01" for ch in marked):
        raise ValueError(f"marked must be a {num_qubits}-bit binary string")
    n_items = 2**num_qubits
    optimal = max(1, int(round((math.pi / 4) * math.sqrt(n_items))))
    k = optimal if iterations is None else int(iterations)
    if k < 0:
        raise ValueError("iterations must be >= 0")

    qubits = list(range(num_qubits))
    circuit = Circuit(num_qubits, num_qubits, name=f"grover_{num_qubits}")
    for q in qubits:
        circuit.add("H", [q])
    for _ in range(k):
        _phase_oracle(circuit, marked, qubits)
        _diffusion(circuit, qubits)
    for q in qubits:
        circuit.measure(q, q)

    theta = math.asin(1 / math.sqrt(n_items))
    success = math.sin((2 * k + 1) * theta) ** 2
    circuit.metadata.update(
        {
            "algorithm": "grover",
            "solution_register": "all qubits",
            "marked": marked,
            "iterations": k,
        }
    )
    return AlgorithmSpec(
        key="grover",
        name=f"Grover search ({num_qubits} qubits)",
        circuit=circuit,
        description="Amplify the amplitude of one marked item among 2^n possibilities.",
        category="Search",
        difficulty="intermediate",
        parameters={"num_qubits": num_qubits, "marked": marked, "iterations": k},
        explanation=[
            f"The Hadamard layer creates an equal superposition of all {n_items} items.",
            "The phase oracle flips the sign of the marked item only.",
            "The diffusion operator reflects every amplitude about their mean, which amplifies the marked item.",
            f"The success probability after k iterations is sin^2((2k+1)theta) with "
            f"theta = arcsin(1/sqrt(N)); the optimal k = floor(pi/4 * sqrt(N)) = {optimal}.",
        ],
        steps=[
            "H^⊗n",
            f"{k} × [ phase oracle | diffusion ]",
            "measure",
        ],
        expected_outcome={
            "marked": marked,
            "success_probability": success,
            "iterations": k,
        },
        solution_register="all qubits",
        analytic={
            "theta": theta,
            "optimal_iterations": optimal,
            "success_probability": success,
            "classical_queries_expected": n_items / 2,
            "quantum_iterations": k,
            "amplification_ratio": success * n_items / max(k, 1),
        },
        complexity=f"{2 * num_qubits + 1} + {k} × {2 * num_qubits + (2 if num_qubits == 3 else 0)} gates",
        tags=["search", "amplitude amplification", "scaling"],
        references=["Grover (1996)"],
    )


def qft(num_qubits: int = 4) -> AlgorithmSpec:
    """Quantum Fourier transform on ``n`` qubits."""
    if num_qubits < 1:
        raise ValueError("QFT needs at least one qubit")
    circuit = Circuit(num_qubits, num_qubits, name=f"qft_{num_qubits}")
    _qft(circuit, list(range(num_qubits)))
    circuit.metadata.update({"algorithm": "qft", "solution_register": "frequency register"})
    return AlgorithmSpec(
        key="qft",
        name=f"Quantum Fourier transform ({num_qubits} qubits)",
        circuit=circuit,
        description="Map computational basis states onto Fourier (phase) basis states.",
        category="Subroutines",
        difficulty="advanced",
        parameters={"num_qubits": num_qubits},
        explanation=[
            "Each qubit gets a Hadamard, followed by controlled phase rotations set by every lower qubit.",
            "The rotations encode binary fractions of the phase, which is why the phase of rotation j is pi/2^(i-j).",
            "The final swaps reverse the bit order (the standard convention for an in-place QFT).",
        ],
        steps=["H + controlled phase rotations", "SWAPs to reverse the output order"],
        expected_outcome={"applied_to": "|x>", "result": "1/sqrt(N) sum_y exp(2 pi i x y / N) |y>"},
        solution_register="frequency register",
        analytic={"gate_count_formula": "n(n+1)/2 + floor(n/2)", "depth_order": "O(n^2) gates vs O(2^n) for a classical FFT"},
        complexity=f"{num_qubits * (num_qubits + 1) // 2 + num_qubits // 2} gates",
        tags=["subroutine", "phase estimation"],
        references=["Coppersmith (1994)"],
    )


def quantum_phase_estimation(
    counting_qubits: int = 4,
    phase: float = 0.3,
    *,
    eigenstate_flip: bool = True,
) -> AlgorithmSpec:
    """Estimate ``phi`` in ``U|psi> = e^{2 pi i phi}|psi>`` for ``U = P(2 pi phi)``."""
    if counting_qubits < 1:
        raise ValueError("phase estimation needs at least one counting qubit")
    if not 0 <= phase < 1:
        raise ValueError("phase must be in [0, 1)")
    n = counting_qubits
    target = n
    circuit = Circuit(n + 1, n, name=f"qpe_{n}")
    if eigenstate_flip:
        circuit.add("X", [target])
    for q in range(n):
        circuit.add("H", [q])
    # Qubit q carries the bit weight 2^(n-1-q) in our ordering, so the controlled
    # phase for that qubit must be 2*pi*phi*2^(n-1-q).  Using 2^q instead writes the
    # phase in reverse bit order and the inverse QFT then reads the wrong answer.
    for q in range(n):
        angle = 2 * math.pi * phase * (2 ** (n - 1 - q))
        circuit.add("P", [target], [angle], controls=[q])
    _inverse_qft(circuit, list(range(n)))
    for q in range(n):
        circuit.measure(q, q)

    best = int(round(phase * 2**n)) % 2**n
    estimate = best / 2**n
    delta = phase - estimate
    # Standard bound: P(measuring the best n-bit estimate) >= 4/pi^2 ~= 0.405.
    circuit.metadata.update({"algorithm": "qpe", "solution_register": "counting register"})
    return AlgorithmSpec(
        key="quantum_phase_estimation",
        name=f"Quantum phase estimation ({n} counting qubits)",
        circuit=circuit,
        description="Estimate an eigenvalue phase with n-bit precision using the inverse QFT.",
        category="Subroutines",
        difficulty="advanced",
        parameters={"counting_qubits": n, "phase": phase},
        explanation=[
            f"The target qubit is an eigenstate of P(2*pi*{phase}), so controlled applications write the phase into the counting register.",
            "Each controlled-P applies a phase 2*pi*phi*2^j, encoding phi in binary fractional bits.",
            "The inverse QFT converts that phase pattern into a readable binary number.",
            f"The most likely outcome is {best} ({best}/{2**n} = {estimate:.6f}), within "
            f"{abs(delta):.6f} of the true phase {phase}.",
        ],
        steps=["prepare eigenstate", "H on counting register", "controlled-U^(2^j)",
               "inverse QFT", "measure counting register"],
        expected_outcome={
            "most_likely_bitstring": format(best, f"0{n}b"),
            "estimate": estimate,
            "true_phase": phase,
            "absolute_error": abs(delta),
        },
        solution_register="counting register",
        analytic={
            "best_estimate": estimate,
            "resolution": 1 / 2**n,
            "probability_of_best_estimate_at_least": 4 / math.pi**2,
            "true_phase": phase,
        },
        complexity=f"{n} H + {n} controlled-P + inverse QFT on {n} qubits",
        tags=["subroutine", "eigenvalue", "precision"],
        references=["Kitaev (1995)", "Nielsen & Chuang, section 5.2"],
    )


def vqe_ansatz(num_qubits: int = 3, layers: int = 2, params: Sequence[float] | None = None) -> AlgorithmSpec:
    """Hardware-efficient variational ansatz (RY layers with a CNOT ring)."""
    if num_qubits < 2:
        raise ValueError("VQE needs at least 2 qubits")
    n_params = layers * num_qubits * 2
    if params is None:
        params = [0.4] * n_params
    if len(params) != n_params:
        raise ValueError(f"this ansatz has {n_params} parameters, got {len(params)}")
    circuit = Circuit(num_qubits, num_qubits, name=f"vqe_{num_qubits}x{layers}")
    cursor = 0
    for layer in range(layers):
        for q in range(num_qubits):
            circuit.add("RY", [q], [float(params[cursor])]); cursor += 1
            circuit.add("RZ", [q], [float(params[cursor])]); cursor += 1
        for q in range(num_qubits):
            circuit.add("CNOT", [q, (q + 1) % num_qubits])
    for q in range(num_qubits):
        circuit.measure(q, q)
    circuit.metadata.update({"algorithm": "vqe", "solution_register": "expectation values"})
    return AlgorithmSpec(
        key="vqe_ansatz",
        name=f"VQE ansatz ({num_qubits} qubits, {layers} layers)",
        circuit=circuit,
        description="A parameterised circuit whose energy is measured and minimised classically.",
        category="Variational",
        difficulty="advanced",
        parameters={"num_qubits": num_qubits, "layers": layers, "params": list(params)},
        explanation=[
            "Each layer applies a rotation to every qubit, then entangles them with a CNOT ring.",
            "The energy is <psi(theta)|H|psi(theta)>; a classical optimiser updates theta.",
            "QScope evaluates the energy exactly from the simulated state, so any optimisation you see "
            "is free of shot noise (a useful baseline before adding noise).",
        ],
        steps=["parameterised rotations", "entangling ring", "measure in a basis defined by H"],
        expected_outcome={"note": "The output depends on the parameters; use the experiment lab to sweep them."},
        solution_register="expectation values",
        analytic={"parameters": n_params, "parameter_shift_rule": "d<H>/d theta = <H(theta+pi/2)> - <H(theta-pi/2)> for RY/RZ generators"},
        complexity=f"{2 * n_params} rotations + {layers * num_qubits} CNOTs",
        tags=["variational", "optimization", "near-term"],
        references=["Peruzzo et al. (2014)"],
    )


def qaoa_maxcut(
    num_qubits: int = 4,
    edges: Sequence[Sequence[int]] | None = None,
    layers: int = 1,
    params: Sequence[float] | None = None,
) -> AlgorithmSpec:
    """QAOA for Max-Cut on a graph with ``num_qubits`` vertices."""
    if num_qubits < 2:
        raise ValueError("QAOA needs at least 2 qubits")
    if edges is None:
        edges = [[i, (i + 1) % num_qubits] for i in range(num_qubits)]
    edges = [tuple(int(v) for v in e) for e in edges]
    for a, b in edges:
        if not (0 <= a < num_qubits and 0 <= b < num_qubits) or a == b:
            raise ValueError(f"invalid edge {(a, b)} for {num_qubits} vertices")
    n_params = 2 * layers
    if params is None:
        params = [0.6] * n_params
    if len(params) != n_params:
        raise ValueError(f"QAOA with {layers} layer(s) needs {n_params} parameters (gamma, beta per layer)")

    circuit = Circuit(num_qubits, num_qubits, name=f"qaoa_maxcut_{num_qubits}")
    for q in range(num_qubits):
        circuit.add("H", [q])
    for layer in range(layers):
        gamma = float(params[2 * layer])
        beta = float(params[2 * layer + 1])
        for a, b in edges:
            circuit.add("RZZ", [a, b], [2 * gamma])
        for q in range(num_qubits):
            circuit.add("RX", [q], [2 * beta])
    for q in range(num_qubits):
        circuit.measure(q, q)
    circuit.metadata.update({"algorithm": "qaoa", "solution_register": "all qubits", "edges": [list(e) for e in edges]})
    return AlgorithmSpec(
        key="qaoa_maxcut",
        name=f"QAOA Max-Cut ({num_qubits} qubits, {layers} layer(s))",
        circuit=circuit,
        description="Approximate the maximum cut of a graph with a shallow alternating ansatz.",
        category="Variational",
        difficulty="advanced",
        parameters={"num_qubits": num_qubits, "edges": [list(e) for e in edges], "layers": layers, "params": list(params)},
        explanation=[
            "The cost layer applies exp(-i gamma Z_a Z_b) per edge, which encodes the cut value in phases.",
            "The mixer layer applies RX(2 beta) per qubit so amplitude can move between bitstrings.",
            "Measuring gives cuts; the approximation ratio compares the best sampled cut with the true optimum.",
        ],
        steps=["H^⊗n", f"{layers} × [cost layer | mixer layer]", "measure"],
        expected_outcome={"note": "Use qscope.evaluate_maxcut to score the sampled cuts against the optimum."},
        solution_register="all qubits",
        analytic={
            "edges": [list(e) for e in edges],
            "parameters": n_params,
            "cost_hamiltonian": "sum_edges (I - Z_a Z_b) / 2",
            "mixer_hamiltonian": "sum_v X_v",
        },
        complexity=f"{num_qubits} + {layers} × ({len(edges)} RZZ + {num_qubits} RX)",
        tags=["variational", "combinatorial", "near-term"],
        references=["Farhi, Goldstone, Gutmann (2014)"],
    )


# ---------------------------------------------------------------------------
# evaluation helpers
# ---------------------------------------------------------------------------


def evaluate_maxcut(graph_edges: Sequence[Sequence[int]], bitstring: str) -> dict[str, Any]:
    """Cut value of one bitstring, its optimum, and the approximation ratio."""
    edges = [tuple(int(v) for v in e) for e in graph_edges]
    bits = [int(b) for b in bitstring]
    cut = sum(1 for a, b in edges if bits[a] != bits[b])
    n = len(bits)
    optimum = 0
    for candidate in range(2**n):
        value = sum(
            1 for a, b in edges if ((candidate >> (n - 1 - a)) & 1) != ((candidate >> (n - 1 - b)) & 1)
        )
        optimum = max(optimum, value)
    return {
        "bitstring": bitstring,
        "cut_value": cut,
        "optimum": optimum,
        "approximation_ratio": cut / optimum if optimum else 0.0,
        "is_optimal": cut == optimum,
    }


def evaluate_maxcut_counts(edges: Sequence[Sequence[int]], counts: dict[str, int]) -> dict[str, Any]:
    """Score a whole histogram for Max-Cut: best cut, mean cut, approximation ratio."""
    if not counts:
        return {"rows": [], "best": None, "mean_cut": 0.0, "approximation_ratio": 0.0}
    total = sum(counts.values())
    per_shot = []
    weighted = 0.0
    best: dict[str, Any] | None = None
    for bitstring, count in sorted(counts.items(), key=lambda kv: -kv[1]):
        scored = evaluate_maxcut(edges, bitstring)
        scored["count"] = count
        scored["frequency"] = count / total
        weighted += scored["cut_value"] * count
        if best is None or scored["cut_value"] > best["cut_value"]:
            best = scored
        per_shot.append(scored)
    optimum = per_shot[0]["optimum"]
    mean_cut = weighted / total
    return {
        "rows": per_shot,
        "best": best,
        "mean_cut": mean_cut,
        "optimum": optimum,
        "approximation_ratio": best["cut_value"] / optimum if optimum and best else 0.0,
        "mean_approximation_ratio": mean_cut / optimum if optimum else 0.0,
        "optimal_fraction": sum(r["frequency"] for r in per_shot if r["is_optimal"]),
    }


def ising_hamiltonian(
    num_qubits: int,
    coupling: float = 1.0,
    field: float = 1.0,
    edges: Sequence[Sequence[int]] | None = None,
) -> list[tuple[str, float]]:
    """Transverse-field Ising Hamiltonian as a list of ``(pauli_string, coefficient)``.

    ``H = -J sum_edges Z_a Z_b - h sum_v X_v``.  Used by the VQE workspace to turn a
    simulated state into an energy with no hidden approximation.
    """
    if edges is None:
        edges = [[i, (i + 1) % num_qubits] for i in range(num_qubits)]
    terms: list[tuple[str, float]] = []
    for a, b in edges:
        string = ["I"] * num_qubits
        string[a] = "Z"
        string[b] = "Z"
        terms.append(("".join(string), -float(coupling)))
    for q in range(num_qubits):
        string = ["I"] * num_qubits
        string[q] = "X"
        terms.append(("".join(string), -float(field)))
    return terms


def expectation_value(state: Any, terms: Sequence[tuple[str, float]]) -> float:
    """``<psi|H|psi>`` for a Hamiltonian given as Pauli terms (exact for a state vector)."""
    return float(sum(coeff * state.expectation_pauli(pauli) for pauli, coeff in terms))


def grover_success_probability(num_qubits: int, iterations: int) -> float:
    """Analytic Grover success probability, for comparison with a simulation."""
    n_items = 2**num_qubits
    theta = math.asin(1 / math.sqrt(n_items))
    return math.sin((2 * iterations + 1) * theta) ** 2


def algorithm_catalog() -> list[dict[str, Any]]:
    """Catalogue metadata for the UI (no circuits, so it stays small)."""
    builders = [
        lambda: bell_state(),
        lambda: ghz_state(3),
        lambda: teleportation(),
        lambda: deutsch_jozsa(3),
        lambda: bernstein_vazirani("101"),
        lambda: grover(4),
        lambda: qft(4),
        lambda: quantum_phase_estimation(4, 0.3),
        lambda: vqe_ansatz(3, 2),
        lambda: qaoa_maxcut(4),
    ]
    out = []
    for builder in builders:
        spec = builder()
        out.append(
            {
                "key": spec.key,
                "name": spec.name,
                "description": spec.description,
                "category": spec.category,
                "difficulty": spec.difficulty,
                "parameters": spec.parameters,
                "tags": spec.tags,
                "complexity": spec.complexity,
                "qubits": spec.circuit.num_qubits,
                "gates": spec.circuit.gate_count(),
                "depth": spec.circuit.depth(),
            }
        )
    return out


ALGORITHMS: dict[str, Any] = {
    "bell_state": bell_state,
    "ghz_state": ghz_state,
    "teleportation": teleportation,
    "deutsch_jozsa": deutsch_jozsa,
    "bernstein_vazirani": bernstein_vazirani,
    "grover": grover,
    "qft": qft,
    "quantum_phase_estimation": quantum_phase_estimation,
    "vqe_ansatz": vqe_ansatz,
    "qaoa_maxcut": qaoa_maxcut,
}


def build_algorithm(key: str, **kwargs: Any) -> AlgorithmSpec:
    """Build an algorithm by key with keyword parameters."""
    if key not in ALGORITHMS:
        raise KeyError(f"unknown algorithm {key!r}; available: {sorted(ALGORITHMS)}")
    return ALGORITHMS[key](**kwargs)


__all__ = [
    "ALGORITHMS",
    "AlgorithmSpec",
    "algorithm_catalog",
    "bell_state",
    "bernstein_vazirani",
    "build_algorithm",
    "deutsch_jozsa",
    "evaluate_maxcut",
    "evaluate_maxcut_counts",
    "expectation_value",
    "ghz_state",
    "grover",
    "grover_success_probability",
    "ising_hamiltonian",
    "qaoa_maxcut",
    "qft",
    "quantum_phase_estimation",
    "teleportation",
    "vqe_ansatz",
]
