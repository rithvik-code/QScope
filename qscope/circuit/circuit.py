"""Circuit model: operations, scheduling, resources and serialisation.

The circuit is deliberately a *data structure*, not an engine.  Every consumer
(simulator, tracer, optimizer, hardware mapper, report generator) walks the same
operation list, so an optimization that changes the circuit is visible to all of
them without any translation layer.

Operation kinds
---------------
``gate``     a unitary operation, optionally controlled or classically conditioned
``measure``  projective readout into classical bits
``reset``    non-unitary reset of a qubit to ``|0>``
``barrier``  a scheduling fence (blocks optimisation across it, keeps wire order)
``delay``    an idle interval on a qubit (used by noise models for idle decay)
"""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable, Iterator, Sequence

import numpy as np

from qscope.core.gates import gate_spec, inverse_gate, resolve_name
from qscope.core.qubit import ClassicalRegister, QubitRegister
from qscope.core.tensor import COMPLEX

GATE = "gate"
MEASURE = "measure"
RESET = "reset"
BARRIER = "barrier"
DELAY = "delay"

OP_KINDS = (GATE, MEASURE, RESET, BARRIER, DELAY)

CLIFFORD_GATES = {
    "I", "X", "Y", "Z", "H", "S", "SDG", "SX", "SXDG", "P",
    "CNOT", "CX", "CZ", "CY", "SWAP", "ISWAP", "ISWAPDG", "TOFFOLI", "CCX", "CCZ",
}
"""Gates in the (single-qubit + CNOT) Clifford group.

The Clifford group is efficiently classically simulable (Gottesman–Knill), so
``is_clifford`` circuits are labelled as such in reports — that is a meaningful
statement about a circuit, not a marketing claim.
"""


def _new_id(prefix: str = "op") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


@dataclass
class Condition:
    """Classical ``if`` condition on a classical bit (mid-circuit feedback)."""

    clbit: int
    value: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {"clbit": self.clbit, "value": self.value}

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "Condition":
        return cls(clbit=int(payload["clbit"]), value=int(payload.get("value", 1)))


@dataclass
class Operation:
    """A single instruction in a circuit."""

    name: str
    targets: list[int] = field(default_factory=list)
    params: list[float] = field(default_factory=list)
    controls: list[int] = field(default_factory=list)
    control_values: list[int] | None = None
    classical_targets: list[int] = field(default_factory=list)
    condition: Condition | None = None
    kind: str = GATE
    label: str = ""
    opid: str = field(default_factory=lambda: _new_id())
    metadata: dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------ views

    @property
    def qubits(self) -> list[int]:
        """Every qubit this instruction touches."""
        return list(self.controls) + list(self.targets)

    @property
    def arity(self) -> int:
        return len(self.targets)

    @property
    def display(self) -> str:
        """Short label for diagrams, e.g. ``Rz(1.57)`` or ``c[0]=``."""
        if self.kind == MEASURE:
            return "M"
        if self.kind == RESET:
            return "|0>"
        if self.kind == BARRIER:
            return "‖"
        if self.kind == DELAY:
            return f"Δt{self.params[0]:g}" if self.params else "Δt"
        spec = None
        try:
            spec = gate_spec(self.name)
        except KeyError:
            pass
        base = (spec.display if spec and spec.display else self.name) if spec else self.name
        if self.params:
            args = ",".join(f"{p:.3g}" for p in self.params)
            base = f"{base}({args})"
        if self.controls:
            base = f"c·{base}"
        return base

    @property
    def is_unitary(self) -> bool:
        return self.kind in (GATE, DELAY)

    @property
    def is_parameterized(self) -> bool:
        return bool(self.params)

    # ------------------------------------------------------------------ io

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "targets": list(self.targets),
            "params": [float(p) for p in self.params],
            "controls": list(self.controls),
            "control_values": list(self.control_values) if self.control_values else None,
            "classical_targets": list(self.classical_targets),
            "condition": self.condition.to_dict() if self.condition else None,
            "kind": self.kind,
            "label": self.label,
            "opid": self.opid,
            "display": self.display,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "Operation":
        kind = payload.get("kind", GATE)
        if kind not in OP_KINDS:
            raise ValueError(f"unknown operation kind {kind!r}")
        name = payload.get("name", "")
        if kind == GATE:
            name = resolve_name(name)
        return cls(
            name=name,
            targets=[int(t) for t in payload.get("targets", [])],
            params=[float(p) for p in payload.get("params", [])],
            controls=[int(c) for c in payload.get("controls", [])],
            control_values=[int(v) for v in payload["control_values"]]
            if payload.get("control_values") is not None
            else None,
            classical_targets=[int(c) for c in payload.get("classical_targets", [])],
            condition=Condition.from_dict(payload["condition"]) if payload.get("condition") else None,
            kind=kind,
            label=payload.get("label", ""),
            opid=payload.get("opid") or _new_id(),
            metadata=dict(payload.get("metadata", {})),
        )

    def copy(self, *, keep_id: bool = True) -> "Operation":
        clone = Operation(
            name=self.name,
            targets=list(self.targets),
            params=list(self.params),
            controls=list(self.controls),
            control_values=list(self.control_values) if self.control_values else None,
            classical_targets=list(self.classical_targets),
            condition=Condition(self.condition.clbit, self.condition.value) if self.condition else None,
            kind=self.kind,
            label=self.label,
            opid=self.opid if keep_id else _new_id(),
            metadata=dict(self.metadata),
        )
        return clone

    def inverse(self) -> "Operation":
        """Adjoint instruction (measurement/reset/barrier are not invertible)."""
        if self.kind != GATE:
            raise ValueError(f"cannot invert a {self.kind} operation")
        name, params = inverse_gate(self.name, self.params)
        return Operation(
            name=name,
            targets=list(self.targets),
            params=list(params),
            controls=list(self.controls),
            control_values=list(self.control_values) if self.control_values else None,
            condition=self.condition,
            kind=GATE,
            label=self.label,
            metadata=dict(self.metadata),
        )


