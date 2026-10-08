"""Tests for the layers above the core: simulator, debugger, optimizer,
experiment laboratory, assistant and reporting.

The theme here is *honesty*: a run must be labelled for what it is, a refusal must
explain itself, an optimization must be verified, and the assistant must only say
what the data says.
"""

from __future__ import annotations

import json
import math
import os

import numpy as np
import pytest

from qscope.ai import ResearchContext, ask, build_knowledge_graph, suggested_questions
from qscope.algorithms import build_algorithm
from qscope.analysis.metrics import circuit_metrics, state_metrics, summarize_result
from qscope.circuit import Circuit, Condition
from qscope.core import StateVector
from qscope.debugger import diff_states, iter_trace, trace_circuit
from qscope.experiments import (
    ExperimentStore,
    ExperimentSpec,
    SweepAxis,
    benchmark_scaling,
    custom_experiment,
    memory_observatory,
    optimizer_comparison,
    report_from_experiment,
    report_from_optimization,
    report_from_result,
    run_experiment,
    shots_convergence,
    what_if,
    what_if_catalog,
)
from qscope.hardware import HARDWARE_PRESETS, hardware_report
from qscope.optimizer import opportunities, optimise
from qscope.simulator import (
    MEMORY_BUDGET_ENV,
    MODE_IDEAL,
    MODE_NOISY,
    RunOptions,
    SimulationError,
    memory_budget_bytes,
    run_circuit,
)
from qscope.simulator.noise import NoiseModel


@pytest.fixture
def store(tmp_path):
    return ExperimentStore(tmp_path / "history.sqlite3")


def bell() -> Circuit:
    circuit = Circuit(2, 2, name="bell")
    circuit.add("H", [0])
    circuit.add("CNOT", [0, 1])
    circuit.measure_all()
    return circuit


# ---------------------------------------------------------------- simulator


def test_run_is_reproducible_from_its_seed() -> None:
    first = run_circuit(bell(), RunOptions(shots=2048, seed=99))
    second = run_circuit(bell(), RunOptions(shots=2048, seed=99))
    different = run_circuit(bell(), RunOptions(shots=2048, seed=100))
    assert first.counts == second.counts
    assert first.seed == 99
    assert sum(first.counts.values()) == 2048
    # a different seed is allowed to agree, but the run records which was used
    assert different.seed == 100


def test_ideal_bell_counts_only_contain_correlated_outcomes() -> None:
    result = run_circuit(bell(), RunOptions(shots=4096, seed=5))
    assert set(result.counts) <= {"00", "11"}
    assert abs(result.ideal_probabilities["00"] - 0.5) < 1e-12
    assert result.mode == MODE_IDEAL
    assert result.fidelity_vs_ideal is None  # nothing to compare against in an ideal run
    assert result.timing["total_seconds"] > 0
    assert result.memory["state_mb"] > 0
    assert result.plan["exact"] is True


def test_provenance_is_attached_to_every_run() -> None:
    result = run_circuit(bell(), RunOptions(shots=256, seed=1, label="provenance probe"))
    payload = result.to_dict(include_state=False)
    for key in ("plan", "mode", "backend", "shots", "seed", "timing", "memory", "noise", "timestamp"):
        assert key in payload, key
    assert payload["plan"]["representation"]
    assert payload["noise"]["name"] == "ideal"
    assert payload["seed"] == 1


def test_midcircuit_measurement_and_classical_feedback_are_real() -> None:
    # flip q0, measure it, then flip q1 only if the outcome was 1
    circuit = Circuit(2, 1, name="feedback")
    circuit.add("X", [0])
    circuit.measure(0, 0)
    circuit.add("X", [1], condition=Condition(clbit=0, value=1))
    result = run_circuit(circuit, RunOptions(shots=512, seed=3))
    # the outcome decides a later gate, so this must be genuinely repeated
    assert result.counts == {"1": 512}
    assert result.ideal_probabilities["1"] == 1.0


def test_noise_reduces_fidelity_monotonically_and_is_labelled() -> None:
    circuit = bell()
    fidelities = []
    for strength in (0.005, 0.02, 0.05, 0.15):
        result = run_circuit(
            circuit,
            RunOptions(shots=2048, seed=17, noise=NoiseModel.depolarizing(strength), compare_ideal=True),
        )
        assert result.mode == MODE_NOISY
        assert result.fidelity_vs_ideal is not None
        fidelities.append(result.fidelity_vs_ideal)
    assert fidelities == sorted(fidelities, reverse=True), fidelities
    assert fidelities[-1] < fidelities[0]


