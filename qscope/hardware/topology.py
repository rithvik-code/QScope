"""Hardware-aware simulation.

Three separate things live here, and QScope keeps them separate on purpose:

1. **Topology** — which qubits can interact.  A coupling map with a BFS distance
   matrix.
2. **Routing** — turning a logical circuit into one that respects the topology,
   inserting SWAPs where needed, and reporting exactly how many were required.
3. **Estimation** — a first-order success-probability estimate from gate errors,
   durations, T1/T2 and readout error.

The estimate is a *model*, not a measurement: it is labelled
``ESTIMATED (hardware model)`` everywhere and never presented as a hardware
result.  QScope will not claim a hardware fidelity it did not measure.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from qscope.circuit.circuit import Circuit, Operation
from qscope.core.tensor import COMPLEX

DEFAULT_ONE_QUBIT_GATES = ("I", "X", "Y", "Z", "H", "S", "SDG", "T", "TDG", "SX", "RX", "RY", "RZ", "P", "U2", "U3")
DEFAULT_TWO_QUBIT_GATES = ("CNOT", "CX", "CZ", "CY", "CH", "ISWAP", "RZZ", "RXX", "RYY", "RZX")


@dataclass
class CouplingMap:
    """Which qubit pairs can host a two-qubit gate."""

    num_qubits: int
    edges: list[tuple[int, int]]

    def __post_init__(self) -> None:
        self.edges = [tuple(sorted((int(a), int(b)))) for a, b in self.edges]
        for a, b in self.edges:
            if a == b or a < 0 or b < 0 or a >= self.num_qubits or b >= self.num_qubits:
                raise ValueError(f"invalid coupling edge {(a, b)} for {self.num_qubits} qubits")
        self._adjacency: dict[int, set[int]] = {q: set() for q in range(self.num_qubits)}
        for a, b in self.edges:
            self._adjacency[a].add(b)
            self._adjacency[b].add(a)

    @classmethod
    def linear(cls, num_qubits: int) -> "CouplingMap":
        return cls(num_qubits, [(i, i + 1) for i in range(num_qubits - 1)])

    @classmethod
    def ring(cls, num_qubits: int) -> "CouplingMap":
        edges = [(i, i + 1) for i in range(num_qubits - 1)]
        if num_qubits > 2:
            edges.append((num_qubits - 1, 0))
        return cls(num_qubits, edges)

    @classmethod
    def grid(cls, rows: int, cols: int) -> "CouplingMap":
        edges: list[tuple[int, int]] = []
        for r in range(rows):
            for c in range(cols):
                q = r * cols + c
                if c + 1 < cols:
                    edges.append((q, q + 1))
                if r + 1 < rows:
                    edges.append((q, q + cols))
        return cls(rows * cols, edges)

    @classmethod
    def all_to_all(cls, num_qubits: int) -> "CouplingMap":
        return cls(num_qubits, [(i, j) for i in range(num_qubits) for j in range(i + 1, num_qubits)])

    @classmethod
    def from_edges(cls, num_qubits: int, edges: Iterable[Sequence[int]]) -> "CouplingMap":
        return cls(num_qubits, [(int(a), int(b)) for a, b in edges])

    # ------------------------------------------------------------------ graph

    def neighbours(self, qubit: int) -> list[int]:
        return sorted(self._adjacency.get(qubit, set()))

    def is_connected(self, a: int, b: int) -> bool:
        return b in self._adjacency.get(a, set())

    def is_fully_connected(self) -> bool:
        """Whether the whole device is reachable (needed before routing is possible)."""
        if self.num_qubits == 0:
            return True
        seen = {0}
        queue = deque([0])
        while queue:
            q = queue.popleft()
            for nb in self._adjacency.get(q, set()):
                if nb not in seen:
                    seen.add(nb)
                    queue.append(nb)
        return len(seen) == self.num_qubits

    def distance(self, a: int, b: int) -> int:
        """Shortest path length in edges (``inf`` when disconnected)."""
        if a == b:
            return 0
        seen = {a}
        queue: deque[tuple[int, int]] = deque([(a, 0)])
        while queue:
            node, dist = queue.popleft()
            for nb in self._adjacency.get(node, set()):
                if nb == b:
                    return dist + 1
                if nb not in seen:
                    seen.add(nb)
                    queue.append((nb, dist + 1))
        return math.inf

    def shortest_path(self, a: int, b: int) -> list[int]:
        """Qubits along a shortest path from ``a`` to ``b`` (inclusive)."""
        if a == b:
            return [a]
        previous: dict[int, int] = {a: a}
        queue = deque([a])
        while queue:
            node = queue.popleft()
            for nb in self._adjacency.get(node, set()):
                if nb not in previous:
                    previous[nb] = node
                    if nb == b:
                        path = [b]
                        while path[-1] != a:
                            path.append(previous[path[-1]])
                        return list(reversed(path))
                    queue.append(nb)
        return []

    def distance_matrix(self) -> list[list[float]]:
        return [[self.distance(i, j) for j in range(self.num_qubits)] for i in range(self.num_qubits)]

    def diameter(self) -> float:
        matrix = self.distance_matrix()
        finite = [d for row in matrix for d in row if d != math.inf]
        return max(finite) if finite else 0.0

    def interacting_pairs(self) -> list[tuple[int, int]]:
        return list(self.edges)

    def to_dict(self) -> dict[str, Any]:
        return {
            "num_qubits": self.num_qubits,
            "edges": [list(e) for e in self.edges],
            "connected": self.is_fully_connected(),
            "diameter": self.diameter(),
            "avg_degree": 2 * len(self.edges) / self.num_qubits if self.num_qubits else 0.0,
        }


@dataclass
class HardwareModel:
    """A hypothetical (or documented) device profile."""

    name: str
    coupling_map: CouplingMap
    native_one_qubit: tuple[str, ...] = DEFAULT_ONE_QUBIT_GATES
    native_two_qubit: tuple[str, ...] = DEFAULT_TWO_QUBIT_GATES
    one_qubit_gate_time: float = 0.035
    """Microseconds."""
    two_qubit_gate_time: float = 0.35
    one_qubit_gate_error: float = 0.0005
    two_qubit_gate_error: float = 0.008
    readout_error: float = 0.015
    t1: float = 120.0
    t2: float = 90.0
    notes: str = ""
    source: str = "hypothetical"

    @property
    def num_qubits(self) -> int:
        return self.coupling_map.num_qubits

    @property
    def one_qubit_gate_time_ns(self) -> float:
        return self.one_qubit_gate_time * 1000

    def supports(self, gate: str) -> bool:
        return gate in self.native_one_qubit or gate in self.native_two_qubit

    def idle_error_probability(self, duration_us: float) -> float:
        """Depolarising-equivalent probability of an idle error over ``duration_us``.

        Uses the standard T1/T2 decay for the |1> population plus a dephasing
        contribution, converted to an error probability.  First order in
        ``duration/T1`` — adequate for the estimate, and labelled as such.
        """
        if self.t1 <= 0 or self.t2 <= 0:
            return 0.0
        gamma = 1 - math.exp(-duration_us / self.t1)
        dephasing = 1 - math.exp(-duration_us / max(self.t2, 1e-9))
        return float(min(1.0, 0.5 * gamma + 0.5 * dephasing))

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "num_qubits": self.num_qubits,
            "topology": self.coupling_map.to_dict(),
            "native_one_qubit": list(self.native_one_qubit),
            "native_two_qubit": list(self.native_two_qubit),
            "one_qubit_gate_time_us": self.one_qubit_gate_time,
            "two_qubit_gate_time_us": self.two_qubit_gate_time,
            "one_qubit_gate_error": self.one_qubit_gate_error,
            "two_qubit_gate_error": self.two_qubit_gate_error,
            "readout_error": self.readout_error,
            "t1_us": self.t1,
            "t2_us": self.t2,
            "notes": self.notes,
            "source": self.source,
        }


HARDWARE_PRESETS: dict[str, HardwareModel] = {
    "linear_5": HardwareModel(
        name="Line 5 (superconducting-style)",
        coupling_map=CouplingMap.linear(5),
        notes="A five-qubit line. Native CNOT only between neighbours.",
        source="hypothetical",
    ),
    "ring_8": HardwareModel(
        name="Ring 8",
        coupling_map=CouplingMap.ring(8),
        notes="Eight qubits in a ring: one extra edge over a line removes the diameter bottleneck.",
        source="hypothetical",
    ),
    "grid_4x4": HardwareModel(
        name="Grid 4x4",
        coupling_map=CouplingMap.grid(4, 4),
        notes="Two-dimensional nearest-neighbour lattice, 40 edges, diameter 6.",
        source="hypothetical",
    ),
    "all_to_all_20": HardwareModel(
        name="All-to-all 20 (trapped-ion style)",
        coupling_map=CouplingMap.all_to_all(20),
        one_qubit_gate_time=20.0,
        two_qubit_gate_time=200.0,
        one_qubit_gate_error=0.0001,
        two_qubit_gate_error=0.003,
        readout_error=0.005,
        t1=10_000.0,
        t2=1_000.0,
        notes="Full connectivity, slower gates, much longer coherence times.",
        source="hypothetical",
    ),
    "ideal_all_to_all": HardwareModel(
        name="Ideal all-to-all",
        coupling_map=CouplingMap.all_to_all(16),
        one_qubit_gate_error=0.0,
        two_qubit_gate_error=0.0,
        readout_error=0.0,
        notes="Noiseless reference device: useful as a routing/perf baseline.",
        source="hypothetical",
    ),
}


@dataclass
class RoutingResult:
    """Outcome of mapping a logical circuit onto a topology."""

    circuit: Circuit
    logical_to_physical: dict[int, int]
    swaps_inserted: int
    swaps: list[dict[str, Any]]
    depth_before: int
    depth_after: int
    gates_before: int
    gates_after: int
    violations_before: list[dict[str, Any]]
    violations_after: list[dict[str, Any]]
    estimation: dict[str, Any]
    notes: list[str] = field(default_factory=list)

    def to_dict(self, include_circuit: bool = True) -> dict[str, Any]:
        out: dict[str, Any] = {
            "logical_to_physical": {str(k): v for k, v in self.logical_to_physical.items()},
            "swaps_inserted": self.swaps_inserted,
            "swaps": self.swaps,
            "depth_before": self.depth_before,
            "depth_after": self.depth_after,
            "depth_overhead": self.depth_after - self.depth_before,
            "depth_overhead_percent": (
                100.0 * (self.depth_after - self.depth_before) / self.depth_before if self.depth_before else 0.0
            ),
            "gates_before": self.gates_before,
            "gates_after": self.gates_after,
            "violations_before": self.violations_before,
            "violations_after": self.violations_after,
            "estimation": self.estimation,
            "notes": self.notes,
        }
        if include_circuit:
            out["circuit"] = self.circuit.to_dict()
        return out


def _initial_layout(circuit: Circuit, hardware: HardwareModel) -> dict[int, int]:
    """Greedy initial placement: busiest logical qubits get the best-connected wires."""
    activity = circuit.qubit_activity()
    used = sorted(activity, key=lambda q: (-activity[q], q))
    degree = {q: len(hardware.coupling_map.neighbours(q)) for q in range(hardware.num_qubits)}
    physical = sorted(range(hardware.num_qubits), key=lambda q: (-degree[q], q))
    return {logical: physical[i] for i, logical in enumerate(used[: hardware.num_qubits])}


def route_circuit(
    circuit: Circuit,
    hardware: HardwareModel,
    *,
    layout: dict[int, int] | None = None,
) -> RoutingResult:
    """Map a logical circuit onto a topology, inserting SWAPs where required.

    The router walks the circuit maintaining a *dynamic layout* (which logical
    qubit currently lives on which physical wire) and, for each two-qubit gate that
    is not physically adjacent, moves one operand along a shortest path by
    inserting SWAPs — the same approach real compilers use, simplified to
    nearest-neighbour SWAPs with a cheapest-first heuristic.
    """
    if circuit.num_qubits > hardware.num_qubits:
        raise ValueError(
            f"circuit needs {circuit.num_qubits} qubits but {hardware.name} has "
            f"{hardware.num_qubits}"
        )
    if not hardware.coupling_map.is_fully_connected():
        raise ValueError(f"{hardware.name} is disconnected; routing cannot bridge components")

    notes: list[str] = []
    layout = dict(layout) if layout else _initial_layout(circuit, hardware)
    # Every logical qubit must land somewhere before relabelling starts.
    free = [p for p in range(hardware.num_qubits) if p not in set(layout.values())]
    for logical in range(circuit.num_qubits):
        if logical not in layout:
            if not free:
                raise ValueError("no free physical qubit left for the initial layout")
            layout[logical] = free.pop(0)

    logical_to_physical = dict(layout)
    physical_to_logical = {p: l for l, p in layout.items()}

    routed = Circuit(
        hardware.num_qubits,
        circuit.num_clbits,
        name=f"{circuit.name}@{hardware.name}",
        description=circuit.description,
        metadata={
            **circuit.metadata,
            "hardware": hardware.name,
            "routed": True,
            "logical_qubits": circuit.num_qubits,
        },
    )
    swaps: list[dict[str, Any]] = []
    violations_before = connectivity_violations(circuit, hardware)

    for op in circuit.operations:
        if op.kind != "gate" or (op.arity + len(op.controls)) < 2:
            routed.append(_relabel(op, layout))
            continue
        wires = [layout[q] for q in op.controls] + [layout[q] for q in op.targets]
        # A 2-qubit gate needs an edge; larger gates are assumed decomposable by the
        # device and are reported rather than silently rewritten.
        if len(wires) > 2 and not hardware.supports(op.name):
            notes.append(
                f"{op.name} acts on {len(wires)} qubits and is not native to {hardware.name}; "
                "it would be decomposed before execution."
            )
        if len(wires) == 2:
            a, b = wires
            if not hardware.coupling_map.is_connected(a, b):
                path = hardware.coupling_map.shortest_path(a, b)
                # Walk the second operand towards the first.  ``path[0]`` (the first
                # operand) is never touched, so its wire stays valid for the gate.
                for index in range(len(path) - 2, 0, -1):
                    sw_a, sw_b = path[index], path[index + 1]
                    routed.add("SWAP", [sw_a, sw_b])
                    swaps.append(
                        {
                            "physical": [sw_a, sw_b],
                            "logical": [physical_to_logical.get(sw_a), physical_to_logical.get(sw_b)],
                            "reason": f"route {op.name} between physical {a} and {b}",
                        }
                    )
                    la, lb = physical_to_logical.pop(sw_a, None), physical_to_logical.pop(sw_b, None)
                    if la is not None:
                        physical_to_logical[sw_b] = la
                        layout[la] = sw_b
                    if lb is not None:
                        physical_to_logical[sw_a] = lb
                        layout[lb] = sw_a
                wires = [layout[q] for q in op.controls] + [layout[q] for q in op.targets]
        clone = op.copy()
        clone.targets = [layout[q] for q in op.targets]
        clone.controls = [layout[q] for q in op.controls]
        routed.append(clone)

    violations_after = connectivity_violations(routed, hardware)
    estimation = estimate_noise(routed, hardware)
    if swaps:
        notes.append(
            f"{len(swaps)} SWAP(s) inserted for routing; each SWAP costs 3 CNOTs on a "
            "superconducting device, which the noise estimate includes."
        )
    return RoutingResult(
        circuit=routed,
        logical_to_physical=logical_to_physical,
        swaps_inserted=len(swaps),
        swaps=swaps,
        depth_before=circuit.depth(),
        depth_after=routed.depth(),
        gates_before=circuit.gate_count(),
        gates_after=routed.gate_count(),
        violations_before=violations_before,
        violations_after=violations_after,
        estimation=estimation,
        notes=notes,
    )


def _relabel(op: Operation, layout: dict[int, int]) -> Operation:
    clone = op.copy()
    clone.targets = [layout[q] for q in op.targets]
    clone.controls = [layout[q] for q in op.controls]
    return clone


def connectivity_violations(circuit: Circuit, hardware: HardwareModel) -> list[dict[str, Any]]:
    """Two-qubit gates that the topology cannot execute directly."""
    out: list[dict[str, Any]] = []
    for index, op in enumerate(circuit.operations):
        if op.kind != "gate":
            continue
        wires = list(op.controls) + list(op.targets)
        if len(wires) != 2:
            if len(wires) > 2 and not hardware.supports(op.name):
                out.append(
                    {
                        "index": index,
                        "gate": op.name,
                        "wires": wires,
                        "issue": f"{len(wires)}-qubit gate is not native",
                    }
                )
            continue
        a, b = wires
        if a >= hardware.num_qubits or b >= hardware.num_qubits:
            out.append({"index": index, "gate": op.name, "wires": wires, "issue": "outside the device"})
            continue
        if not hardware.coupling_map.is_connected(a, b):
            out.append(
                {
                    "index": index,
                    "gate": op.name,
                    "wires": wires,
                    "issue": "not connected",
                    "distance": hardware.coupling_map.distance(a, b),
                }
            )
    return out


def unsupported_gates(circuit: Circuit, hardware: HardwareModel) -> list[dict[str, Any]]:
    """Gates the device cannot execute natively (they would need decomposition)."""
    out: list[dict[str, Any]] = []
    for index, op in enumerate(circuit.operations):
        if op.kind == "gate" and not hardware.supports(op.name):
            out.append({"index": index, "gate": op.name, "qubits": op.qubits})
    return out


def estimate_noise(circuit: Circuit, hardware: HardwareModel) -> dict[str, Any]:
    """First-order success-probability estimate for a circuit on a device.

    ``P_success ~ prod(1 - gate_error) * (1 - readout_error)^n_measured * exp(-t/T2)``.
    Every term is reported separately so the dominant contributor is visible, and
    the whole thing is labelled an estimate.
    """
    one_q = two_q = multi_q = 0
    duration = 0.0
    for op in circuit.operations:
        if op.kind != "gate":
            continue
        arity = op.arity + len(op.controls)
        if arity == 1:
            one_q += 1
            duration += hardware.one_qubit_gate_time
        elif arity == 2:
            two_q += 1
            duration += hardware.two_qubit_gate_time
        else:
            multi_q += 1
            duration += arity * hardware.two_qubit_gate_time

    gate_survival = (
        (1 - hardware.one_qubit_gate_error) ** one_q
        * (1 - hardware.two_qubit_gate_error) ** two_q
        * (1 - min(0.5, 2 * hardware.two_qubit_gate_error)) ** multi_q
    )
    measured = len(circuit.measurements) or circuit.num_qubits
    readout_survival = (1 - hardware.readout_error) ** measured
    coherence = math.exp(-duration / max(hardware.t2, 1e-9)) if hardware.t2 > 0 else 1.0
    total = max(0.0, gate_survival * readout_survival * coherence)

    contributors = {
        "gate_errors": 1 - gate_survival,
        "readout_errors": 1 - readout_survival,
        "decoherence": 1 - coherence,
    }
    dominant = max(contributors.items(), key=lambda kv: kv[1])[0] if contributors else None
    return {
        "label": "ESTIMATED (hardware model)",
        "estimated_success_probability": total,
        "estimated_error_rate": 1 - total,
        "gate_survival": gate_survival,
        "readout_survival": readout_survival,
        "coherence_factor": coherence,
        "contributors": contributors,
        "dominant_contributor": dominant,
        "one_qubit_gates": one_q,
        "two_qubit_gates": two_q,
        "multi_qubit_gates": multi_q,
        "circuit_duration_us": duration,
        "circuit_depth": circuit.depth(),
        "assumptions": [
            "Independent, gate-local depolarising errors (no correlated or crosstalk errors).",
            "Idle decoherence estimated from a single lumped duration, not per-qubit scheduling.",
            "Readout error treated as symmetric bit flips.",
            "No leakage, no drift, no calibration error.",
        ],
        "hardware": hardware.name,
        "source": hardware.source,
    }


def hardware_report(circuit: Circuit, hardware: HardwareModel, *, route: bool = True) -> dict[str, Any]:
    """Full hardware analysis: violations, routing cost and a noise estimate."""
    violations = connectivity_violations(circuit, hardware)
    unsupported = unsupported_gates(circuit, hardware)
    report: dict[str, Any] = {
        "hardware": hardware.to_dict(),
        "required_qubits": circuit.num_qubits,
        "available_qubits": hardware.num_qubits,
        "fits": circuit.num_qubits <= hardware.num_qubits,
        "connectivity_violations": violations,
        "unsupported_gates": unsupported,
        "estimate_before_routing": estimate_noise(circuit, hardware),
        "limitations": [
            "Noise numbers here are ESTIMATES from a device model, not measurements.",
            "Routing uses nearest-neighbour SWAPs; a real compiler may find a better layout.",
        ],
    }
    if route and circuit.num_qubits <= hardware.num_qubits and hardware.coupling_map.is_fully_connected():
        routing = route_circuit(circuit, hardware)
        report["routing"] = routing.to_dict(include_circuit=True)
        report["estimate_after_routing"] = routing.estimation
    return report


def preset_catalog() -> list[dict[str, Any]]:
    """Device presets for the UI."""
    return [
        {
            "key": key,
            "name": model.name,
            "num_qubits": model.num_qubits,
            "topology": key.split("_")[0],
            "edges": len(model.coupling_map.edges),
            "connected": model.coupling_map.is_fully_connected(),
            "two_qubit_gate_error": model.two_qubit_gate_error,
            "source": model.source,
            "notes": model.notes,
        }
        for key, model in HARDWARE_PRESETS.items()
    ]


__all__ = [
    "CouplingMap",
    "DEFAULT_ONE_QUBIT_GATES",
    "DEFAULT_TWO_QUBIT_GATES",
    "HARDWARE_PRESETS",
    "HardwareModel",
    "RoutingResult",
    "connectivity_violations",
    "estimate_noise",
    "hardware_report",
    "preset_catalog",
    "route_circuit",
    "unsupported_gates",
]