class Circuit:
    """An ordered list of operations on a fixed set of qubits."""

    FORMAT = "qscope-circuit"
    VERSION = "1.0"

    def __init__(
        self,
        num_qubits: int,
        num_clbits: int = 0,
        *,
        name: str = "circuit",
        description: str = "",
        qubit_labels: Sequence[str] | None = None,
        clbit_labels: Sequence[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.qubits = QubitRegister(num_qubits, qubit_labels)
        self.clbits = ClassicalRegister(num_clbits, clbit_labels)
        self.operations: list[Operation] = []
        self.name = name
        self.description = description
        self.metadata: dict[str, Any] = dict(metadata or {})

    # ------------------------------------------------------------------ dunder

    def __len__(self) -> int:
        return len(self.operations)

    def __iter__(self) -> Iterator[Operation]:
        return iter(self.operations)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"Circuit({self.num_qubits}q/{self.num_clbits}c, {len(self)} ops)"

    # -------------------------------------------------------------- properties

    @property
    def num_qubits(self) -> int:
        return self.qubits.num_qubits

    @property
    def num_clbits(self) -> int:
        return self.clbits.num_bits

    @property
    def gates(self) -> list[Operation]:
        return [op for op in self.operations if op.kind == GATE]

    @property
    def measurements(self) -> list[Operation]:
        return [op for op in self.operations if op.kind == MEASURE]

    # ------------------------------------------------------------------ build

    def add(
        self,
        name: str,
        targets: Sequence[int] = (),
        params: Sequence[float] = (),
        *,
        controls: Sequence[int] = (),
        control_values: Sequence[int] | None = None,
        condition: Condition | None = None,
        label: str = "",
        metadata: dict[str, Any] | None = None,
        at: int | None = None,
    ) -> Operation:
        """Append (or insert at ``at``) a unitary gate."""
        op = Operation(
            name=resolve_name(name),
            targets=[self._check_qubit(t) for t in targets],
            params=[float(p) for p in params],
            controls=[self._check_qubit(c) for c in controls],
            control_values=list(control_values) if control_values else None,
            condition=condition,
            kind=GATE,
            label=label,
            metadata=dict(metadata or {}),
        )
        self._validate(op)
        if at is None:
            self.operations.append(op)
        else:
            self.operations.insert(at, op)
        return op

    def measure(
        self,
        qubit: int,
        clbit: int | None = None,
        *,
        at: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Operation:
        """Measure ``qubit`` into ``clbit`` (defaults to the same index)."""
        clbit = qubit if clbit is None else clbit
        op = Operation(
            name="measure",
            targets=[self._check_qubit(qubit)],
            classical_targets=[self._check_clbit(clbit)],
            kind=MEASURE,
            metadata=dict(metadata or {}),
        )
        if at is None:
            self.operations.append(op)
        else:
            self.operations.insert(at, op)
        return op

    def measure_all(self, start_clbit: int = 0) -> list[Operation]:
        out = []
        for q in range(self.num_qubits):
            out.append(self.measure(q, start_clbit + q))
        return out

    def reset(self, qubit: int, *, at: int | None = None) -> Operation:
        op = Operation(name="reset", targets=[self._check_qubit(qubit)], kind=RESET)
        if at is None:
            self.operations.append(op)
        else:
            self.operations.insert(at, op)
        return op

    def barrier(self, qubits: Sequence[int] | None = None, *, at: int | None = None) -> Operation:
        targets = [self._check_qubit(q) for q in (qubits if qubits is not None else range(self.num_qubits))]
        op = Operation(name="barrier", targets=targets, kind=BARRIER)
        if at is None:
            self.operations.append(op)
        else:
            self.operations.insert(at, op)
        return op

    def delay(self, qubit: int, duration: float = 1.0, *, at: int | None = None) -> Operation:
        op = Operation(
            name="delay",
            targets=[self._check_qubit(qubit)],
            params=[float(duration)],
            kind=DELAY,
        )
        if at is None:
            self.operations.append(op)
        else:
            self.operations.insert(at, op)
        return op

    def append(self, op: Operation, *, at: int | None = None) -> Operation:
        """Add a prepared :class:`Operation` (used by importers and the optimizer)."""
        if op.kind == GATE:
            op.name = resolve_name(op.name)
        self._validate(op)
        if at is None:
            self.operations.append(op)
        else:
            self.operations.insert(at, op)
        return op

    def extend(self, ops: Iterable[Operation]) -> "Circuit":
        for op in ops:
            self.append(op)
        return self

    # ------------------------------------------------------------------ edits

    def remove(self, index: int) -> Operation:
        return self.operations.pop(index)

    def remove_many(self, indices: Iterable[int]) -> list[Operation]:
        """Remove several operations at once (indices refer to the original list)."""
        kill = sorted({int(i) for i in indices}, reverse=True)
        removed: list[Operation] = []
        for i in kill:
            removed.append(self.operations.pop(i))
        return list(reversed(removed))

    def move(self, index: int, new_index: int) -> Operation:
        if not 0 <= index < len(self.operations):
            raise IndexError(f"operation index {index} out of range")
        op = self.operations.pop(index)
        new_index = max(0, min(new_index, len(self.operations)))
        self.operations.insert(new_index, op)
        return op

    def replace(self, index: int, op: Operation) -> Operation:
        old = self.operations[index]
        self.append(op, at=index)
        # ``append(at=i)`` inserted before ``old``; drop the stale copy.
        self.operations.pop(index + 1)
        return old

    def set_params(self, index: int, params: Sequence[float]) -> Operation:
        self.operations[index].params = [float(p) for p in params]
        return self.operations[index]

    def insert_circuit(self, other: "Circuit", at: int, qubit_map: dict[int, int] | None = None) -> None:
        """Splice ``other`` into this circuit at ``at`` with an optional qubit remap."""
        remapped: list[Operation] = []
        for op in other.operations:
            clone = op.copy()
            if qubit_map:
                clone.targets = [qubit_map[q] for q in clone.targets]
                clone.controls = [qubit_map[c] for c in clone.controls]
            remapped.append(clone)
        for offset, op in enumerate(remapped):
            self.append(op, at=at + offset)

    # -------------------------------------------------------------- structure

    def layers(self) -> list[list[int]]:
        """Group operation indices into parallel layers ("moments").

        A gate joins the earliest layer after every qubit it touches is free.
        Barriers force a fence: they occupy the current layer of each wire and
        everything after them starts in a later layer.
        """
        wire_layer = [0] * self.num_qubits
        layers: list[list[int]] = []
        for index, op in enumerate(self.operations):
            qubits = op.qubits or list(range(self.num_qubits))
            if not qubits:
                qubits = list(range(self.num_qubits))
            start = max(wire_layer[q] for q in qubits)
            while len(layers) <= start:
                layers.append([])
            layers[start].append(index)
            end = start + 1
            for q in qubits:
                wire_layer[q] = end
        return [layer for layer in layers if layer]

    def depth(self) -> int:
        """Circuit depth (number of sequential layers)."""
        return len(self.layers())

    def gate_count(self) -> int:
        return len(self.gates)

    def op_count(self) -> int:
        return len(self.operations)

    def gate_histogram(self) -> dict[str, int]:
        hist: dict[str, int] = {}
        for op in self.operations:
            key = op.label or (op.name if op.kind != GATE else resolve_name(op.name))
            hist[key] = hist.get(key, 0) + 1
        return dict(sorted(hist.items(), key=lambda kv: (-kv[1], kv[0])))

    def multi_qubit_gate_count(self) -> int:
        return sum(1 for op in self.gates if op.arity + len(op.controls) > 1)

    def two_qubit_gate_count(self) -> int:
        return sum(1 for op in self.gates if op.arity + len(op.controls) == 2)

    def t_count(self) -> int:
        """Number of T/T† gates — the dominant cost with magic-state distillation."""
        return sum(1 for op in self.gates if op.name in {"T", "TDG"})

    def used_qubits(self) -> list[int]:
        used: set[int] = set()
        for op in self.operations:
            used.update(op.qubits)
        return sorted(used)

    def unused_qubits(self) -> list[int]:
        used = set(self.used_qubits())
        return [q for q in range(self.num_qubits) if q not in used]

    def qubit_activity(self) -> dict[int, int]:
        """Operation count per qubit (drives the activity heat strip in the IDE)."""
        out = {q: 0 for q in range(self.num_qubits)}
        for op in self.operations:
            for q in op.qubits:
                out[q] = out.get(q, 0) + 1
        return out

    def is_clifford(self) -> bool:
        """True when every gate is in the Clifford group (efficiently simulable)."""
        for op in self.gates:
            if op.controls:
                return False
            if resolve_name(op.name) not in CLIFFORD_GATES:
                return False
        return True

    def is_parameterized(self) -> bool:
        return any(op.is_parameterized for op in self.gates)

    def parameterized_ops(self) -> list[tuple[int, Operation]]:
        return [(i, op) for i, op in enumerate(self.operations) if op.is_parameterized]

    def has_classical_control(self) -> bool:
        return any(op.condition is not None for op in self.operations)

    def has_mid_circuit_measurement(self) -> bool:
        """True when a measurement is followed by a unitary (measurement is not terminal)."""
        seen_measure = False
        for op in self.operations:
            if op.kind == MEASURE:
                seen_measure = True
            elif seen_measure and op.kind in (GATE, RESET, DELAY):
                return True
        return False

    def classical_control_barriers(self) -> list[int]:
        """Indices after which optimisation must not rewrite history.

        Measurement and reset break the unitary history: an optimizer may not
        cancel gates across them.
        """
        return [i for i, op in enumerate(self.operations) if op.kind in (MEASURE, RESET, BARRIER)]

    def resources(self) -> dict[str, Any]:
        """Resource summary used by reports and the comparison view."""
        hist = self.gate_histogram()
        return {
            "num_qubits": self.num_qubits,
            "num_clbits": self.num_clbits,
            "operations": len(self.operations),
            "gates": self.gate_count(),
            "measurements": len(self.measurements),
            "resets": sum(1 for op in self.operations if op.kind == RESET),
            "depth": self.depth(),
            "multi_qubit_gates": self.multi_qubit_gate_count(),
            "two_qubit_gates": self.two_qubit_gate_count(),
            "t_count": self.t_count(),
            "t_depth": self.t_depth(),
            "histogram": hist,
            "used_qubits": self.used_qubits(),
            "unused_qubits": self.unused_qubits(),
            "is_clifford": self.is_clifford(),
            "is_parameterized": self.is_parameterized(),
            "has_mid_circuit_measurement": self.has_mid_circuit_measurement(),
            "has_classical_control": self.has_classical_control(),
            "parameters": self.parameter_names(),
        }

    def parameter_names(self) -> list[str]:
        """Sorted unique parameter slots as ``opNNN:p0`` identifiers."""
        out: list[str] = []
        for index, op in enumerate(self.operations):
            for slot in range(len(op.params)):
                out.append(f"op{index:03d}:p{slot}")
        return out

    def t_depth(self) -> int:
        """Depth counting only T/T† gates per wire (magic-state cost proxy)."""
        wire_layer = [0] * self.num_qubits
        best = 0
        for op in self.operations:
            if op.name not in {"T", "TDG"}:
                continue
            q = op.targets[0]
            wire_layer[q] += 1
            best = max(best, wire_layer[q])
        return best

    # ----------------------------------------------------------------- evolve

    def bind(self, values: dict[str, float] | Sequence[float]) -> "Circuit":
        """Return a copy with numeric parameter values substituted.

        Accepts either the flat sequence produced by the experiment sweeps or a
        mapping keyed by :meth:`parameter_names`.
        """
        clone = self.copy()
        if isinstance(values, dict):
            flat: list[float] = []
            for name in self.parameter_names():
                if name not in values:
                    raise KeyError(f"missing parameter value for {name!r}")
                flat.append(float(values[name]))
        else:
            flat = [float(v) for v in values]
        expected = sum(len(op.params) for op in clone.operations)
        if len(flat) != expected:
            raise ValueError(f"expected {expected} parameter values, got {len(flat)}")
        cursor = 0
        for op in clone.operations:
            if op.params:
                op.params = flat[cursor : cursor + len(op.params)]
                cursor += len(op.params)
        return clone

    def inverse(self) -> "Circuit":
        """Circuit implementing ``U^dagger`` (reverses gates, keeps measurements)."""
        out = Circuit(self.num_qubits, self.num_clbits, name=f"{self.name}^dag")
        for op in reversed(self.operations):
            if op.kind == GATE:
                out.append(op.inverse())
            elif op.kind in (MEASURE, RESET, BARRIER, DELAY):
                out.append(op.copy())
        return out

    def copy(self, *, name: str | None = None) -> "Circuit":
        clone = Circuit(
            self.num_qubits,
            self.num_clbits,
            name=name if name is not None else self.name,
            description=self.description,
            qubit_labels=self.qubits.labels,
            clbit_labels=self.clbits.labels,
            metadata=dict(self.metadata),
        )
        clone.operations = [op.copy() for op in self.operations]
        return clone

    def to_unitary(self, max_qubits: int = 10) -> np.ndarray:
        """Full ``2^n x 2^n`` unitary of the gate prefix (before any measurement).

        Raises for circuits with measurement, reset or classical conditions,
        because those are not unitary operations and pretending otherwise would
        corrupt every downstream equivalence proof.
        """
        if self.num_qubits > max_qubits:
            raise ValueError(
                f"refusing to build a {self.num_qubits}-qubit unitary "
                f"({4 ** self.num_qubits * 16 / 1e6:.0f} MB); max_qubits={max_qubits}"
            )
        dim = 2**self.num_qubits
        unitary = np.eye(dim, dtype=COMPLEX)
        from qscope.core.tensor import apply_operator, controlled

        for op in self.operations:
            if op.kind == BARRIER or op.kind == DELAY:
                continue
            if op.kind != GATE:
                raise ValueError(f"circuit is not unitary: contains a {op.kind} operation")
            if op.condition is not None:
                raise ValueError("classically conditioned gates have no single unitary")
            spec = gate_spec(op.name)
            inner = (
                spec.matrix(op.params, num_qubits=op.arity)
                if spec.num_qubits == -1
                else spec.matrix(op.params)
            )
            if op.controls:
                inner = controlled(inner, len(op.controls), control_values=op.control_values)
            wires = list(op.controls) + list(op.targets)
            if wires == list(range(self.num_qubits)):
                # The operator already spans every wire in order, so its matrix is
                # exactly the embedded one.
                unitary = inner @ unitary
            else:
                # Otherwise embed each column explicitly: this is the only correct
                # way to handle permuted target orders such as ``ccx c,b,a``.
                cols = [
                    apply_operator(unitary[:, c], inner, wires, self.num_qubits)
                    for c in range(dim)
                ]
                unitary = np.column_stack(cols)
        return unitary

    # ------------------------------------------------------------------- io

    def to_dict(self) -> dict[str, Any]:
        return {
            "format": self.FORMAT,
            "version": self.VERSION,
            "name": self.name,
            "description": self.description,
            "num_qubits": self.num_qubits,
            "num_clbits": self.num_clbits,
            "qubit_labels": self.qubits.labels,
            "clbit_labels": self.clbits.labels,
            "operations": [op.to_dict() for op in self.operations],
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "Circuit":
        if payload.get("format") not in (None, cls.FORMAT):
            raise ValueError(f"unexpected circuit format {payload.get('format')!r}")
        circuit = cls(
            int(payload["num_qubits"]),
            int(payload.get("num_clbits", 0)),
            name=payload.get("name", "circuit"),
            description=payload.get("description", ""),
            qubit_labels=payload.get("qubit_labels"),
            clbit_labels=payload.get("clbit_labels"),
            metadata=payload.get("metadata"),
        )
        for raw in payload.get("operations", []):
            circuit.operations.append(Operation.from_dict(raw))
        return circuit

    def to_json(self, indent: int | None = 2) -> str:
        import json

        return json.dumps(self.to_dict(), indent=indent)

    @classmethod
    def from_json(cls, text: str) -> "Circuit":
        import json

        return cls.from_dict(json.loads(text))

    def to_qasm(self, *, version: str = "2.0") -> str:
        from qscope.circuit.qasm import to_qasm

        return to_qasm(self, version=version)

    @classmethod
    def from_qasm(cls, text: str) -> "Circuit":
        from qscope.circuit.qasm import from_qasm

        return from_qasm(text)

    def diagram(self, max_wires: int = 6) -> str:
        """ASCII diagram — handy in tests, logs and CLI output."""
        lines: list[str] = []
        for q in range(min(self.num_qubits, max_wires)):
            cells: list[str] = []
            for op in self.operations:
                if op.kind == MEASURE and q in op.targets:
                    cells.append("─[M]─")
                elif op.kind == BARRIER:
                    cells.append("──‖──")
                elif q in op.controls:
                    cells.append(f"──●──" if op.arity == 1 else "──●──")
                elif q in op.targets:
                    cells.append(f"─{op.display:<4}─")
                else:
                    cells.append("─────")
            lines.append(f"q{q}: " + "".join(cells))
        if self.num_qubits > max_wires:  # pragma: no cover - display aid
            lines.append(f"... {self.num_qubits - max_wires} more wires")
        return "\n".join(lines)

    # -------------------------------------------------------------- internals

    def _check_qubit(self, index: int) -> int:
        index = int(index)
        if not 0 <= index < self.num_qubits:
            raise ValueError(f"qubit {index} outside 0..{self.num_qubits - 1}")
        return index

    def _check_clbit(self, index: int) -> int:
        index = int(index)
        if not 0 <= index < self.num_clbits:
            raise ValueError(
                f"classical bit {index} outside 0..{self.num_clbits - 1}; "
                "declare more classical bits first"
            )
        return index

    def _validate(self, op: Operation) -> None:
        if op.kind == GATE:
            spec = gate_spec(op.name)
            if spec.num_qubits != -1 and len(op.targets) != spec.num_qubits:
                raise ValueError(
                    f"gate {op.name} acts on {spec.num_qubits} qubit(s), "
                    f"got targets={op.targets}"
                )
            if spec.num_qubits == -1 and len(op.targets) < 2:
                raise ValueError(f"variable-arity gate {op.name} needs at least 2 targets")
            if len(op.params) != len(spec.params):
                raise ValueError(
                    f"gate {op.name} expects {len(spec.params)} parameter(s) "
                    f"{list(spec.params)}, got {op.params}"
                )
            overlap = set(op.targets) & set(op.controls)
            if overlap:
                raise ValueError(f"gate {op.name} uses qubits as both control and target: {overlap}")
        elif op.kind == MEASURE:
            if len(op.targets) != 1:
                raise ValueError("measurement expects exactly one qubit target")
            if len(op.classical_targets) != 1:
                raise ValueError("measurement expects exactly one classical target")
        elif op.kind == RESET:
            if len(op.targets) != 1:
                raise ValueError("reset expects exactly one qubit")
        for q in op.qubits:
            self._check_qubit(q)
        for c in op.classical_targets:
            self._check_clbit(c)


def circuit_from_ops(
    num_qubits: int,
    ops: Sequence[Operation],
    *,
    num_clbits: int = 0,
    name: str = "circuit",
) -> Circuit:
    """Build a circuit from prepared operations (used by algorithms/optimizers)."""
    circuit = Circuit(num_qubits, num_clbits, name=name)
    circuit.extend(ops)
    return circuit


def bcs_helper() -> None:  # pragma: no cover - placeholder for future hooks
    """Reserved for future circuit transforms that need a registry hook."""


__all__ = [
    "BARRIER",
    "CLIFFORD_GATES",
    "Condition",
    "Circuit",
    "DELAY",
    "GATE",
    "MEASURE",
    "OP_KINDS",
    "Operation",
    "RESET",
    "circuit_from_ops",
]
