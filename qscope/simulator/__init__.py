"""Simulation layer: backends, noise models, planning and execution."""

from __future__ import annotations

from qscope.simulator.execution import (
    BACKENDS,
    MEMORY_BUDGET_ENV,
    BackendSpec,
    ExecutionPlan,
    RunOptions,
    backend_catalog,
    choose_backend,
    describe_bytes,
    memory_budget_bytes,
    plan_execution,
    safe_max_qubits,
    scaling_table,
)
from qscope.simulator.noise import (
    KRAUS_BUILDERS,
    NoiseChannel,
    NoiseModel,
    build_kraus,
    combine_models,
    noise_model_catalog,
)
from qscope.simulator.simulator import (
    MODE_HARDWARE,
    MODE_IDEAL,
    MODE_NOISY,
    SimulationError,
    SimulationResult,
    ideal_state_of,
    measured_qubits_of,
    run_circuit,
    run_unitary,
    simulate_shot,
)

__all__ = [
    "BACKENDS",
    "KRAUS_BUILDERS",
    "MODE_HARDWARE",
    "MODE_IDEAL",
    "MODE_NOISY",
    "BackendSpec",
    "ExecutionPlan",
    "NoiseChannel",
    "NoiseModel",
    "RunOptions",
    "SimulationError",
    "SimulationResult",
    "backend_catalog",
    "build_kraus",
    "choose_backend",
    "combine_models",
    "describe_bytes",
    "ideal_state_of",
    "measured_qubits_of",
    "memory_budget_bytes",
    "noise_model_catalog",
    "plan_execution",
    "run_circuit",
    "run_unitary",
    "safe_max_qubits",
    "scaling_table",
    "simulate_shot",
]
