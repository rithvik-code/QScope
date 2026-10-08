"""Mathematical correctness tests for the QScope core.

Every assertion here is checked against a value that can be derived by hand, or
against an independent brute-force computation.  If a number in QScope is wrong,
this file is where it should fail first.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from qscope.analysis.entanglement import (
    ENTANGLED,
    SEPARABLE,
    concurrence,
    entanglement_report,
    negativity,
    pairwise_concurrence,
    partial_transpose,
)
from qscope.analysis.entropy import participation_ratio, purity, shannon, von_neumann
from qscope.analysis.fidelity import (
    process_fidelity,
    state_fidelity,
    total_variation,
    trace_distance,
)
from qscope.circuit import Circuit, from_qasm
from qscope.core import (
    DensityMatrix,
    StateVector,
    apply_kraus,
    basis_label,
    basis_state,
    controlled_matrix,
    gate_matrix,
    is_close,
    kron_list,
    partial_trace,
    unitary_distance,
)
from qscope.core.gates import gate_catalog
from qscope.simulator.noise import KRAUS_BUILDERS, build_kraus

CATALOG = {entry["name"]: entry for entry in gate_catalog()}

# --------------------------------------------------------------- tensor layer


def test_kron_list_orders_the_first_qubit_most_significant() -> None:
    x = gate_matrix("X", ())
    identity = gate_matrix("I", ())
    # X on qubit 0 of a two-qubit register is X (x) I, not I (x) X
    expected = np.kron(x, identity)
    assert np.allclose(kron_list([x, identity]), expected)


def test_basis_state_and_label_agree() -> None:
    state = basis_state(3, 5)  # |101>
    amp = state.amplitudes() if isinstance(state, StateVector) else state
    assert amp.shape == (8,)
    assert abs(amp[5] - 1.0) < 1e-12
    assert basis_label(3, 5) == "101"
    assert abs(np.sum(np.abs(amp) ** 2) - 1.0) < 1e-12


def test_controlled_matrix_acts_only_on_the_one_branch() -> None:
    matrix = controlled_matrix(gate_matrix("X", ()), 1)
    # identity on the control=0 block, X on the control=1 block
    expected = np.eye(4, dtype=complex)
    expected[2:, 2:] = [[0, 1], [1, 0]]
    assert np.allclose(matrix, expected)
    assert np.allclose(matrix, gate_matrix("CNOT", ()))


def test_unitary_distance_ignores_global_phase_only() -> None:
    h = gate_matrix("H", ())
    assert abs(unitary_distance(h, h)) < 1e-12
    assert abs(unitary_distance(h, -h)) < 1e-12  # -H is the same operator
    assert abs(unitary_distance(h, 1j * h)) < 1e-12
    assert unitary_distance(h, gate_matrix("X", ())) > 0.1


# -------------------------------------------------------------- gate algebra


@pytest.mark.parametrize("name", sorted(CATALOG))
def test_every_gate_in_the_catalog_is_unitary(name: str) -> None:
    entry = CATALOG[name]
    arity = entry["num_qubits"]
    params = [0.7] * len(entry["params"])
    matrix = np.asarray(gate_matrix(name, params), dtype=complex)
    size = 2**arity
    assert matrix.shape == (size, size), f"{name}: expected {size}x{size}"
    assert np.allclose(matrix.conj().T @ matrix, np.eye(size), atol=1e-12), name
    assert np.allclose(np.asarray(entry["matrix"], dtype=complex), gate_matrix(name, [0.7] * 0), atol=1e-12) if not entry["params"] else True


def test_known_gate_actions() -> None:
    zero = StateVector.zero_state(1)
    plus = StateVector(1, [1 / math.sqrt(2), 1 / math.sqrt(2)])

    assert np.allclose(zero.copy().apply_gate("H", [0]).amplitudes(), plus.amplitudes())
    assert np.allclose(zero.copy().apply_gate("X", [0]).amplitudes(), [0, 1])
    assert np.allclose(zero.copy().apply_gate("Z", [0]).amplitudes(), [1, 0])
    assert np.allclose(zero.copy().apply_gate("S", [0]).amplitudes(), [1, 0])
    # Rx(pi) |0> = -i |1>
    assert np.allclose(zero.copy().apply_gate("RX", [0], [math.pi]).amplitudes(), [0, -1j])
    # Ry(pi/2) |0> = (|0> + |1>)/sqrt(2)
    assert np.allclose(zero.copy().apply_gate("RY", [0], [math.pi / 2]).amplitudes(), [1 / math.sqrt(2), 1 / math.sqrt(2)])
    # Rz(pi) |+> = |->, i.e. the phase flips sign on |1>
    assert np.allclose(plus.copy().apply_gate("RZ", [0], [math.pi]).amplitudes(), [1 / math.sqrt(2), -1 / math.sqrt(2)])


def test_phase_gate_powers_follow_the_known_relations() -> None:
    # S^2 = Z, T^2 = S
    s2 = gate_matrix("S", ()) @ gate_matrix("S", ())
    assert np.allclose(s2, gate_matrix("Z", ()), atol=1e-12)
    t2 = gate_matrix("T", ()) @ gate_matrix("T", ())
    assert np.allclose(t2, gate_matrix("S", ()), atol=1e-12)


def test_normalisation_is_preserved_by_every_gate() -> None:
    rng = np.random.default_rng(0)
    names = ["X", "Y", "Z", "H", "S", "T"]
    for trial in range(20):
        state = StateVector(3)
        for _ in range(12):
            name = names[int(rng.integers(len(names)))]
            state.apply_gate(name, [int(rng.integers(3))])
        assert abs(state.norm() - 1.0) < 1e-10, trial
        assert state.is_normalized()


def test_normalize_rescales_an_unnormalised_vector() -> None:
    state = StateVector(1, [3.0, 4.0])
    assert abs(state.norm() - 5.0) < 1e-12
    assert not state.is_normalized()
    state.normalize()
    assert state.is_normalized()
    assert abs(state.probability(0) - 0.36) < 1e-12  # (3/5)^2


# ---------------------------------------------------------------- statevector


def test_bell_state_amplitudes_are_exactly_right() -> None:
    circuit = Circuit(2, 2, name="bell")
    circuit.add("H", [0])
    circuit.add("CNOT", [1], controls=[0])
    state = StateVector(2).apply_gate("H", [0]).apply_controlled("X", [0], [1])

    amps = state.amplitudes()
    assert abs(amps[0] - 1 / math.sqrt(2)) < 1e-12  # |00>
    assert abs(amps[3] - 1 / math.sqrt(2)) < 1e-12  # |11>
    assert abs(amps[1]) < 1e-12  # |01>
    assert abs(amps[2]) < 1e-12  # |10>
    assert abs(state.probability(0) - 0.5) < 1e-12
    assert abs(state.probability(3) - 0.5) < 1e-12
    assert state.support() == [0, 3]
    # the circuit and the hand-built state must agree
    assert np.allclose(circuit.to_unitary() @ np.array([1, 0, 0, 0], dtype=complex), amps)


def test_reduced_density_of_bell_state_is_maximally_mixed() -> None:
    bell = StateVector(2, [1 / math.sqrt(2), 0, 0, 1 / math.sqrt(2)])
    reduced = bell.reduced_density([0])
    assert np.allclose(reduced, np.eye(2) / 2, atol=1e-12)
    assert abs(bell.entanglement_entropy([0]) - 1.0) < 1e-12
    assert bell.schmidt_rank([0]) == 2


def test_partial_trace_matches_the_statevector_reduction() -> None:
    bell = StateVector(2, [1 / math.sqrt(2), 0, 0, 1 / math.sqrt(2)])
    assert np.allclose(partial_trace(bell.density_matrix(), [0], 2), bell.reduced_density([0]), atol=1e-12)
    assert np.allclose(partial_trace(bell.density_matrix(), [1], 2), bell.reduced_density([1]), atol=1e-12)


def test_ghz_state_has_only_two_branches_and_maximal_single_qubit_entropy() -> None:
    ghz = StateVector(3, [1 / math.sqrt(2), 0, 0, 0, 0, 0, 0, 1 / math.sqrt(2)])
    assert ghz.support() == [0, 7]
    assert ghz.entanglement_entropy([0]) > 0.999
    assert ghz.entanglement_entropy([0, 1]) > 0.999
    # a GHZ state is not a product state and not biseparable across any cut
    assert ghz.dominant_basis() == "000"


def _bloch(state: StateVector, qubit: int = 0) -> list[float]:
    vector = state.bloch_vector(qubit)
    return [vector.x, vector.y, vector.z]


def test_bloch_vector_of_the_known_poles() -> None:
    assert np.allclose(_bloch(StateVector.zero_state(1)), [0, 0, 1], atol=1e-12)
    assert np.allclose(_bloch(StateVector(1, [0, 1])), [0, 0, -1], atol=1e-12)
    assert np.allclose(_bloch(StateVector(1, [1 / math.sqrt(2), 1 / math.sqrt(2)])), [1, 0, 0], atol=1e-12)
    assert np.allclose(_bloch(StateVector(1, [1 / math.sqrt(2), -1j / math.sqrt(2)])), [0, 1, 0], atol=1e-12)
    # a maximally mixed qubit has no Bloch vector at all
    bell = DensityMatrix.from_statevector(StateVector(2, [1 / math.sqrt(2), 0, 0, 1 / math.sqrt(2)]))
    mixed = bell.bloch_vector(0)
    assert abs(mixed.x) < 1e-12 and abs(mixed.y) < 1e-12 and abs(mixed.z) < 1e-12


def test_pauli_expectations_for_a_bell_state() -> None:
    bell = StateVector(2, [1 / math.sqrt(2), 0, 0, 1 / math.sqrt(2)])
    # <ZZ> = +1, <XX> = +1, <YY> = -1, <ZI> = 0, <IZ> = 0
    assert abs(bell.expectation_pauli("ZZ") - 1.0) < 1e-12
    assert abs(bell.expectation_pauli("XX") - 1.0) < 1e-12
    assert abs(bell.expectation_pauli("YY") + 1.0) < 1e-12
    assert abs(bell.expectation_pauli("ZI")) < 1e-12
    assert abs(bell.expectation_pauli("IZ")) < 1e-12


def test_measurement_of_superposition_returns_both_outcomes() -> None:
    counts = {"0": 0, "1": 0}
    rng = np.random.default_rng(20260101)
    for _ in range(4000):
        state = StateVector(1, [1 / math.sqrt(2), 1 / math.sqrt(2)])
        outcome = state.measure_qubit(0, rng=rng)
        counts[str(outcome.outcome)] += 1
    # 4000 draws: the standard error on a 50 % rate is 0.0079
    assert abs(counts["0"] / 4000 - 0.5) < 0.04, counts
    assert counts["1"] > 0


def test_measurement_collapses_and_renormalises() -> None:
    state = StateVector(1, [1 / math.sqrt(3), math.sqrt(2 / 3)])
    outcome = state.measure_qubit(0, outcome=0)
    assert abs(outcome.probability - 1 / 3) < 1e-12
    assert np.allclose(state.amplitudes(), [1, 0])
    assert state.is_normalized()


# -------------------------------------------------------------- density matrix


def test_density_matrix_properties() -> None:
    bell = StateVector(2, [1 / math.sqrt(2), 0, 0, 1 / math.sqrt(2)])
    rho = DensityMatrix.from_statevector(bell)
    assert rho.is_valid()
    assert abs(rho.trace() - 1.0) < 1e-12
    assert rho.is_pure()
    assert abs(rho.purity() - 1.0) < 1e-12
    assert abs(rho.entropy()) < 1e-12

    mixed = DensityMatrix.maximally_mixed(2)
    assert abs(mixed.purity() - 0.25) < 1e-12  # 1/2^n
    assert abs(mixed.entropy() - 2.0) < 1e-12  # log2(4)


def test_dephasing_removes_off_diagonal_coherence_without_changing_populations() -> None:
    plus = DensityMatrix.from_statevector(StateVector(1, [1 / math.sqrt(2), 1 / math.sqrt(2)]))
    populations = plus.probabilities().copy()
    plus.dephase(0, 1.0)
    assert np.allclose(plus.probabilities(), populations, atol=1e-12)
    assert abs(plus.data[0, 1]) < 1e-12
    assert abs(plus.data[1, 0]) < 1e-12
    assert np.allclose(plus.data, np.eye(2) / 2, atol=1e-12)


def test_amplitude_damping_drives_one_towards_zero() -> None:
    one = DensityMatrix.from_statevector(StateVector(1, [0, 1]))
    kraus = build_kraus("amplitude_damping", {"gamma": 0.3})
    one.apply_channel(kraus, [0])
    assert abs(one.data[0, 0] - 0.3) < 1e-12
    assert abs(one.data[1, 1] - 0.7) < 1e-12
    assert one.is_valid()


@pytest.mark.parametrize("kind", sorted(KRAUS_BUILDERS))
def test_every_kraus_set_is_trace_preserving_and_valid(kind: str) -> None:
    defaults = {"p": 0.2, "gamma": 0.2, "lambda": 0.2, "t1": 50.0, "t2": 40.0, "duration": 0.1}
    params = {name: defaults[name] for name in KRAUS_BUILDERS[kind][1] if name in defaults}
    kraus = build_kraus(kind, params)
    total = sum(k.conj().T @ k for k in kraus)
    assert np.allclose(total, np.eye(2), atol=1e-12), kind

    rho = DensityMatrix.from_statevector(StateVector(1, [1 / math.sqrt(2), 1 / math.sqrt(2)]))
    rho.apply_channel(kraus, [0])
    assert rho.is_valid(), kind
    assert abs(rho.trace() - 1.0) < 1e-12


def test_apply_kraus_matches_the_density_matrix_path() -> None:
    kraus = build_kraus("depolarizing", {"p": 0.4})
    rho = DensityMatrix.from_statevector(StateVector(1, [1, 0]))
    rho.apply_channel(kraus, [0])
    expected = sum(k @ np.array([[1, 0], [0, 0]]) @ k.conj().T for k in kraus)
    assert np.allclose(rho.data, expected, atol=1e-12)


# ------------------------------------------------------------------ analysis


def test_fidelity_and_trace_distance_sanity() -> None:
    a = StateVector(1, [1, 0])
    b = StateVector(1, [0, 1])
    assert abs(state_fidelity(a, a) - 1.0) < 1e-12
    assert abs(state_fidelity(a, b)) < 1e-12  # orthogonal

    plus = StateVector(1, [1 / math.sqrt(2), 1 / math.sqrt(2)])
    assert abs(state_fidelity(a, plus) - 0.5) < 1e-12  # |<0|+>|^2

    rho_a, rho_b = DensityMatrix.from_statevector(a), DensityMatrix.from_statevector(b)
    assert abs(rho_a.trace_distance(rho_b) - 1.0) < 1e-12
    assert abs(rho_a.trace_distance(rho_a)) < 1e-12


def test_total_variation_handles_different_support() -> None:
    assert abs(total_variation({"0": 0.5, "1": 0.5}, {"0": 0.5, "1": 0.5})) < 1e-12
    assert abs(total_variation({"0": 1.0}, {"1": 1.0}) - 1.0) < 1e-12
    assert abs(total_variation({"00": 0.5, "11": 0.5}, {"00": 1.0}) - 0.5) < 1e-12


def test_process_fidelity_recognises_equivalent_circuits() -> None:
    identity = np.eye(4, dtype=complex)
    assert abs(process_fidelity(identity, identity) - 1.0) < 1e-12
    assert abs(process_fidelity(identity, -identity) - 1.0) < 1e-12
    assert process_fidelity(identity, gate_matrix("SWAP", ())) < 0.5
    # a Bell circuit and the same circuit with the CX reversed must differ
    cnot = gate_matrix("CNOT", ())
    reversed_cnot = np.eye(4, dtype=complex)
    reversed_cnot[[1, 2]] = reversed_cnot[[2, 1]]
    assert process_fidelity(cnot, reversed_cnot) < 0.5


def test_entropy_helpers_on_known_distributions() -> None:
    assert abs(von_neumann(np.diag([1.0, 0.0]))) < 1e-12
    assert abs(von_neumann(np.diag([0.5, 0.5])) - 1.0) < 1e-12
    assert abs(shannon([0.5, 0.5]) - 1.0) < 1e-12
    assert abs(purity(np.diag([0.25, 0.25, 0.25, 0.25])) - 0.25) < 1e-12
    # participation ratio of a uniform distribution over 4 states is 4
    assert abs(participation_ratio([0.25] * 4) - 4.0) < 1e-12
    assert abs(participation_ratio([1.0, 0.0, 0.0, 0.0]) - 1.0) < 1e-12


def test_concurrence_of_the_four_bell_states() -> None:
    bell = {
        "phi+": [1 / math.sqrt(2), 0, 0, 1 / math.sqrt(2)],
        "phi-": [1 / math.sqrt(2), 0, 0, -1 / math.sqrt(2)],
        "psi+": [0, 1 / math.sqrt(2), 1 / math.sqrt(2), 0],
        "psi-": [0, 1 / math.sqrt(2), -1 / math.sqrt(2), 0],
    }
    for label, amps in bell.items():
        rho = DensityMatrix.from_statevector(StateVector(2, amps))
        assert abs(concurrence(rho, 0, 1) - 1.0) < 1e-9, label
        assert abs(negativity(rho, 0, 1) - 0.5) < 1e-9, label


def test_product_states_are_reported_separable_and_never_as_entangled() -> None:
    product = StateVector(1, [1 / math.sqrt(2), 1 / math.sqrt(2)])
    two = StateVector(2, np.kron(product.amplitudes(), product.amplitudes()))
    rho = DensityMatrix.from_statevector(two)
    assert concurrence(rho, 0, 1) < 1e-9
    assert negativity(rho, 0, 1) < 1e-9
    report = entanglement_report(two)
    assert report["status"] == SEPARABLE
    assert report["max_concurrence"] < 1e-9

    entangling = entanglement_report(StateVector(2, [1 / math.sqrt(2), 0, 0, 1 / math.sqrt(2)]))
    assert entangling["status"] == ENTANGLED
    assert abs(entangling["max_concurrence"] - 1.0) < 1e-9
    assert entangling["pairs"][0]["a"] == 0 and entangling["pairs"][0]["b"] == 1
    assert entangling["limitations"], "an entanglement verdict must state what it cannot see"


def test_partial_transpose_has_the_expected_spectrum() -> None:
    bell = DensityMatrix.from_statevector(StateVector(2, [1 / math.sqrt(2), 0, 0, 1 / math.sqrt(2)]))
    eigenvalues = np.linalg.eigvalsh(partial_transpose(bell.data, 0, 2))
    eigenvalues = np.sort(eigenvalues)
    assert abs(eigenvalues[0] + 0.5) < 1e-12, eigenvalues
    assert abs(eigenvalues[-1] - 0.5) < 1e-12


def test_pairwise_concurrence_matrix_is_symmetric_with_zero_diagonal() -> None:
    ghz = DensityMatrix.from_statevector(StateVector(3, [1 / math.sqrt(2), 0, 0, 0, 0, 0, 0, 1 / math.sqrt(2)]))
    matrix = np.asarray(pairwise_concurrence(ghz))
    assert matrix.shape == (3, 3)
    assert np.allclose(np.diag(matrix), 0.0, atol=1e-12)
    assert np.allclose(matrix, matrix.T, atol=1e-12)
    # in a GHZ state every pair is classically correlated but not pairwise entangled
    assert np.all(matrix < 1e-9)


# ------------------------------------------------------------------- circuit


def test_circuit_depth_and_resources_on_a_known_circuit() -> None:
    circuit = Circuit(3, name="layers")
    circuit.add("H", [0])
    circuit.add("H", [1])
    circuit.add("H", [2])
    circuit.add("CNOT", [1], controls=[0])
    circuit.add("CNOT", [2], controls=[1])
    resources = circuit.resources()
    assert resources["gates"] == 5
    assert resources["two_qubit_gates"] == 2
    assert resources["depth"] == 3  # H,H,H | CX | CX
    assert resources["num_qubits"] == 3
    assert len(circuit.layers()) == 3


def test_cnot_direction_matters_and_matches_the_hand_built_matrix() -> None:
    forward = Circuit(2)
    forward.add("CNOT", [1], controls=[0])
    backward = Circuit(2)
    backward.add("CNOT", [0], controls=[1])

    expected_forward = np.eye(4, dtype=complex)
    expected_forward[[2, 3]] = expected_forward[[3, 2]]
    assert np.allclose(forward.to_unitary(), expected_forward)
    assert unitary_distance(forward.to_unitary(), backward.to_unitary()) > 0.5
    # CNOT is its own inverse
    assert unitary_distance(forward.to_unitary(), forward.to_unitary().conj().T) < 1e-12


def test_to_unitary_handles_permuted_target_order() -> None:
    # SWAP and a reversed-target CX must not be confused with each other
    swap = Circuit(2)
    swap.add("SWAP", [0, 1])
    assert np.allclose(swap.to_unitary(), np.array([[1, 0, 0, 0], [0, 0, 1, 0], [0, 1, 0, 0], [0, 0, 0, 1]], dtype=complex))

    toffoli = Circuit(3)
    toffoli.add("TOFFOLI", [2], controls=[0, 1])
    matrix = toffoli.to_unitary()
    assert np.allclose(matrix @ matrix, np.eye(8), atol=1e-12)  # self-inverse
    assert np.allclose(matrix[0, 0], 1.0)
    assert np.allclose(matrix[7, 6], 1.0)  # |110> -> |111>


def test_inverse_circuit_composes_to_the_identity_for_random_circuits() -> None:
    rng = np.random.default_rng(7)
    names = ["H", "X", "Y", "Z", "S", "T", "RX", "RY", "RZ"]
    for trial in range(12):
        circuit = Circuit(3)
        for _ in range(14):
            name = names[int(rng.integers(len(names)))]
            params = [float(rng.uniform(0, 2 * math.pi))] if name.startswith("R") else []
            circuit.add(name, [int(rng.integers(3))], params)
        combined = circuit.copy()
        for op in reversed(circuit.operations):
            combined.operations.append(op.inverse())
        assert unitary_distance(combined.to_unitary(), np.eye(8)) < 1e-9, trial


def test_qasm_round_trip_preserves_the_unitary() -> None:
    circuit = Circuit(3, 3, name="roundtrip")
    circuit.add("H", [0])
    circuit.add("RX", [1], [0.75])
    circuit.add("CNOT", [2], controls=[1])
    circuit.add("SWAP", [0, 2])
    circuit.measure(0, 0)

    qasm = circuit.to_qasm()
    assert "OPENQASM" in qasm
    assert "qreg q[3]" in qasm
    assert "creg c[3]" in qasm
    assert "measure" in qasm

    restored = from_qasm(qasm)
    assert restored.num_qubits == circuit.num_qubits
    assert restored.num_clbits == circuit.num_clbits
    assert len(restored.operations) == len(circuit.operations)
    gates_only = Circuit(3)
    for op in circuit.operations:
        if op.kind == "gate":
            gates_only.add(op.name, op.targets, op.params, controls=op.controls)
    restored_gates = Circuit(3)
    for op in restored.operations:
        if op.kind == "gate":
            restored_gates.add(op.name, op.targets, op.params, controls=op.controls)
    assert unitary_distance(gates_only.to_unitary(), restored_gates.to_unitary()) < 1e-12


def test_circuit_document_round_trip() -> None:
    circuit = Circuit(2, 2, name="doc")
    circuit.add("H", [0])
    circuit.add("CNOT", [1], controls=[0])
    circuit.measure_all()
    again = Circuit.from_dict(circuit.to_dict())
    assert again.name == circuit.name
    assert again.num_clbits == circuit.num_clbits
    assert [op.to_dict()["name"] for op in again.operations] == [op.to_dict()["name"] for op in circuit.operations]
    assert unitary_distance(again.to_unitary(), circuit.to_unitary()) < 1e-12


def test_diagram_shows_every_wire_and_gate() -> None:
    circuit = Circuit(3, 3, name="diagram")
    circuit.add("H", [0])
    circuit.add("CNOT", [2], controls=[0])
    circuit.measure_all()
    diagram = circuit.diagram()
    assert "q0" in diagram and "q2" in diagram
    assert "H" in diagram
    assert "M" in diagram


def test_unknown_gate_and_out_of_range_qubit_are_rejected() -> None:
    circuit = Circuit(2)
    with pytest.raises(KeyError):
        circuit.add("NOT_A_GATE", [0])
    with pytest.raises((IndexError, ValueError)):
        circuit.add("X", [5])
    with pytest.raises((ValueError, KeyError)):
        circuit.add("CNOT", [0])  # missing a target
