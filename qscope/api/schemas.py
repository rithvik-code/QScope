"""Request and response models for the QScope API.

Everything the API accepts is explicit and validated: a circuit can arrive as a
QScope JSON document, as OpenQASM 2.0, or as an algorithm name with arguments, and
a noise model can arrive as a named preset or as explicit channels.  Extra keys
are rejected so a typo in a client never silently does nothing.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Backend = Literal["auto", "statevector", "density_matrix", "trajectory"]


class CircuitSource(BaseModel):
    """How the caller supplies a circuit."""

    model_config = ConfigDict(extra="forbid")

    circuit: dict[str, Any] | None = Field(
        default=None, description="QScope circuit document (Circuit.to_dict())"
    )
    qasm: str | None = Field(default=None, description="OpenQASM 2.0 source")
    algorithm: str | None = Field(default=None, description="algorithm key from /api/meta/catalog")
    algorithm_kwargs: dict[str, Any] = Field(
        default_factory=dict, description="arguments passed to the algorithm factory"
    )
    num_qubits: int | None = Field(default=None, ge=1, le=32)
    num_clbits: int | None = Field(default=None, ge=0, le=32)
    name: str | None = None


class NoiseChannelSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str
    params: dict[str, float] = Field(default_factory=dict)
    scope: str = "gate"
    qubits: list[int] | None = None
    after_gates: list[str] | None = None
    label: str = ""
    approximate: bool = False


class NoiseSpec(BaseModel):
    """Either a named preset with parameters, or explicit channels."""

    model_config = ConfigDict(extra="forbid")

    name: str = "ideal"
    """Preset name: ideal, bit_flip, phase_flip, depolarizing, amplitude_damping,
    phase_damping, bit_phase_flip, thermal, amp_phase."""
    params: dict[str, float] = Field(default_factory=dict)
    channels: list[NoiseChannelSpec] = Field(default_factory=list)
    readout_error: float = Field(default=0.0, ge=0.0, le=0.5)
    one_qubit_gate_error: float = Field(default=0.0, ge=0.0, le=1.0)
    two_qubit_gate_error: float = Field(default=0.0, ge=0.0, le=1.0)
    multi_qubit_gate_error: float = Field(default=0.0, ge=0.0, le=1.0)
    idle_error: float = Field(default=0.0, ge=0.0, le=1.0)
    calibrated: bool = False
    description: str = ""
    scale: float | None = Field(
        default=None,
        description="If set, every channel probability and the readout error are scaled to this value.",
    )


class SimulateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: CircuitSource
    backend: Backend = "auto"
    shots: int = Field(default=2048, ge=1, le=1_000_000)
    seed: int | None = None
    noise: NoiseSpec = Field(default_factory=NoiseSpec)
    measure_all: bool = True
    compare_ideal: bool = True
    memory_budget_mb: float | None = Field(default=None, gt=0)
    max_qubits: int | None = Field(default=None, ge=1, le=32)
    store: bool = False
    include_state: bool = True
    label: str = ""


class PlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: CircuitSource
    backend: Backend = "auto"
    shots: int = Field(default=2048, ge=1, le=1_000_000)
    noise: NoiseSpec = Field(default_factory=NoiseSpec)
    memory_budget_mb: float | None = Field(default=None, gt=0)


class TraceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: CircuitSource
    depth: Literal["fast", "standard", "full"] = "standard"
    term_limit: int = Field(default=24, ge=1, le=256)
    max_steps: int | None = Field(default=None, ge=1, le=4000)
    analyze_last_only: bool = False


class OptimizeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: CircuitSource
    level: Literal["safe", "standard", "aggressive"] = "standard"
    verify: bool = True


class CompareRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    a: CircuitSource
    b: CircuitSource
    shots: int = Field(default=2048, ge=1, le=1_000_000)
    seed: int = 11
    noise: NoiseSpec = Field(default_factory=NoiseSpec)
    backend: Backend = "auto"


class HardwareRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: CircuitSource
    device: str = "linear_5"
    """:data:`qscope.hardware.topology.HARDWARE_PRESETS` key, or "custom" with a ``model``."""
    model: dict[str, Any] | None = None
    route: bool = True


class EvolutionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: CircuitSource
    generations: int = Field(default=6, ge=0, le=60)
    population: int = Field(default=8, ge=2, le=64)
    seed: int = 1234
    hardware: str | None = None
    target: str = "circuit"


class ExperimentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = "custom"
    name: str | None = None
    kind: Literal[
        "algorithm_scaling",
        "noise_sweep",
        "backend_comparison",
        "optimizer_comparison",
        "shots_convergence",
        "parameter_sweep",
        "custom",
    ] = "custom"
    algorithm: str | None = None
    axes: dict[str, list[Any]] = Field(
        default_factory=dict, description="{axis_name: [values]} for custom sweeps"
    )
    fixed: dict[str, Any] = Field(default_factory=dict)
    shots: int = Field(default=2048, ge=1, le=1_000_000)
    backend: Backend = "auto"
    noise: NoiseSpec = Field(default_factory=NoiseSpec)
    seed: int = 12345
    optimizer_level: Literal["safe", "standard", "aggressive"] | None = None
    store: bool = True
    max_combinations: int = Field(default=64, ge=1, le=512)
    notes: list[str] = Field(default_factory=list)


class BenchmarkRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["scaling", "backends", "throughput", "memory", "suite", "external"] = "scaling"
    qubits: list[int] = Field(default_factory=lambda: [4, 8, 10], max_length=12)
    depth: int = Field(default=8, ge=1, le=64)
    shots: int = Field(default=1024, ge=1, le=1_000_000)
    trials: int = Field(default=3, ge=1, le=20)
    backends: list[Backend] = Field(default_factory=lambda: ["statevector"])
    seed: int = 7


class WhatIfRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: CircuitSource
    modification: dict[str, Any]
    shots: int = Field(default=2048, ge=1, le=1_000_000)
    seed: int = 12345
    backend: Backend = "auto"
    noise: NoiseSpec = Field(default_factory=NoiseSpec)
    store: bool = False


class ReportRequest(BaseModel):
    """Generate a report. The payload carries the objects to report on."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["simulation", "experiment", "optimization", "trace", "comparison", "evolution", "hardware"]
    title: str | None = None
    objective: str | None = None
    save: bool = True
    payload: dict[str, Any] = Field(default_factory=dict)


class AIRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=2000)
    use_llm: bool = False
    source: CircuitSource | None = None
    simulate: SimulateRequest | None = None
    trace: TraceRequest | None = None
    optimize: OptimizeRequest | None = None
    experiment_ids: list[str] = Field(default_factory=list, max_length=8)
    hardware: HardwareRequest | None = None


class BatchSimulateRequest(BaseModel):
    """Run several circuits with identical settings (used by comparison views)."""

    model_config = ConfigDict(extra="forbid")

    sources: list[CircuitSource] = Field(min_length=1, max_length=16)
    shots: int = Field(default=2048, ge=1, le=1_000_000)
    seed: int = 11
    backend: Backend = "auto"
    noise: NoiseSpec = Field(default_factory=NoiseSpec)


class MetricRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: CircuitSource
    keys: list[str] = Field(default_factory=list)
    include_entanglement: bool = True


class ValidateResponse(BaseModel):
    valid: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    resources: dict[str, Any] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    error: str
    detail: str = ""
    hint: str = ""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GateDefinition(BaseModel):
    name: str
    num_qubits: int
    params: list[str]
    category: str = ""
    description: str = ""
    self_inverse: bool = False
    diagonal: bool = False


class CircuitDocument(_Strict):
    """A circuit along with its resources, QASM and diagram (the editor's shape)."""

    format: str = "qscope-circuit"
    version: str = "1.0"
    name: str
    num_qubits: int
    num_clbits: int
    operations: list[dict[str, Any]]
    resources: dict[str, Any]
    diagram: str = ""
    qasm: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class SimulationResponse(_Strict):
    """A run plus the circuit it ran and the plan that chose the engine."""

    result: dict[str, Any]
    circuit: CircuitDocument
    plan: dict[str, Any]
    experiment_id: str | None = None


class HealthResponse(_Strict):
    status: str
    version: str
    python: str
    numpy: str
    database: str
    database_ok: bool
    experiments_stored: int
    reports_dir: str
    llm_configured: bool
    offline: bool = True