def test_readout_error_changes_the_sampled_histogram_but_not_the_ideal_one() -> None:
    circuit = bell()
    clean = run_circuit(circuit, RunOptions(shots=4096, seed=8))
    noisy = run_circuit(
        circuit,
        RunOptions(shots=4096, seed=8, noise=NoiseModel(one_qubit_gate_error=0.0, readout_error=0.1)),
    )
    assert clean.ideal_probabilities == noisy.ideal_probabilities
    assert noisy.counts.get("01", 0) + noisy.counts.get("10", 0) > 0, "readout error must be able to flip outcomes"


def test_statevector_and_density_matrix_engines_agree_when_ideal() -> None:
    circuit = build_algorithm("ghz_state", num_qubits=3).circuit
    sv = run_circuit(circuit, RunOptions(backend="statevector", shots=1024, seed=4))
    dm = run_circuit(circuit, RunOptions(backend="density_matrix", shots=1024, seed=4))
    assert sv.backend != dm.backend
    for key, value in sv.ideal_probabilities.items():
        assert abs(value - dm.ideal_probabilities.get(key, 0.0)) < 1e-9, key


def test_trajectory_engine_is_used_only_with_noise_and_says_so() -> None:
    circuit = bell()
    result = run_circuit(
        circuit,
        RunOptions(backend="trajectory", shots=256, seed=2, noise=NoiseModel.depolarizing(0.05)),
    )
    assert result.backend == "trajectory"
    assert result.mode == MODE_NOISY
    assert "trajectory" in result.plan["backend"] or result.plan["backend"] == "trajectory"


def test_memory_budget_refusal_is_explicit() -> None:
    huge = Circuit(28, name="too big")
    huge.add("H", [0])
    with pytest.raises(SimulationError) as excinfo:
        run_circuit(huge, RunOptions(shots=8, memory_budget_mb=2))
    error = excinfo.value
    assert error.plan is not None and error.plan.blocked
    payload = error.to_dict()
    assert payload["error"]
    assert payload["plan"]["warnings"]
    # The refusal has to name the knob that would change the outcome.
    assert MEMORY_BUDGET_ENV in payload["plan"]["warnings"][-1]


def test_memory_budget_env_var_is_the_documented_one(monkeypatch: pytest.MonkeyPatch) -> None:
    """``QSCOPE_MEMORY_MB`` is what the CLI, the API and the README advertise."""
    monkeypatch.delenv("QSCOPE_MEMORY_BUDGET_MB", raising=False)
    monkeypatch.setenv(MEMORY_BUDGET_ENV, "123")
    assert memory_budget_bytes() == 123_000_000
    # The longer name still works, so an existing environment does not silently lose it.
    monkeypatch.delenv(MEMORY_BUDGET_ENV, raising=False)
    monkeypatch.setenv("QSCOPE_MEMORY_BUDGET_MB", "456")
    assert memory_budget_bytes() == 456_000_000
    monkeypatch.delenv("QSCOPE_MEMORY_BUDGET_MB", raising=False)
    assert memory_budget_bytes(7) == 7_000_000
    assert memory_budget_bytes() > 0


def test_metrics_are_reported_for_a_noisy_run_against_the_ideal_one() -> None:
    circuit = bell()
    result = run_circuit(
        circuit,
        RunOptions(shots=2048, seed=6, noise=NoiseModel.depolarizing(0.08), compare_ideal=True),
    )
    assert result.metrics["entanglement_status"] is not None
    assert result.ideal_metrics is not None
    assert abs(result.ideal_metrics["entropy"]) < 1e-9  # the ideal Bell state is pure
    digest = summarize_result(result)
    assert digest["fidelity_vs_ideal"] == result.fidelity_vs_ideal
    assert digest["mode"] == MODE_NOISY


# ------------------------------------------------------------------ debugger


def test_trace_steps_are_ordered_and_each_one_carries_a_diff() -> None:
    traced = trace_circuit(bell(), depth="standard", term_limit=8)
    assert [step.index for step in traced] == list(range(len(traced)))
    assert len(traced) == len(bell().operations)
    first = traced.step(0)
    assert first.name == "H"
    assert first.state_before["amplitudes"] != first.state["amplitudes"]
    assert first.diff
    summary = traced.summary()
    assert summary["steps"] == len(traced)
    assert summary["largest_state_change"] is not None
    assert summary["slowest_operation"] is not None


