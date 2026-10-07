"""The "What if?" engine.

The question a researcher actually asks is counterfactual: *what happens if I
remove this gate, raise the noise, add a qubit, swap H for Ry, optimize it?*
QScope answers it by running both variants with everything else held fixed and
reporting the measured difference — never by asserting what "would" happen.

Every modification is expressed as a small, explicit delta:

    {"kind": "remove_gate", "index": 4}
    {"kind": "replace_gate", "index": 2, "gate": "RY", "params": [1.5707963]}
    {"kind": "insert_gate", "gate": "H", "targets": [0], "at": 3}
    {"kind": "add_qubit", "count": 1}
    {"kind": "set_noise", "strength": 0.05}         # scale every channel
    {"kind": "set_shots", "shots": 8192}
    {"kind": "optimize", "level": "standard"}
    {"kind": "set_backend", "backend": "density_matrix"}

The result reports the delta in cost, distribution distance, fidelity, purity,
entropy, and a plain-language verdict derived from those numbers.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Sequence

from qscope.analysis.fidelity import total_variation
from qscope.analysis.metrics import circuit_metrics
from qscope.circuit.circuit import Circuit, Operation
from qscope.optimizer.optimizer import optimise
from qscope.simulator.execution import RunOptions
from qscope.simulator.noise import NoiseChannel, NoiseModel
from qscope.simulator.simulator import run_circuit

MODIFICATIONS = (
    "remove_gate",
    "replace_gate",
    "insert_gate",
    "add_qubit",
    "remove_qubit",
    "set_noise",
    "set_shots",
    "set_backend",
    "optimize",
)


@dataclass
class WhatIfVariant:
    """One counterfactual configuration."""

    label: str
    kind: str
    detail: dict[str, Any]
    circuit: Circuit
    shots: int
    backend: str
    noise: NoiseModel


@dataclass
class WhatIfResult:
    """Baseline vs variant, everything measured."""

    question: str
    baseline: dict[str, Any]
    variant: dict[str, Any]
    deltas: dict[str, Any]
    verdict: list[str]
    observations: list[str]
    seconds: float
    warnings: list[str] = field(default_factory=list)
    limitation: str = (
        "Both sides are simulations run with the same seed and shot count. A difference is a "
        "property of this model, not evidence about hardware."
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "baseline": self.baseline,
            "variant": self.variant,
            "deltas": self.deltas,
            "verdict": self.verdict,
            "observations": self.observations,
            "seconds": self.seconds,
            "warnings": self.warnings,
            "limitation": self.limitation,
        }

    def headline(self) -> str:
        return " ".join(self.verdict) or "no measurable difference"


def apply_modification(
    circuit: Circuit,
    modification: dict[str, Any],
) -> tuple[Circuit, str, dict[str, Any]]:
    """Return ``(new_circuit, label, detail)`` for one explicit modification."""
    kind = str(modification.get("kind", "")).strip()
    if kind not in MODIFICATIONS:
        raise ValueError(f"unknown modification {kind!r}; known: {', '.join(MODIFICATIONS)}")
    working = circuit.copy()
    detail = dict(modification)

    if kind == "remove_gate":
        index = int(modification["index"])
        if not 0 <= index < len(working.operations):
            raise IndexError(f"operation index {index} out of range (0..{len(working.operations) - 1})")
        removed = working.operations[index].display
        del working.operations[index]
        return working, f"remove {removed} at #{index}", detail

    if kind == "replace_gate":
        index = int(modification["index"])
        if not 0 <= index < len(working.operations):
            raise IndexError(f"operation index {index} out of range (0..{len(working.operations) - 1})")
        original = working.operations[index]
        if original.kind != "gate":
            raise ValueError(f"operation #{index} is {original.kind}, not a gate; replace_gate only edits gates")
        del working.operations[index]
        try:
            replacement = working.add(
                str(modification.get("gate", original.name)),
                list(modification.get("targets") or original.targets),
                [float(p) for p in modification.get("params", original.params)],
                controls=list(modification.get("controls", original.controls)),
                at=index,
            )
        except Exception:
            working.operations.insert(index, original)  # leave the circuit untouched on failure
            raise
        return working, f"replace {original.display} with {replacement.display}", detail

    if kind == "insert_gate":
        at = modification.get("at")
        index = max(0, min(int(at) if at is not None else len(working.operations), len(working.operations)))
        op = working.add(
            str(modification["gate"]),
            [int(t) for t in modification.get("targets", [0])],
            [float(p) for p in modification.get("params", [])],
            controls=[int(c) for c in modification.get("controls", [])],
            at=index,
        )
        return working, f"insert {op.display} at #{index}", detail

    if kind == "add_qubit":
        count = int(modification.get("count", 1))
        if count < 1:
            raise ValueError("count must be at least 1")
        grown = Circuit(
            circuit.num_qubits + count,
            circuit.num_clbits,
            name=circuit.name,
            description=circuit.description,
            metadata={**circuit.metadata, "what_if": f"added {count} qubit(s)"},
        )
        for op in circuit.operations:
            grown.append(op.copy())
        detail["added_qubits"] = [circuit.num_qubits + i for i in range(count)]
        return grown, f"add {count} qubit(s) in |0>", detail

    if kind == "remove_qubit":
        qubit = int(modification["qubit"])
        if not 0 <= qubit < circuit.num_qubits:
            raise IndexError(f"qubit {qubit} out of range (0..{circuit.num_qubits - 1})")
        if circuit.num_qubits <= 1:
            raise ValueError("cannot remove the last qubit")
        mapping = {old: new for new, old in enumerate(q for q in range(circuit.num_qubits) if q != qubit)}
        shrunk = Circuit(
            circuit.num_qubits - 1,
            circuit.num_clbits,
            name=circuit.name,
            description=circuit.description,
            metadata={**circuit.metadata, "what_if": f"removed qubit {qubit}"},
        )
        dropped: list[str] = []
        for op in circuit.operations:
            wires = list(op.targets) + list(op.controls)
            if qubit in wires:
                dropped.append(op.display)
                continue
            clone = op.copy()
            clone.targets = [mapping[t] for t in op.targets]
            clone.controls = [mapping[c] for c in op.controls]
            shrunk.append(clone)
        detail["dropped_operations"] = dropped
        return shrunk, f"remove qubit q{qubit} (dropping {len(dropped)} operation(s) that touched it)", detail

    # The remaining kinds change the execution, not the circuit.
    label = {
        "set_noise": f"set noise strength to {modification.get('strength')}",
        "set_shots": f"set shots to {modification.get('shots')}",
        "set_backend": f"run on the {modification.get('backend')} engine",
        "optimize": f"optimize at level {modification.get('level', 'standard')}",
    }[kind]
    return working, label, detail


def _scaled_noise(model: NoiseModel, strength: float) -> NoiseModel:
    strength = max(0.0, min(1.0, float(strength)))
    channels = []
    for channel in model.channels:
        scaled = {
            name: (strength if name in {"p", "gamma", "lambda"} else value)
            for name, value in channel.params.items()
        }
        channels.append(
            NoiseChannel(
                kind=channel.kind,
                params=scaled,
                scope=channel.scope,
                qubits=channel.qubits,
                after_gates=channel.after_gates,
                label=channel.label,
                approximate=channel.approximate,
            )
        )
    return NoiseModel(
        name=f"{model.name} @ strength {strength:g}" if model.channels else f"scaled noise @ {strength:g}",
        channels=channels,
        readout_error=strength * (model.readout_error or 0.0),
        one_qubit_gate_error=0.0,
        two_qubit_gate_error=0.0,
        multi_qubit_gate_error=0.0,
        idle_error=0.0,
        description=f"Every channel probability scaled to {strength:g}.",
        calibrated=model.calibrated,
    )


def what_if(
    circuit: Circuit,
    modification: dict[str, Any],
    *,
    question: str | None = None,
    shots: int = 2048,
    seed: int = 12345,
    backend: str = "auto",
    noise: NoiseModel | None = None,
    store: Any | None = None,
) -> WhatIfResult:
    """Run the baseline and the modified variant, and report the measured delta."""
    started = time.perf_counter()
    base_noise = noise or NoiseModel.ideal()
    variant_circuit, label, detail = apply_modification(circuit, modification)
    variant_shots = shots
    variant_backend = backend
    variant_noise = base_noise
    kind = modification["kind"]

    if kind == "set_shots":
        variant_shots = int(modification["shots"])
    elif kind == "set_backend":
        variant_backend = str(modification["backend"])
    elif kind == "set_noise":
        variant_noise = _scaled_noise(base_noise, float(modification.get("strength", 0.0)))
    elif kind == "optimize":
        optimization = optimise(variant_circuit, level=str(modification.get("level", "standard")))
        variant_circuit = optimization.optimized

    warnings: list[str] = []
    base_result = run_circuit(circuit, RunOptions(backend=backend, shots=shots, noise=base_noise, seed=seed))
    warnings.extend(base_result.warnings)
    variant_result = run_circuit(
        variant_circuit,
        RunOptions(backend=variant_backend, shots=variant_shots, noise=variant_noise, seed=seed),
    )
    warnings.extend(variant_result.warnings)

    base_resources = circuit_metrics(circuit)
    variant_resources = circuit_metrics(variant_circuit)

    def summarise(result: Any, resources: dict[str, Any], bench: Circuit, model: NoiseModel, shot_count: int) -> dict[str, Any]:
        metrics = result.metrics or {}
        return {
            "label": bench.name,
            "circuit": {
                "qubits": bench.num_qubits,
                "gates": resources["gates"],
                "depth": resources["depth"],
                "two_qubit_gates": resources["two_qubit_gates"],
                "t_count": resources["t_count"],
                "histogram": resources["histogram"],
            },
            "shots": shot_count,
            "backend": result.backend,
            "mode": result.mode,
            "noise_model": model.name,
            "counts": result.counts,
            "probabilities": result.ideal_probabilities,
            "top_outcome": max(result.counts.items(), key=lambda kv: kv[1])[0] if result.counts else None,
            "dominant_basis": metrics.get("dominant_basis"),
            "dominant_probability": metrics.get("dominant_probability"),
            "fidelity_vs_ideal": result.fidelity_vs_ideal,
            "trace_distance_vs_ideal": result.trace_distance_vs_ideal,
            "purity": metrics.get("purity"),
            "entropy": metrics.get("entropy"),
            "entanglement_status": metrics.get("entanglement_status"),
            "max_concurrence": (metrics.get("entanglement") or {}).get("max_concurrence"),
            "runtime_seconds": result.timing.get("total_seconds"),
            "memory_mb": result.memory.get("state_mb"),
            "warnings": result.warnings,
        }

    baseline = summarise(base_result, base_resources, circuit, base_noise, shots)
    variant = summarise(variant_result, variant_resources, variant_circuit, variant_noise, variant_shots)

    distribution_distance = total_variation(base_result.sampled_probabilities, variant_result.sampled_probabilities)
    shape_distance = total_variation(
        base_result.ideal_probabilities, variant_result.ideal_probabilities
    ) if set(base_result.ideal_probabilities) or set(variant_result.ideal_probabilities) else 0.0

    def delta(key: str, *, baseline_key: str | None = None, variant_key: str | None = None) -> float | None:
        a = baseline[baseline_key or key]
        b = variant[variant_key or key]
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            return float(b) - float(a)
        return None

    deltas = {
        "qubits": variant["circuit"]["qubits"] - baseline["circuit"]["qubits"],
        "gates": variant["circuit"]["gates"] - baseline["circuit"]["gates"],
        "depth": variant["circuit"]["depth"] - baseline["circuit"]["depth"],
        "two_qubit_gates": variant["circuit"]["two_qubit_gates"] - baseline["circuit"]["two_qubit_gates"],
        "t_count": variant["circuit"]["t_count"] - baseline["circuit"]["t_count"],
        "shots": variant["shots"] - baseline["shots"],
        "runtime_seconds": delta("runtime_seconds"),
        "memory_mb": delta("memory_mb"),
        "fidelity_vs_ideal": delta("fidelity_vs_ideal"),
        "purity": delta("purity"),
        "entropy": delta("entropy"),
        "dominant_probability": delta("dominant_probability"),
        "max_concurrence": delta("max_concurrence"),
        "distribution_total_variation": distribution_distance,
        "distribution_shape_total_variation": shape_distance,
    }

    verdict: list[str] = []
    if deltas["gates"]:
        verdict.append(
            f"Gate count {'drops' if deltas['gates'] < 0 else 'grows'} by {abs(deltas['gates'])} "
            f"({baseline['circuit']['gates']} → {variant['circuit']['gates']})."
        )
    if deltas["two_qubit_gates"]:
        verdict.append(
            f"Two-qubit gates change by {deltas['two_qubit_gates']:+d} "
            f"({baseline['circuit']['two_qubit_gates']} → {variant['circuit']['two_qubit_gates']}) — "
            "the term that usually dominates hardware error."
        )
    if deltas["fidelity_vs_ideal"] is not None and abs(deltas["fidelity_vs_ideal"]) > 1e-9:
        verdict.append(
            f"Noisy-state fidelity changes by {deltas['fidelity_vs_ideal']:+.6f} "
            f"({baseline['fidelity_vs_ideal']:.6f} → {variant['fidelity_vs_ideal']:.6f})."
        )
    if deltas["purity"] is not None and abs(deltas["purity"]) > 1e-9:
        verdict.append(f"Purity changes by {deltas['purity']:+.6f}.")
    if shape_distance > 1e-9:
        verdict.append(
            f"The exact distribution changes by {shape_distance:.4f} (total variation): the modification "
            "altered the computation itself, not just its cost."
        )
    else:
        verdict.append("The exact output distribution is unchanged: this modification did not alter what the circuit computes.")
    if baseline["entanglement_status"] != variant["entanglement_status"]:
        verdict.append(
            f"Entanglement status changes: {baseline['entanglement_status']} → {variant['entanglement_status']}."
        )
    if abs(distribution_distance - shape_distance) > 0.05 and abs(deltas["shots"]) > 0:
        verdict.append(
            f"Sampling noise alone accounts for {distribution_distance - shape_distance:+.4f} of the measured "
            "distribution distance (shots changed, exact distribution did not)."
        )

    observations = [
        f"baseline: {baseline['circuit']['gates']} gates, depth {baseline['circuit']['depth']}, "
        f"{baseline['runtime_seconds']:.6f} s, top outcome |{baseline['top_outcome']}⟩",
        f"variant ({label}): {variant['circuit']['gates']} gates, depth {variant['circuit']['depth']}, "
        f"{variant['runtime_seconds']:.6f} s, top outcome |{variant['top_outcome']}⟩",
    ]
    if deltas["qubits"] and shape_distance == 0.0:
        observations.append(
            "the reported distribution covers only the qubits this circuit measures, so a change in the "
            "qubit count with no measured-wire change leaves the distribution identical"
        )
    if store is not None:
        try:
            for tag, result, bench in (("baseline", base_result, circuit), ("variant", variant_result, variant_circuit)):
                store.record_result(
                    name=f"what-if {tag}: {label}",
                    circuit=bench,
                    result=result,
                    tags=["what-if", tag],
                    metadata={"modification": detail},
                )
        except Exception as exc:  # storage must never break the analysis
            warnings.append(f"history storage skipped: {exc}")
    return WhatIfResult(
        question=question or f"What happens if I {label}?",
        baseline=baseline,
        variant=variant,
        deltas=deltas,
        verdict=verdict,
        observations=observations,
        seconds=time.perf_counter() - started,
        warnings=warnings,
    )


def experiment_what_if(
    outcome: Any,
    *,
    modification: dict[str, Any],
    next_value: Any | None = None,
) -> dict[str, Any]:
    """Extrapolate a *measured* trend from an experiment's own rows (no invention).

    For a sweep, this fits the recorded metric against the swept axis and reports
    the fitted value at the next point, together with the fit quality and the
    extrapolation distance — labelled as an extrapolation of measured data.
    """
    import numpy as np

    rows = list(outcome.rows)
    x_name = outcome.spec["axes"][0]["name"] if outcome.spec.get("axes") else None
    if len(rows) < 3 or x_name is None:
        return {
            "available": False,
            "reason": "need at least three points on one axis to fit a trend",
        }
    x = np.array([float(r.params[x_name]) for r in rows], dtype=float)
    out: dict[str, Any] = {"available": True, "axis": x_name, "fits": {}}
    target = float(next_value) if next_value is not None else float(x[-1] + (x[-1] - x[-2]))
    out["target"] = target
    out["measured_x"] = x.tolist()
    for key in ("success_probability", "fidelity_vs_ideal", "runtime_seconds", "gates", "depth"):
        y = np.array([getattr(r, key) if getattr(r, key) is not None else np.nan for r in rows], dtype=float)
        mask = ~np.isnan(y)
        if mask.sum() < 3:
            continue
        order = 1 if mask.sum() < 5 else 2
        coeffs = np.polyfit(x[mask], y[mask], order)
        predicted = float(np.polyval(coeffs, target))
        fitted = np.polyval(coeffs, x[mask])
        rms = float(np.sqrt(np.mean((fitted - y[mask]) ** 2)))
        out["fits"][key] = {
            "order": order,
            "predicted_at_target": predicted,
            "rms_residual": rms,
            "last_measured": float(y[mask][-1]),
            "measured_min": float(np.min(y[mask])),
            "measured_max": float(np.max(y[mask])),
        }
    out["note"] = (
        "These values are extrapolations of a polynomial fit to measured points, not measured "
        f"values. The fit residual is reported so you can judge whether the trend is trustworthy."
    )
    out["modification"] = modification
    return out


def what_if_catalog() -> list[dict[str, Any]]:
    """The modifications the UI can offer, with their JSON shape."""
    return [
        {"kind": "remove_gate", "label": "Remove a gate", "shape": {"kind": "remove_gate", "index": 0}},
        {"kind": "replace_gate", "label": "Replace a gate", "shape": {"kind": "replace_gate", "index": 0, "gate": "RY", "params": [1.5707963]}},
        {"kind": "insert_gate", "label": "Insert a gate", "shape": {"kind": "insert_gate", "gate": "H", "targets": [0], "at": 3}},
        {"kind": "add_qubit", "label": "Add a qubit", "shape": {"kind": "add_qubit", "count": 1}},
        {"kind": "remove_qubit", "label": "Remove a qubit", "shape": {"kind": "remove_qubit", "qubit": 0}},
        {"kind": "set_noise", "label": "Change noise strength", "shape": {"kind": "set_noise", "strength": 0.05}},
        {"kind": "set_shots", "label": "Change shot count", "shape": {"kind": "set_shots", "shots": 8192}},
        {"kind": "set_backend", "label": "Switch engine", "shape": {"kind": "set_backend", "backend": "density_matrix"}},
        {"kind": "optimize", "label": "Optimize the circuit", "shape": {"kind": "optimize", "level": "standard"}},
    ]


__all__ = [
    "MODIFICATIONS",
    "WhatIfResult",
    "WhatIfVariant",
    "apply_modification",
    "experiment_what_if",
    "what_if",
    "what_if_catalog",
]
