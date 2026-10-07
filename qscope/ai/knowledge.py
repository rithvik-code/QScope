"""The quantum knowledge graph.

QScope's AI layer must never invent a number.  The way that is enforced is that
the assistant can only speak about nodes that exist in this graph, and every node
either points at a live object or at a stored experiment row.

    Algorithm ── built ──▶ Circuit ── contains ──▶ Gate
                              │
                              ├─ executed as ─▶ Run ── produces ─▶ State
                              │                  │
                              │                  ├─ measured as ─▶ Distribution
                              │                  └─ scored by ─▶ Metric
                              └─ optimised to ─▶ Circuit (verified)

Nodes are plain dicts, edges are typed, and everything is derivable from objects
the caller already has (a circuit, a `SimulationResult`, an `ExperimentOutcome`,
an optimization result, or rows from the SQLite history).  Build the graph from
whatever is available; queries then walk it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

NODE_KINDS = ("algorithm", "circuit", "gate", "run", "state", "distribution", "metric", "experiment", "report")


@dataclass
class KnowledgeNode:
    """One node of the graph."""

    id: str
    kind: str
    label: str
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "kind": self.kind, "label": self.label, "data": self.data}


@dataclass
class KnowledgeEdge:
    source: str
    target: str
    relation: str
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"source": self.source, "target": self.target, "relation": self.relation, "data": self.data}


class KnowledgeGraph:
    """Nodes + typed edges, built only from data QScope actually recorded."""

    def __init__(self) -> None:
        self.nodes: dict[str, KnowledgeNode] = {}
        self.edges: list[KnowledgeEdge] = []

    # ------------------------------------------------------------- mutation

    def add_node(self, node_id: str, kind: str, label: str, **data: Any) -> KnowledgeNode:
        if kind not in NODE_KINDS:
            raise ValueError(f"unknown node kind {kind!r}")
        existing = self.nodes.get(node_id)
        if existing is not None:
            existing.data.update(data)
            return existing
        node = KnowledgeNode(id=node_id, kind=kind, label=label, data=dict(data))
        self.nodes[node_id] = node
        return node

    def add_edge(self, source: str, target: str, relation: str, **data: Any) -> None:
        if source not in self.nodes or target not in self.nodes:
            return
        for edge in self.edges:
            if edge.source == source and edge.target == target and edge.relation == relation:
                edge.data.update(data)
                return
        self.edges.append(KnowledgeEdge(source, target, relation, dict(data)))

    # --------------------------------------------------------------- access

    def of_kind(self, kind: str) -> list[KnowledgeNode]:
        return [n for n in self.nodes.values() if n.kind == kind]

    def neighbours(self, node_id: str, relation: str | None = None) -> list[KnowledgeNode]:
        out: list[KnowledgeNode] = []
        for edge in self.edges:
            if relation and edge.relation != relation:
                continue
            other = None
            if edge.source == node_id:
                other = edge.target
            elif edge.target == node_id:
                other = edge.source
            if other and other in self.nodes:
                out.append(self.nodes[other])
        return out

    def subgraph(self, root: str, depth: int = 2) -> dict[str, Any]:
        seen = {root}
        frontier = [root]
        for _ in range(depth):
            nxt: list[str] = []
            for node_id in frontier:
                for neighbour in self.neighbours(node_id):
                    if neighbour.id not in seen:
                        seen.add(neighbour.id)
                        nxt.append(neighbour.id)
            frontier = nxt
        return {
            "nodes": [self.nodes[n].to_dict() for n in seen],
            "edges": [
                e.to_dict() for e in self.edges if e.source in seen and e.target in seen
            ],
        }

    def metrics_for(self, node_id: str) -> dict[str, float]:
        out: dict[str, float] = {}
        for neighbour in self.neighbours(node_id, "scored by"):
            value = neighbour.data.get("value")
            if isinstance(value, (int, float)):
                out[neighbour.label] = float(value)
        return out

    def summary(self) -> dict[str, Any]:
        counts: dict[str, int] = {}
        for node in self.nodes.values():
            counts[node.kind] = counts.get(node.kind, 0) + 1
        relations: dict[str, int] = {}
        for edge in self.edges:
            relations[edge.relation] = relations.get(edge.relation, 0) + 1
        return {"nodes": len(self.nodes), "edges": len(self.edges), "by_kind": counts, "by_relation": relations}

    def to_dict(self) -> dict[str, Any]:
        return {
            "nodes": [n.to_dict() for n in self.nodes.values()],
            "edges": [e.to_dict() for e in self.edges],
            "summary": self.summary(),
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, default=str)


# ---------------------------------------------------------------------------
# builders
# ---------------------------------------------------------------------------


def add_circuit(graph: KnowledgeGraph, circuit: Any, *, parent: str | None = None, relation: str = "contains") -> str:
    """Add a circuit, its gates and its resource nodes."""
    node_id = f"circuit:{circuit.name}:{id(circuit)}"
    resources = circuit.resources()
    graph.add_node(
        node_id,
        "circuit",
        circuit.name,
        num_qubits=circuit.num_qubits,
        num_clbits=circuit.num_clbits,
        gates=resources.get("gates"),
        depth=resources.get("depth"),
        two_qubit_gates=resources.get("two_qubit_gates"),
        t_count=resources.get("t_count"),
        histogram=resources.get("histogram"),
        is_clifford=resources.get("is_clifford"),
        parameterised=resources.get("is_parameterized"),
        diagram=circuit.diagram(max_wires=min(circuit.num_qubits, 8)),
    )
    for index, op in enumerate(circuit.operations):
        gate_id = f"gate:{node_id}:{index}"
        graph.add_node(
            gate_id,
            "gate",
            op.display,
            op=op.name,
            targets=list(op.targets),
            controls=list(op.controls),
            parameters=dict(op.params),
            layer=index,
        )
        graph.add_edge(node_id, gate_id, "contains", index=index)
    if parent:
        graph.add_edge(parent, node_id, relation)
    return node_id


def add_result(graph: KnowledgeGraph, result: Any, circuit_node: str | None = None) -> str:
    """Add a run, its state, distribution and metrics."""
    run_id = f"run:{result.timestamp or result.circuit_name}:{result.shots}:{result.seed}"
    graph.add_node(
        run_id,
        "run",
        f"{result.circuit_name} on {result.backend}",
        backend=result.backend,
        mode=result.mode,
        representation=(result.plan or {}).get("representation"),
        shots=result.shots,
        seed=result.seed,
        runtime_seconds=result.timing.get("total_seconds"),
        memory_mb=result.memory.get("state_mb"),
        noise_model=result.noise.get("name"),
        exact=(result.plan or {}).get("exact"),
        fidelity_vs_ideal=result.fidelity_vs_ideal,
        warnings=list(result.warnings),
    )
    if circuit_node:
        graph.add_edge(circuit_node, run_id, "executed as")

    distribution_id = f"distribution:{run_id}"
    graph.add_node(
        distribution_id,
        "distribution",
        f"counts ({result.shots} shots)",
        counts=result.counts,
        probabilities=result.ideal_probabilities,
        sampled=result.sampled_probabilities,
        measured_qubits=list(result.measured_qubits),
    )
    graph.add_edge(run_id, distribution_id, "measured as")

    if result.statevector:
        state_id = f"state:{run_id}"
        graph.add_node(
            state_id,
            "state",
            "state vector",
            dimension=result.statevector.get("dimension"),
            nonzero=result.statevector.get("nonzero"),
            top_amplitudes=(result.statevector.get("amplitudes") or [])[:6],
        )
        graph.add_edge(run_id, state_id, "produces")
    if result.density_matrix:
        state_id = f"state:{run_id}"
        graph.add_node(
            state_id,
            "state",
            "density matrix",
            dimension=result.density_matrix.get("dimension"),
            purity=result.density_matrix.get("purity"),
        )
        graph.add_edge(run_id, state_id, "produces")

    for key, value in (result.metrics or {}).items():
        if isinstance(value, (int, float)) or (isinstance(value, str) and key.endswith("status")):
            metric_id = f"metric:{run_id}:{key}"
            graph.add_node(metric_id, "metric", key, value=value, scope="state")
            graph.add_edge(run_id, metric_id, "scored by")
    for key in ("fidelity_vs_ideal", "trace_distance_vs_ideal"):
        value = getattr(result, key)
        if isinstance(value, (int, float)):
            metric_id = f"metric:{run_id}:{key}"
            graph.add_node(metric_id, "metric", key, value=float(value), scope="comparison")
            graph.add_edge(run_id, metric_id, "scored by")
    return run_id


def add_optimization(graph: KnowledgeGraph, optimization: Any, original_node: str | None = None) -> str:
    """Add the optimized circuit and the verification verdict."""
    optimized_node = add_circuit(graph, optimization.optimized, parent=original_node, relation="optimised to")
    graph.add_node(
        f"metric:{optimized_node}:verification",
        "metric",
        "verification",
        value=optimization.verification.get("status"),
        method=optimization.verification.get("method"),
        max_deviation=optimization.verification.get("max_deviation"),
    )
    graph.add_edge(optimized_node, f"metric:{optimized_node}:verification", "scored by")
    for step in optimization.steps:
        graph.add_node(
            f"metric:{optimized_node}:{step.rule}",
            "metric",
            step.rule,
            value=step.gates_after - step.gates_before,
            description=step.description,
            reasoning=step.reasoning,
            verified=step.verified,
            rolled_back=step.rolled_back,
        )
        graph.add_edge(optimized_node, f"metric:{optimized_node}:{step.rule}", "scored by")
    return optimized_node


def add_experiment(graph: KnowledgeGraph, outcome: Any) -> str:
    """Add an experiment and one run node per parameter point."""
    key = outcome.spec["key"]
    experiment_id = f"experiment:{key}:{outcome.started_at}"
    graph.add_node(
        experiment_id,
        "experiment",
        outcome.spec["name"],
        kind=outcome.spec["kind"],
        algorithm=outcome.spec.get("algorithm"),
        axes=outcome.spec.get("axes"),
        shots=outcome.spec.get("shots"),
        seed=outcome.spec.get("seed"),
        noise_model=outcome.spec.get("noise", {}).get("name"),
        rows=len(outcome.rows),
        seconds=outcome.seconds,
        started_at=outcome.started_at,
    )
    for row in outcome.rows:
        run_id = f"run:{experiment_id}:{row.index}"
        graph.add_node(
            run_id,
            "run",
            row.label or f"row {row.index}",
            params=row.params,
            backend=row.backend,
            mode=row.mode,
            qubits=row.qubits,
            gates=row.gates,
            depth=row.depth,
            runtime_seconds=row.runtime_seconds,
            memory_mb=row.memory_mb,
            success_probability=row.success_probability,
            analytic_success=row.analytic_success,
            fidelity_vs_ideal=row.fidelity_vs_ideal,
            top_outcome=row.top_outcome,
            observation=row.observation,
        )
        graph.add_edge(experiment_id, run_id, "contains", index=row.index)
        distribution_id = f"distribution:{run_id}"
        graph.add_node(
            distribution_id,
            "distribution",
            f"counts ({sum(row.counts.values())} shots)",
            counts=row.counts,
            probabilities=row.ideal_probabilities,
        )
        graph.add_edge(run_id, distribution_id, "measured as")
        for metric_key in ("success_probability", "fidelity_vs_ideal", "purity", "entropy", "max_concurrence", "distribution_distance"):
            value = getattr(row, metric_key, None)
            if isinstance(value, (int, float)):
                metric_id = f"metric:{run_id}:{metric_key}"
                graph.add_node(metric_id, "metric", metric_key, value=float(value))
                graph.add_edge(run_id, metric_id, "scored by")
    graph.add_node(
        f"metric:{experiment_id}:aggregates",
        "metric",
        "aggregates",
        value=len(outcome.rows),
        summary=(outcome.aggregates or {}).get("summary"),
        growth=(outcome.aggregates or {}).get("growth"),
        best_success=(outcome.aggregates or {}).get("best_success", {}).get("success_probability") if outcome.aggregates else None,
    )
    graph.add_edge(experiment_id, f"metric:{experiment_id}:aggregates", "scored by")
    return experiment_id


def add_stored_experiment(graph: KnowledgeGraph, stored: Any) -> str:
    """Add a row read back from the SQLite history."""
    experiment_id = f"experiment:stored:{stored.experiment_id}"
    graph.add_node(
        experiment_id,
        "experiment",
        stored.name,
        algorithm=stored.algorithm,
        circuit_name=stored.circuit_name,
        qubits=stored.num_qubits,
        gates=stored.gate_count,
        depth=stored.depth,
        backend=stored.backend,
        representation=stored.representation,
        mode=stored.mode,
        shots=stored.shots,
        seed=stored.seed,
        noise_model=stored.noise_name,
        runtime_seconds=stored.runtime_seconds,
        memory_bytes=stored.memory_bytes,
        created_at=stored.created_at,
        optimizer=stored.optimizer,
    )
    run_id = f"run:stored:{stored.experiment_id}"
    graph.add_node(run_id, "run", stored.name, counts=stored.counts, backend=stored.backend, mode=stored.mode)
    graph.add_edge(experiment_id, run_id, "contains")
    distribution_id = f"distribution:stored:{stored.experiment_id}"
    graph.add_node(distribution_id, "distribution", "counts", counts=stored.counts, probabilities={})
    graph.add_edge(run_id, distribution_id, "measured as")
    for key, value in (stored.metrics or {}).items():
        if isinstance(value, (int, float)):
            metric_id = f"metric:stored:{stored.experiment_id}:{key}"
            graph.add_node(metric_id, "metric", key, value=float(value))
            graph.add_edge(run_id, metric_id, "scored by")
    return experiment_id


def build_knowledge_graph(
    *,
    circuit: Any | None = None,
    result: Any | None = None,
    optimization: Any | None = None,
    outcome: Any | None = None,
    stored: Sequence[Any] = (),
    trace: Any | None = None,
) -> KnowledgeGraph:
    """Build a graph from whatever objects the caller has."""
    graph = KnowledgeGraph()
    circuit_node: str | None = None
    if circuit is not None:
        circuit_node = add_circuit(graph, circuit)
        if getattr(circuit, "algorithm", None):
            algorithm_node = f"algorithm:{circuit.algorithm}"
            graph.add_node(algorithm_node, "algorithm", str(circuit.algorithm), built_by="library")
            graph.add_edge(algorithm_node, circuit_node, "built")
    if optimization is not None:
        add_optimization(graph, optimization, original_node=circuit_node)
    if result is not None:
        add_result(graph, result, circuit_node=circuit_node)
    if outcome is not None:
        experiment_id = add_experiment(graph, outcome)
        if circuit_node:
            graph.add_edge(circuit_node, experiment_id, "swept in")
    for row in stored:
        add_stored_experiment(graph, row)
    if trace is not None:
        trace_node = f"run:trace:{trace.circuit_name}:{len(trace.steps)}"
        graph.add_node(
            trace_node,
            "run",
            f"{trace.circuit_name} trace",
            steps=len(trace.steps),
            depth_mode=trace.depth_mode,
            total_seconds=trace.summary().get("total_seconds"),
            final_entanglement=trace.summary().get("final_entanglement_status"),
        )
        if circuit_node:
            graph.add_edge(circuit_node, trace_node, "traced in")
        for step in trace.steps:
            if step.diff.get("changed_basis_states"):
                metric_id = f"metric:{trace_node}:step{step.index}"
                graph.add_node(
                    metric_id,
                    "metric",
                    f"step {step.index} ({step.display})",
                    value=step.diff.get("total_variation"),
                    entanglement=(step.diff.get("entanglement") or {}).get("after_status"),
                    targets=list(step.targets),
                )
                graph.add_edge(trace_node, metric_id, "scored by")
    return graph


__all__ = [
    "KnowledgeEdge",
    "KnowledgeGraph",
    "KnowledgeNode",
    "add_circuit",
    "add_experiment",
    "add_optimization",
    "add_result",
    "add_stored_experiment",
    "build_knowledge_graph",
]