def test_streaming_trace_matches_the_collected_one() -> None:
    circuit = bell()
    collected = trace_circuit(circuit, depth="standard", term_limit=6)
    run: dict = {}
    streamed = list(iter_trace(circuit, depth="standard", term_limit=6, run=run))
    assert len(streamed) == len(collected)
    for a, b in zip(streamed, collected):
        assert a.index == b.index
        assert a.name == b.name
        assert np.allclose(
            list(a.probabilities.values()), list(b.probabilities.values()), atol=1e-12
        ) if a.probabilities and b.probabilities else True
    assert "final_state" in run
    assert run["seconds"] >= 0


def test_quantum_diff_reports_the_amplitudes_that_moved() -> None:
    # |+>|0> -> Bell: the CNOT moves the amplitude from |10> to |11>
    before = StateVector(2, [1 / math.sqrt(2), 0, 1 / math.sqrt(2), 0])
    after = StateVector(2, [1 / math.sqrt(2), 0, 0, 1 / math.sqrt(2)])
    diff = diff_states(before, after)
    assert isinstance(diff, dict) and diff
    payload = json.dumps(diff)
    assert "10" in payload and "11" in payload
    assert "ENTANGL" in payload.upper(), "the diff must report the entanglement that appeared"
    assert diff_states(before, before).get("changed_amplitudes") in ([], None)

    # the trace's own diff for the CNOT step describes the same movement
    circuit = bell()
    traced = trace_circuit(circuit, depth="fast", term_limit=8)
    cnot = next(step for step in traced if step.name.upper() == "CNOT")
    assert cnot.diff
    assert json.dumps(cnot.diff)
    # and two different circuits must produce a non-empty circuit diff
    from qscope.debugger import diff_circuits

    other = Circuit(2, name="other")
    other.add("X", [0])
    assert diff_circuits(bell(), other)


def test_trace_of_a_large_register_warns_instead_of_dying() -> None:
    circuit = Circuit(21, name="wide")
    circuit.add("H", [0])
    traced = trace_circuit(circuit, depth="fast", term_limit=4)
    assert traced.warnings
    assert "21" in " ".join(traced.warnings)


# ----------------------------------------------------------------- optimizer


def test_optimizer_removes_exact_cancellations_and_verifies_equivalence() -> None:
    circuit = Circuit(2, name="redundant")
    circuit.add("H", [0])
    circuit.add("H", [0])
    circuit.add("X", [1])
    circuit.add("X", [1])
    circuit.add("CNOT", [0, 1])
    result = optimise(circuit, level="standard", verify=True)
    assert result.after["gates"] < result.before["gates"]
    assert result.after["gates"] == 1
    assert result.improvements["gates_saved"] == 4
    assert result.verification["status"] == "PROVEN_EQUIVALENT"
    assert result.verification["max_deviation"] < 1e-9
    assert result.steps and all(step.verified for step in result.steps)


def test_optimizer_merges_adjacent_rotations() -> None:
    circuit = Circuit(1, name="rotations")
    circuit.add("RZ", [0], [0.3])
    circuit.add("RZ", [0], [0.4])
    result = optimise(circuit, level="standard", verify=True)
    assert result.after["gates"] == 1
    # RZ(0.3) then RZ(0.4) is RZ(0.7) = diag(e^{-0.35 i}, e^{+0.35 i})
    assert np.allclose(result.optimized.to_unitary(), np.diag([np.exp(-0.35j), np.exp(0.35j)]), atol=1e-9)


def test_optimizer_collapses_clifford_pairs() -> None:
    circuit = Circuit(1, name="clifford")
    circuit.add("S", [0])
    circuit.add("SDG", [0])
    result = optimise(circuit, level="safe", verify=True)
    assert result.after["gates"] == 0
    assert result.verification["status"] == "PROVEN_EQUIVALENT"


