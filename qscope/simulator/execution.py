"""Execution planning: backend selection, memory estimation and guard rails.

The single most important fact about classical quantum simulation is that state
size grows exponentially:

* state vector — ``2^n`` complex amplitudes  (16 bytes each)
* density matrix — ``2^n x 2^n`` complex entries (``4^n * 16`` bytes)

QScope refuses to pretend otherwise.  Before a run it estimates the footprint,
compares it against a configurable budget, and either proceeds, warns, or
refuses with an actionable message.  Nothing is silently down-cast or chunked.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from qscope.circuit.circuit import Circuit
from qscope.simulator.noise import NoiseModel

BYTES_PER_AMPLITUDE = 16  # complex128
"""Bytes per complex amplitude."""

DEFAULT_BUDGET_MB = 4096.0
"""Fallback memory budget when total system memory cannot be read."""

STATEVECTOR_WORKING_COPIES = 3
DENSITY_WORKING_COPIES = 3
"""Peak working-set multiplier during a gate application (state + temporaries)."""


@dataclass(frozen=True)
class BackendSpec:
    """A simulation representation QScope can execute a circuit on."""

    key: str
    label: str
    representation: str
    exact: bool
    supports_noise: bool
    supports_midcircuit_measurement: bool
    per_qubit_bytes: Any
    max_practical_qubits: int
    description: str
    tradeoff: str

    def estimate_bytes(self, num_qubits: int, *, peak: bool = False) -> int:
        base = int(self.per_qubit_bytes(num_qubits))
        return base * (3 if peak else 1)


def _sv_bytes(n: int) -> int:
    return BYTES_PER_AMPLITUDE * (2**n)


def _dm_bytes(n: int) -> int:
    return BYTES_PER_AMPLITUDE * (4**n)


BACKENDS: dict[str, BackendSpec] = {
    "statevector": BackendSpec(
        key="statevector",
        label="State vector",
        representation="statevector",
        exact=True,
        supports_noise=False,
        supports_midcircuit_measurement=True,
        per_qubit_bytes=_sv_bytes,
        max_practical_qubits=27,
        description="Exact pure-state evolution. 2^n complex amplitudes.",
        tradeoff="Exact and fast, but cannot represent a mixed state.",
    ),
    "density_matrix": BackendSpec(
        key="density_matrix",
        label="Density matrix",
        representation="density_matrix",
        exact=True,
        supports_noise=True,
        supports_midcircuit_measurement=True,
        per_qubit_bytes=_dm_bytes,
        max_practical_qubits=13,
        description="Exact mixed-state evolution. 2^n x 2^n complex matrix.",
        tradeoff="The only exact way to track mixedness; squared memory cost.",
    ),
    "trajectory": BackendSpec(
        key="trajectory",
        label="Quantum trajectories (Monte Carlo)",
        representation="statevector",
        exact=False,
        supports_noise=True,
        supports_midcircuit_measurement=True,
        per_qubit_bytes=_sv_bytes,
        max_practical_qubits=27,
        description=(
            "Samples one Kraus branch per noise event, per shot, on a state vector. "
            "Unbiased in the ensemble; statistical error ~1/sqrt(shots)."
        ),
        tradeoff="Cheap and scalable, but a single trajectory is not the exact state.",
    ),
}


@dataclass
class RunOptions:
    """Everything that controls a single execution."""

    backend: str = "auto"
    shots: int = 1024
    noise: NoiseModel = field(default_factory=NoiseModel.ideal)
    seed: int | None = None
    measure_all: bool = True
    compare_ideal: bool = True
    keep_memory: bool = True
    store_state: bool = True
    max_qubits: int | None = None
    memory_budget_mb: float | None = None
    collect_trace: bool = False
    apply_readout_error: bool = True
    label: str = ""
    algorithm: str = ""
    optimizer: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "backend": self.backend,
            "shots": self.shots,
            "noise": self.noise.to_dict(),
            "seed": self.seed,
            "measure_all": self.measure_all,
            "compare_ideal": self.compare_ideal,
            "keep_memory": self.keep_memory,
            "store_state": self.store_state,
            "max_qubits": self.max_qubits,
            "memory_budget_mb": self.memory_budget_mb,
            "collect_trace": self.collect_trace,
            "apply_readout_error": self.apply_readout_error,
            "label": self.label,
            "algorithm": self.algorithm,
            "optimizer": self.optimizer,
            "metadata": dict(self.metadata),
        }


@dataclass
class ExecutionPlan:
    """The decision plus everything the UI needs to explain it."""

    backend: str
    representation: str
    exact: bool
    num_qubits: int
    shots: int
    estimated_bytes: int
    estimated_peak_bytes: int
    budget_bytes: int
    safe_max_qubits: int
    blocked: bool = False
    warnings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    auto_selected: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "backend": self.backend,
            "backend_label": BACKENDS[self.backend].label,
            "representation": self.representation,
            "exact": self.exact,
            "num_qubits": self.num_qubits,
            "shots": self.shots,
            "estimated_bytes": self.estimated_bytes,
            "estimated_peak_bytes": self.estimated_peak_bytes,
            "estimated_mb": self.estimated_bytes / 1e6,
            "estimated_peak_mb": self.estimated_peak_bytes / 1e6,
            "budget_mb": self.budget_bytes / 1e6,
            "safe_max_qubits": self.safe_max_qubits,
            "blocked": self.blocked,
            "warnings": self.warnings,
            "notes": self.notes,
            "auto_selected": self.auto_selected,
        }


MEMORY_BUDGET_ENV = "QSCOPE_MEMORY_MB"
# The older, longer name is still honoured so an existing environment keeps working.
MEMORY_BUDGET_ENV_ALIASES = ("QSCOPE_MEMORY_MB", "QSCOPE_MEMORY_BUDGET_MB")


def memory_budget_bytes(explicit_mb: float | None = None) -> int:
    """Memory QScope is willing to use for one simulation.

    Order of precedence: explicit value, ``QSCOPE_MEMORY_MB`` (alias
    ``QSCOPE_MEMORY_BUDGET_MB``), then 60 % of the memory currently available to the
    process.
    """
    if explicit_mb is not None:
        return int(explicit_mb * 1e6)
    env = next((os.environ[name] for name in MEMORY_BUDGET_ENV_ALIASES if os.environ.get(name)), None)
    if env:
        try:
            return int(float(env) * 1e6)
        except ValueError:
            pass
    try:
        import psutil

        return int(psutil.virtual_memory().available * 0.6)
    except Exception:
        return int(DEFAULT_BUDGET_MB * 1e6)


def describe_bytes(num_bytes: float) -> str:
    """Human-readable byte count."""
    value = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if abs(value) < 1000 or unit == "GB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1000
    return f"{value:.1f} GB"


def safe_max_qubits(backend: str, budget_bytes: int) -> int:
    """Largest qubit count whose *peak* footprint fits the budget."""
    spec = BACKENDS[backend]
    limit = 0
    for n in range(1, 33):
        if spec.estimate_bytes(n) > budget_bytes:
            break
        limit = n
    return min(limit, spec.max_practical_qubits)


def choose_backend(circuit: Circuit, options: RunOptions) -> tuple[str, bool]:
    """Pick a backend.  Returns ``(backend, auto_selected)``."""
    if options.backend != "auto":
        return options.backend, False
    n = circuit.num_qubits
    noisy = not options.noise.is_ideal()
    if not noisy:
        return "statevector", True
    # Exact mixed-state simulation when it fits, otherwise Monte-Carlo trajectories.
    budget = memory_budget_bytes(options.memory_budget_mb)
    if n <= safe_max_qubits("density_matrix", budget):
        return "density_matrix", True
    return "trajectory", True


def plan_execution(circuit: Circuit, options: RunOptions) -> ExecutionPlan:
    """Estimate resources and decide whether the run may proceed."""
    backend, auto = choose_backend(circuit, options)
    if backend not in BACKENDS:
        raise ValueError(f"unknown backend {backend!r}; available: {sorted(BACKENDS)}")
    spec = BACKENDS[backend]
    budget = memory_budget_bytes(options.memory_budget_mb)
    n = circuit.num_qubits
    warnings: list[str] = []
    notes: list[str] = []

    if options.noise.is_ideal() and backend == "trajectory":
        notes.append("Ideal noise model on the trajectory backend: results are exact samples.")
    if options.noise.is_ideal() and backend == "density_matrix":
        notes.append("Ideal run on the density-matrix backend: exact, but slower than a state vector.")
    if not options.noise.is_ideal() and backend == "trajectory":
        warnings.append(
            "Monte-Carlo trajectories are APPROXIMATE for a single run: per-shot sampling "
            "error scales as 1/sqrt(shots). Increase shots, or use the density-matrix "
            "backend for exact mixed-state numbers."
        )
    if options.noise.readout_error > 0 and not options.apply_readout_error:
        warnings.append("Readout error is configured but disabled for this run.")

    estimated = spec.estimate_bytes(n)
    peak = spec.estimate_bytes(n, peak=True)

    if options.max_qubits is not None and n > options.max_qubits:
        return ExecutionPlan(
            backend, spec.representation, spec.exact, n, options.shots, estimated, peak, budget,
            safe_max_qubits(backend, budget), blocked=True,
            warnings=warnings + [
                f"Circuit has {n} qubits but this run sets max_qubits={options.max_qubits}."
            ],
        )

    if peak > budget:
        return ExecutionPlan(
            backend, spec.representation, spec.exact, n, options.shots, estimated, peak, budget,
            safe_max_qubits(backend, budget), blocked=True,
            warnings=warnings + [
                f"{spec.label} needs about {describe_bytes(peak)} of working memory for {n} "
                f"qubits, above the {describe_bytes(budget)} budget. Reduce the qubit count, "
                f"raise {MEMORY_BUDGET_ENV}, or switch backend (safe maximum: "
                f"{safe_max_qubits(backend, budget)} qubits)."
            ],
        )

    if peak > budget * 0.6:
        warnings.append(
            f"Close to the memory limit: about {describe_bytes(peak)} of a "
            f"{describe_bytes(budget)} budget."
        )
    if n >= 24 and backend != "density_matrix":
        warnings.append(
            f"{n} qubits means {2 ** n:,} amplitudes; each gate application is already "
            "seconds, not milliseconds."
        )
    if circuit.has_mid_circuit_measurement() or circuit.has_classical_control():
        if options.shots > 2000:
            warnings.append(
                "Mid-circuit measurement or classical feedback forces a per-shot simulation; "
                f"{options.shots} shots will be slow. Reduce shots for exploration."
            )
        notes.append(
            "Classical feedback is simulated shot-by-shot, so each shot is a genuine "
            "conditional run rather than a marginal resampling."
        )
    if backend == "density_matrix" and spec.max_practical_qubits - n <= 1:
        warnings.append(
            f"Density matrices grow as 4^n: {n} qubits already needs "
            f"{describe_bytes(estimated)}."
        )
    if not spec.supports_noise and not options.noise.is_ideal():
        warnings.append(f"{spec.label} cannot represent noise; the noise model was ignored.")

    return ExecutionPlan(
        backend, spec.representation, spec.exact, n, options.shots, estimated, peak, budget,
        safe_max_qubits(backend, budget), blocked=False, warnings=warnings, notes=notes,
        auto_selected=auto,
    )


def scaling_table(
    backend: str = "statevector",
    qubits: list[int] | None = None,
    budget_mb: float | None = None,
) -> list[dict[str, Any]]:
    """Memory/limit table for the performance observatory."""
    budget = memory_budget_bytes(budget_mb)
    qubits = qubits or [5, 10, 15, 20, 24, 28, 30]
    rows: list[dict[str, Any]] = []
    for n in qubits:
        spec = BACKENDS[backend]
        size = spec.estimate_bytes(n)
        rows.append(
            {
                "qubits": n,
                "amplitudes": 2**n if backend != "density_matrix" else 4**n,
                "bytes": size,
                "mb": size / 1e6,
                "human": describe_bytes(size),
                "fits_budget": spec.estimate_bytes(n, peak=True) <= budget,
            }
        )
    return rows


def backend_catalog() -> list[dict[str, Any]]:
    """Serialisable backend metadata."""
    budget = memory_budget_bytes()
    return [
        {
            "key": spec.key,
            "label": spec.label,
            "representation": spec.representation,
            "exact": spec.exact,
            "supports_noise": spec.supports_noise,
            "supports_midcircuit_measurement": spec.supports_midcircuit_measurement,
            "max_practical_qubits": spec.max_practical_qubits,
            "safe_max_qubits": safe_max_qubits(spec.key, budget),
            "description": spec.description,
            "tradeoff": spec.tradeoff,
            "bytes_per_qubit_expression": "16 * 2^n" if spec.key != "density_matrix" else "16 * 4^n",
        }
        for spec in BACKENDS.values()
    ]


__all__ = [
    "BACKENDS",
    "BYTES_PER_AMPLITUDE",
    "BackendSpec",
    "ExecutionPlan",
    "RunOptions",
    "backend_catalog",
    "choose_backend",
    "describe_bytes",
    "memory_budget_bytes",
    "plan_execution",
    "safe_max_qubits",
    "scaling_table",
]
