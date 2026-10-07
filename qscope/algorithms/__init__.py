"""Algorithm laboratory: standard algorithms as first-class QScope experiments."""

from __future__ import annotations

from qscope.algorithms.library import (
    ALGORITHMS,
    AlgorithmSpec,
    algorithm_catalog,
    bell_state,
    bernstein_vazirani,
    build_algorithm,
    deutsch_jozsa,
    evaluate_maxcut,
    evaluate_maxcut_counts,
    expectation_value,
    ghz_state,
    grover,
    grover_success_probability,
    ising_hamiltonian,
    qaoa_maxcut,
    qft,
    quantum_phase_estimation,
    teleportation,
    vqe_ansatz,
)

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