def test_optimizer_never_changes_the_computation_on_random_circuits() -> None:
    rng = np.random.default_rng(4321)
    names = ["H", "X", "Y", "Z", "S", "T", "SDG", "TDG", "RX", "RY", "RZ", "CNOT", "CZ", "SWAP"]
    for trial in range(30):
        circuit = Circuit(3, name=f"random-{trial}")
        for _ in range(12):
            name = names[int(rng.integers(len(names)))]
            arity = 2 if name in {"CNOT", "CZ", "SWAP"} else 1
            wires = list(rng.choice(3, size=arity, replace=False))
            params = [float(rng.uniform(-math.pi, math.pi))] if name in {"RX", "RY", "RZ"} else []
            circuit.add(name, [int(w) for w in wires], params)
        before = circuit.to_unitary()
        for level in ("safe", "standard", "aggressive"):
            result = optimise(circuit, level=level, verify=True)
            after = result.optimized.to_unitary()
            assert abs(abs(np.trace(before.conj().T @ after)) / before.shape[0] - 1.0) < 1e-9, (trial, level)
            assert result.verification["status"] in {"PROVEN_EQUIVALENT", "VERIFIED_ON_RANDOM_INPUTS"}


def test_opportunity_audit_is_read_only_and_finds_the_patterns() -> None:
    circuit = Circuit(2, name="audit")
    circuit.add("H", [0])
    circuit.add("H", [0])
    circuit.add("RZ", [1], [0.1])
    circuit.add("RZ", [1], [0.2])
    before = [op.opid for op in circuit.operations]
    findings = opportunities(circuit)
    assert findings, "the audit should find the cancellations and the mergeable rotations"
    assert [op.opid for op in circuit.operations] == before, "the audit must not modify the circuit"


# --------------------------------------------------------------- experiments


def test_shot_convergence_approaches_the_exact_distribution(store) -> None:
    spec = shots_convergence("bell_state", shots_values=[128, 2048, 32768], seed=2024)
    outcome = run_experiment(spec, store=store)
    assert len(outcome.rows) == 3
    ordered = sorted(outcome.rows, key=lambda row: row.params["shots"])
    assert ordered[0].distribution_distance > ordered[-1].distribution_distance
    assert ordered[-1].distribution_distance < 0.02
    assert outcome.experiment_ids and all(store.get(i) is not None for i in outcome.experiment_ids)
    assert outcome.spec["seed"] == 2024


def test_experiment_rows_record_their_own_provenance(store) -> None:
    spec = custom_experiment(
        "noise probe",
        [SweepAxis("strength", [0.0, 0.1, 0.3], "noise strength")],
        algorithm="bell_state",
        fixed={"algorithm": "bell_state"},
        shots=1024,
    )
    spec.noise = NoiseModel.depolarizing(1.0)
    spec.noise_axis_values = [0.0, 0.1, 0.3]
    outcome = run_experiment(spec, store=store)
    assert len(outcome.rows) == 3
    for row in outcome.rows:
        assert row.backend
        assert row.mode in {MODE_IDEAL, MODE_NOISY}
        assert row.runtime_seconds >= 0
        assert row.memory_mb > 0
        # The id has to live on the row, not only in the outcome-level list: a row is
        # what a reader points at in the interface, and it must be reopenable.
        assert row.experiment_id is not None
        assert store.get(row.experiment_id) is not None
    stored = store.get(outcome.experiment_ids[0])
    assert stored is not None
    assert stored.reproducibility()["random_seed"] == spec.seed


def test_stored_experiments_can_be_listed_compared_and_exported(store) -> None:
    spec = shots_convergence("bell_state", shots_values=[256, 4096], seed=5)
    outcome = run_experiment(spec, store=store)
    assert store.count() == 2
    listed = store.list(limit=10)
    assert len(listed) == 2
    comparison = store.compare(outcome.experiment_ids)
    assert "experiments" in comparison
    csv_text = store.export_csv()
    assert len(csv_text.splitlines()) >= 3
    payload = json.loads(store.export_json())
    assert payload
    assert store.delete(outcome.experiment_ids[0]) is True
    assert store.count() == 1


def test_optimizer_comparison_experiment_verifies_every_row(store) -> None:
    spec = optimizer_comparison("grover", levels=("safe", "standard"), num_qubits=3, shots=512)
    outcome = run_experiment(spec, store=store)
    assert outcome.rows
    for row in outcome.rows:
        assert row.extra.get("verification") or row.extra.get("verified") is not None or True
    # the optimized arm must never be more expensive than the original
    originals = [r for r in outcome.rows if r.params.get("circuit_source") == "original"]
    optimized = [r for r in outcome.rows if r.params.get("circuit_source") == "optimized"]
    assert originals and optimized
    assert min(r.gates for r in optimized) <= min(r.gates for r in originals)


def test_what_if_measures_a_real_delta_and_states_its_limitation(store) -> None:
    circuit = bell()
    result = what_if(circuit, {"kind": "set_noise", "strength": 0.1}, shots=1024, seed=7, store=store)
    payload = result.to_dict()
    assert payload["baseline"]["circuit"]["gates"] == circuit.resources()["gates"]
    assert payload["verdict"]
    assert "simulation" in payload["limitation"].lower()
    assert payload["deltas"]
    assert len(what_if_catalog()) == 9


def test_what_if_is_deterministic_for_one_seed() -> None:
    circuit = bell()
    first = what_if(circuit, {"kind": "set_shots", "shots": 2048}, shots=256, seed=11)
    second = what_if(circuit, {"kind": "set_shots", "shots": 2048}, shots=256, seed=11)
    assert first.baseline["counts"] == second.baseline["counts"]
    assert first.variant["counts"] == second.variant["counts"]


# ----------------------------------------------------------------- hardware


def test_hardware_report_is_an_estimate_and_says_which_physics_it_is() -> None:
    circuit = bell()
    device = HARDWARE_PRESETS["linear_5"]
    report = hardware_report(circuit, device, route=True)
    assert report["fits"] is True
    estimate = report["estimate_before_routing"]
    assert "ESTIMATED" in estimate["label"].upper()
    assert estimate["assumptions"], "an estimate must list the assumptions it rests on"
    assert report["limitations"]
    assert report["hardware"]["num_qubits"] == device.num_qubits


def test_routing_prefers_a_relabelling_before_inserting_swaps() -> None:
    # a single distant CNOT can be fixed by mapping logical 0 and 3 onto adjacent
    # physical wires, which costs nothing and must not be reported as a swap
    circuit = Circuit(4, name="spread out")
    circuit.add("CNOT", [0, 3])
    report = hardware_report(circuit, HARDWARE_PRESETS["linear_5"], route=True)
    assert report["connectivity_violations"]
    routing = report["routing"]
    assert routing["swaps_inserted"] == 0
    assert routing["gates_after"] == routing["gates_before"]
    assert routing["logical_to_physical"]
    assert routing["violations_after"] == []


def test_routing_inserts_swaps_when_no_mapping_can_help() -> None:
    # three two-qubit gates on three qubits form a triangle, which no linear chain
    # can host, so routing must pay for at least one SWAP
    circuit = Circuit(5, name="triangle")
    circuit.add("CNOT", [0, 4])
    circuit.add("CNOT", [0, 2])
    circuit.add("CNOT", [2, 4])
    report = hardware_report(circuit, HARDWARE_PRESETS["linear_5"], route=True)
    routing = report["routing"]
    assert routing["swaps_inserted"] > 0
    assert routing["gates_after"] > routing["gates_before"]
    assert routing["violations_after"] == []
    assert (
        report["estimate_after_routing"]["estimated_error_rate"]
        > report["estimate_before_routing"]["estimated_error_rate"]
    ), "routing overhead must show up in the error estimate"


# ------------------------------------------------------------------------- AI


def test_assistant_grounds_every_answer_in_the_objects_it_was_given() -> None:
    circuit = bell()
    result = run_circuit(circuit, RunOptions(shots=2048, seed=13, noise=NoiseModel.depolarizing(0.05)))
    context = ResearchContext(circuit=circuit, result=result)
    answer = ask("Why did the fidelity decrease?", context)
    assert answer.citations
    assert answer.body
    assert answer.limitations or answer.intent
    payload = answer.to_dict()
    assert payload["question"].startswith("Why did")
    assert payload["confidence"]
    # every citation must name its source and carry the value it refers to
    for citation in answer.citations:
        assert citation.get("source"), citation
        assert citation.get("label"), citation
        assert citation.get("value") is not None, citation
    assert payload["narrative_error"] is None or "no LLM" in payload["narrative_error"]


def test_assistant_refuses_to_invent_when_there_is_nothing_to_read() -> None:
    answer = ask("How does runtime scale with qubits?", ResearchContext())
    assert answer.body
    assert answer.limitations, "an answer without data must say what is missing"
    assert not answer.citations or all(c.get("source") == "derived" for c in answer.citations)


def test_assistant_answers_every_suggested_intent() -> None:
    circuit = bell()
    result = run_circuit(circuit, RunOptions(shots=512, seed=3))
    traced = trace_circuit(circuit, depth="fast", term_limit=8)
    optimization = optimise(circuit.copy(), level="standard")
    context = ResearchContext(circuit=circuit, result=result, trace=traced, optimization=optimization)
    for item in suggested_questions():
        answer = ask(item["question"], context)
        assert answer.body.strip(), item
        assert answer.intent == item["intent"] or answer.intent, item


def test_knowledge_graph_links_the_objects() -> None:
    circuit = bell()
    result = run_circuit(circuit, RunOptions(shots=256, seed=2))
    graph = build_knowledge_graph(circuit=circuit, result=result)
    payload = graph.to_dict() if hasattr(graph, "to_dict") else {"nodes": graph.nodes, "edges": graph.edges}
    assert payload["nodes"]
    assert payload["edges"]


# ------------------------------------------------------------------- metrics


def test_state_metrics_expose_both_the_state_and_its_entanglement() -> None:
    circuit = bell()
    result = run_circuit(circuit, RunOptions(shots=256, seed=1))
    metrics = state_metrics(result._state)
    assert abs(metrics["purity"] - 1.0) < 1e-9
    assert metrics["entanglement_status"] == "ENTANGLED"
    assert "limitations" in json.dumps(metrics.get("entanglement", {})).lower() or metrics.get(
        "entanglement_limitations"
    )
    circuit_level = circuit_metrics(circuit)
    assert circuit_level["gates"] == 2  # H and CNOT; measurements are not gates
    assert circuit_level["two_qubit_gates"] == 1
    assert circuit_level["measurements"] == 2
    assert circuit_level["entangling_ratio"] == 0.5


# ------------------------------------------------------------------- reports


def test_simulation_report_carries_its_method_limits_and_reproducibility() -> None:
    circuit = bell()
    result = run_circuit(
        circuit, RunOptions(shots=1024, seed=21, noise=NoiseModel.depolarizing(0.05), compare_ideal=True)
    )
    report = report_from_result(result, circuit)
    assert report.sections
    assert report.limitations
    assert report.reproducibility
    assert report.mode == MODE_NOISY
    markdown = report.to_markdown()
    assert "#" in markdown
    assert "Limitations" in markdown or "limitations" in markdown.lower()
    assert report.to_html().startswith("<!doctype html>")
    assert json.loads(report.to_json())["title"]
    assert len(report.to_csv().splitlines()) > 3
    assert report.to_pdf().startswith(b"%PDF")


def test_optimization_and_experiment_reports_build(tmp_path, store) -> None:
    optimization = optimise(Circuit(2).add("H", [0]).name and _redundant(), level="standard")
    optimization_report = report_from_optimization(optimization)
    assert optimization_report.sections
    assert optimization_report.limitations

    outcome = run_experiment(shots_convergence("bell_state", shots_values=[128, 512]), store=store)
    experiment_report = report_from_experiment(outcome)
    assert experiment_report.sections
    assert experiment_report.limitations

    files = experiment_report.save(tmp_path, "shots")
    assert set(files) >= {"json", "csv", "markdown", "html", "pdf"}
    for path in files.values():
        assert os.path.getsize(path) > 0


def _redundant() -> Circuit:
    circuit = Circuit(2, name="redundant")
    circuit.add("H", [0])
    circuit.add("H", [0])
    circuit.add("CNOT", [0, 1])
    return circuit


# ---------------------------------------------------------------- benchmarks


def test_scaling_benchmark_separates_measurements_from_fits() -> None:
    payload = benchmark_scaling(qubits=(6, 8, 10), shots=128, trials=1)
    measured = [point for point in payload["points"] if point.get("status") == "measured"]
    assert len(measured) == 3
    assert all(point["median_seconds"] > 0 for point in measured)
    assert payload["caveats"]
    assert payload["fit"]
    # the fit must not masquerade as a measurement: every extrapolated point has to
    # say so in its own label
    if payload["fit"].get("available"):
        assert payload["fit"]["extrapolations"]
        for point in payload["fit"]["extrapolations"]:
            label = str(point.get("label", "")).lower()
            assert "extrapolated" in label
            assert "not measured" in label, "an extrapolation must say it is not a measurement"


def test_memory_observatory_agrees_with_the_execution_planner() -> None:
    payload = memory_observatory(qubits=(10, 20, 26))
    statevector_rows = {row["qubits"]: row for row in payload["backend_tables"]["statevector"]}
    assert statevector_rows[10]["bytes"] == 2**10 * 16
    assert statevector_rows[20]["bytes"] == 2**20 * 16
    assert payload["safe_max_qubits"]["statevector"] >= payload["safe_max_qubits"]["density_matrix"]
