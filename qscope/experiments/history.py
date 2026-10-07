"""Experiment history: a local SQLite research log.

Every run is stored with everything needed to reproduce it later:

``experiment id``, timestamp, circuit (full JSON), qubit/gate/depth counts,
backend, representation, noise model and parameters, random seed, shots,
execution time, memory, results (counts + metrics), optimizer provenance and the
software version.  A stored row is enough to answer "what exactly did I run, and
can I get the same number again?" — which is the difference between a demo and a
research tool.

SQLite keeps it offline-first: the whole history is one file next to the project.
"""

from __future__ import annotations

import csv
import io
import json
import os
import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

SCHEMA_VERSION = 3

DEFAULT_DB = Path(os.environ.get("QSCOPE_DB", Path.home() / ".qscope" / "qscope.sqlite3"))


@dataclass
class StoredExperiment:
    """One stored run, with its reproducibility record."""

    experiment_id: str
    name: str
    created_at: str
    tags: list[str]
    circuit_name: str
    num_qubits: int
    num_clbits: int
    gate_count: int
    depth: int
    backend: str
    representation: str
    mode: str
    shots: int
    seed: int
    noise_name: str
    noise_json: dict[str, Any]
    runtime_seconds: float
    memory_bytes: int
    counts: dict[str, int]
    metrics: dict[str, Any]
    circuit: dict[str, Any]
    algorithm: str
    optimizer: str
    warnings: list[str]
    notes: list[str]
    qscope_version: str
    python_version: str
    parent_id: str | None = None
    metadata: dict[str, Any] | None = None

    def to_dict(self, include_circuit: bool = False) -> dict[str, Any]:
        out = {
            "experiment_id": self.experiment_id,
            "name": self.name,
            "created_at": self.created_at,
            "tags": self.tags,
            "circuit_name": self.circuit_name,
            "num_qubits": self.num_qubits,
            "num_clbits": self.num_clbits,
            "gate_count": self.gate_count,
            "depth": self.depth,
            "backend": self.backend,
            "representation": self.representation,
            "mode": self.mode,
            "shots": self.shots,
            "seed": self.seed,
            "noise_name": self.noise_name,
            "noise": self.noise_json,
            "runtime_seconds": self.runtime_seconds,
            "memory_bytes": self.memory_bytes,
            "counts": self.counts,
            "metrics": self.metrics,
            "algorithm": self.algorithm,
            "optimizer": self.optimizer,
            "warnings": self.warnings,
            "notes": self.notes,
            "qscope_version": self.qscope_version,
            "python_version": self.python_version,
            "parent_id": self.parent_id,
            "metadata": self.metadata or {},
        }
        if include_circuit:
            out["circuit"] = self.circuit
        return out

    def reproducibility(self) -> dict[str, Any]:
        """The fields that make this run reproducible, in one place."""
        return {
            "experiment_id": self.experiment_id,
            "created_at": self.created_at,
            "circuit_name": self.circuit_name,
            "num_qubits": self.num_qubits,
            "gate_count": self.gate_count,
            "depth": self.depth,
            "backend": self.backend,
            "representation": self.representation,
            "shots": self.shots,
            "random_seed": self.seed,
            "noise_model": self.noise_name,
            "noise_parameters": self.noise_json,
            "optimizer": self.optimizer,
            "qscope_version": self.qscope_version,
            "python_version": self.python_version,
            "runtime_seconds": self.runtime_seconds,
            "memory_bytes": self.memory_bytes,
        }


class ExperimentStore:
    """Append-only SQLite log of experiments (offline, single file)."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path is not None else DEFAULT_DB
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._migrate()

    # ----------------------------------------------------------------- setup

    def _migrate(self) -> None:
        cur = self._conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS experiments (
                experiment_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                created_at TEXT NOT NULL,
                tags TEXT NOT NULL DEFAULT '[]',
                circuit_name TEXT NOT NULL,
                num_qubits INTEGER NOT NULL,
                num_clbits INTEGER NOT NULL,
                gate_count INTEGER NOT NULL,
                depth INTEGER NOT NULL,
                backend TEXT NOT NULL,
                representation TEXT NOT NULL,
                mode TEXT NOT NULL,
                shots INTEGER NOT NULL,
                seed INTEGER NOT NULL,
                noise_name TEXT NOT NULL,
                noise_json TEXT NOT NULL,
                runtime_seconds REAL NOT NULL,
                memory_bytes INTEGER NOT NULL,
                counts TEXT NOT NULL,
                metrics TEXT NOT NULL,
                circuit TEXT NOT NULL,
                algorithm TEXT NOT NULL DEFAULT '',
                optimizer TEXT NOT NULL DEFAULT '',
                warnings TEXT NOT NULL DEFAULT '[]',
                notes TEXT NOT NULL DEFAULT '[]',
                qscope_version TEXT NOT NULL,
                python_version TEXT NOT NULL,
                parent_id TEXT,
                metadata TEXT NOT NULL DEFAULT '{}'
            )
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_experiments_created ON experiments(created_at DESC)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_experiments_algorithm ON experiments(algorithm)")
        cur.execute("PRAGMA user_version = %d" % SCHEMA_VERSION)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    # ----------------------------------------------------------------- write

    def save(
        self,
        *,
        name: str,
        circuit: dict[str, Any],
        result: dict[str, Any],
        tags: Sequence[str] = (),
        algorithm: str = "",
        optimizer: str = "",
        parent_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        experiment_id: str | None = None,
    ) -> StoredExperiment:
        """Store a run from its serialised result (see ``record_result``)."""
        from qscope import __version__

        circuit_payload = circuit or {}
        resources = circuit_payload.get("resources") or _resources_from_ops(circuit_payload)
        plan = result.get("plan", {})
        timing = result.get("timing", {})
        memory = result.get("memory", {})
        experiment = StoredExperiment(
            experiment_id=experiment_id or uuid.uuid4().hex[:12],
            name=name,
            created_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
            tags=list(tags),
            circuit_name=circuit_payload.get("name", "circuit"),
            num_qubits=int(circuit_payload.get("num_qubits", resources.get("num_qubits", 0))),
            num_clbits=int(circuit_payload.get("num_clbits", 0)),
            gate_count=int(resources.get("gates", 0)),
            depth=int(resources.get("depth", 0)),
            backend=str(plan.get("backend", result.get("backend", ""))),
            representation=str(plan.get("representation", "")),
            mode=str(result.get("mode", "")),
            shots=int(result.get("shots", 0)),
            seed=int(result.get("seed", 0)),
            noise_name=str(result.get("noise", {}).get("name", "ideal")),
            noise_json=result.get("noise", {}),
            runtime_seconds=float(timing.get("total_seconds", 0.0)),
            memory_bytes=int(memory.get("state_bytes", 0) or 0),
            counts=result.get("counts", {}),
            metrics=result.get("metrics") or {},
            circuit=circuit_payload,
            algorithm=algorithm or str(result.get("extra", {}).get("algorithm", "")),
            optimizer=optimizer or str(result.get("extra", {}).get("optimizer", "")),
            warnings=list(result.get("warnings", [])),
            notes=list(result.get("notes", [])),
            qscope_version=__version__,
            python_version=str(timing.get("python", "")),
            parent_id=parent_id,
            metadata=metadata or {},
        )
        self._insert(experiment)
        return experiment

    def _insert(self, experiment: StoredExperiment) -> None:
        self._conn.execute(
            """
            INSERT OR REPLACE INTO experiments (
                experiment_id, name, created_at, tags, circuit_name, num_qubits, num_clbits,
                gate_count, depth, backend, representation, mode, shots, seed, noise_name,
                noise_json, runtime_seconds, memory_bytes, counts, metrics, circuit, algorithm,
                optimizer, warnings, notes, qscope_version, python_version, parent_id, metadata
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                experiment.experiment_id,
                experiment.name,
                experiment.created_at,
                json.dumps(experiment.tags),
                experiment.circuit_name,
                experiment.num_qubits,
                experiment.num_clbits,
                experiment.gate_count,
                experiment.depth,
                experiment.backend,
                experiment.representation,
                experiment.mode,
                experiment.shots,
                experiment.seed,
                experiment.noise_name,
                json.dumps(experiment.noise_json),
                experiment.runtime_seconds,
                experiment.memory_bytes,
                json.dumps(experiment.counts),
                json.dumps(experiment.metrics),
                json.dumps(experiment.circuit),
                experiment.algorithm,
                experiment.optimizer,
                json.dumps(experiment.warnings),
                json.dumps(experiment.notes),
                experiment.qscope_version,
                experiment.python_version,
                experiment.parent_id,
                json.dumps(experiment.metadata or {}),
            ),
        )
        self._conn.commit()

    def record_result(
        self,
        name: str,
        circuit: Any,
        result: Any,
        *,
        tags: Sequence[str] = (),
        optimizer: str = "",
        parent_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> StoredExperiment:
        """Store a live ``SimulationResult`` with its circuit."""
        circuit_payload = circuit.to_dict()
        circuit_payload["resources"] = circuit.resources()
        payload = result.to_dict(include_state=False)
        payload["metrics"] = result.metrics
        return self.save(
            name=name,
            circuit=circuit_payload,
            result=payload,
            tags=tags,
            optimizer=optimizer,
            parent_id=parent_id,
            metadata=metadata,
        )

    def delete(self, experiment_id: str) -> bool:
        cur = self._conn.execute("DELETE FROM experiments WHERE experiment_id = ?", (experiment_id,))
        self._conn.commit()
        return cur.rowcount > 0

    def clear(self) -> int:
        cur = self._conn.execute("DELETE FROM experiments")
        self._conn.commit()
        return cur.rowcount

    # ------------------------------------------------------------------ read

    def get(self, experiment_id: str) -> StoredExperiment | None:
        row = self._conn.execute(
            "SELECT * FROM experiments WHERE experiment_id = ?", (experiment_id,)
        ).fetchone()
        return _row_to_experiment(row) if row else None

    def list(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        algorithm: str | None = None,
        tag: str | None = None,
        search: str | None = None,
        order_by: str = "created_at",
        descending: bool = True,
    ) -> list[StoredExperiment]:
        clauses: list[str] = []
        params: list[Any] = []
        if algorithm:
            clauses.append("algorithm = ?")
            params.append(algorithm)
        if tag:
            clauses.append("tags LIKE ?")
            params.append(f'%"{tag}"%')
        if search:
            clauses.append("(name LIKE ? OR circuit_name LIKE ? OR algorithm LIKE ?)")
            params.extend([f"%{search}%"] * 3)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        direction = "DESC" if descending else "ASC"
        if order_by not in {"created_at", "runtime_seconds", "gate_count", "depth", "num_qubits"}:
            order_by = "created_at"
        rows = self._conn.execute(
            f"SELECT * FROM experiments {where} ORDER BY {order_by} {direction} LIMIT ? OFFSET ?",
            (*params, limit, offset),
        ).fetchall()
        return [_row_to_experiment(r) for r in rows]

    def count(self) -> int:
        return int(self._conn.execute("SELECT COUNT(*) AS c FROM experiments").fetchone()["c"])

    def tags(self) -> list[dict[str, Any]]:
        seen: dict[str, int] = {}
        for row in self._conn.execute("SELECT tags FROM experiments"):
            for tag in json.loads(row["tags"] or "[]"):
                seen[tag] = seen.get(tag, 0) + 1
        return [{"tag": t, "count": c} for t, c in sorted(seen.items(), key=lambda kv: -kv[1])]

    def compare(self, ids: Sequence[str]) -> dict[str, Any]:
        """Compare 2+ stored experiments on resources, runtime and metrics."""
        experiments = [e for e in (self.get(i) for i in ids) if e is not None]
        if len(experiments) < 2:
            raise ValueError("comparison needs at least two existing experiment ids")
        rows: list[dict[str, Any]] = []
        numeric_keys = [
            ("num_qubits", "Qubits"),
            ("gate_count", "Gates"),
            ("depth", "Depth"),
            ("shots", "Shots"),
            ("runtime_seconds", "Runtime (s)"),
            ("memory_bytes", "State memory (B)"),
        ]
        for key, label in numeric_keys:
            values = [getattr(e, key) for e in experiments]
            rows.append({"metric": label, "key": key, "values": values, "delta": values[-1] - values[0]})
        metric_keys = [
            "purity",
            "entropy",
            "dominant_probability",
            "participation_ratio",
            "support_size",
            "entanglement_status",
        ]
        for key in metric_keys:
            values = [e.metrics.get(key) for e in experiments]
            if any(v is None for v in values):
                continue
            delta = None
            if all(isinstance(v, (int, float)) for v in values):
                delta = values[-1] - values[0]
            rows.append({"metric": key, "key": key, "values": values, "delta": delta})
        fidelity_row = {
            "metric": "fidelity_vs_ideal",
            "key": "fidelity_vs_ideal",
            "values": [e.metrics.get("ideal") is not None for e in experiments],
            "delta": None,
        }
        rows.append(fidelity_row)
        verdict: list[str] = []
        a, b = experiments[0], experiments[-1]
        if a.gate_count and b.gate_count != a.gate_count:
            verdict.append(
                f"'{b.name}' uses {b.gate_count} gates vs {a.gate_count} in '{a.name}' "
                f"({100 * (b.gate_count - a.gate_count) / a.gate_count:+.1f}%)."
            )
        if a.depth and b.depth != a.depth:
            verdict.append(f"Depth {a.depth} → {b.depth} ({100 * (b.depth - a.depth) / a.depth:+.1f}%).")
        if a.runtime_seconds and b.runtime_seconds:
            ratio = b.runtime_seconds / a.runtime_seconds
            verdict.append(f"Runtime ratio B/A = {ratio:.2f}× (same machine, same process).")
        if a.backend != b.backend:
            verdict.append(
                f"Different backends ({a.backend} vs {b.backend}): runtime and memory are not "
                "directly comparable, the representations differ."
            )
        return {
            "experiments": [e.to_dict() for e in experiments],
            "labels": [e.name for e in experiments],
            "rows": rows,
            "verdict": verdict,
            "reproducibility": [e.reproducibility() for e in experiments],
        }

    # ------------------------------------------------------------- dashboard

    def stats(self) -> dict[str, Any]:
        """Aggregates for the research dashboard, all computed from stored rows."""
        total = self.count()
        if not total:
            return {
                "total_experiments": 0,
                "total_circuits": 0,
                "unique_circuits": 0,
                "max_qubits": 0,
                "total_gates": 0,
                "total_shots": 0,
                "total_runtime_seconds": 0.0,
                "by_algorithm": [],
                "by_backend": [],
                "by_mode": [],
                "most_tested_algorithm": None,
                "largest_circuit": None,
                "most_expensive_run": None,
                "longest_runtime": None,
                "lowest_purity": None,
                "highest_entanglement": None,
                "recent": [],
            }
        rows = self._conn.execute("SELECT * FROM experiments").fetchall()
        experiments = [_row_to_experiment(r) for r in rows]
        by_algorithm: dict[str, int] = {}
        by_backend: dict[str, int] = {}
        by_mode: dict[str, int] = {}
        for e in experiments:
            key = e.algorithm or e.circuit_name or "unlabelled"
            by_algorithm[key] = by_algorithm.get(key, 0) + 1
            by_backend[e.backend] = by_backend.get(e.backend, 0) + 1
            by_mode[e.mode] = by_mode.get(e.mode, 0) + 1
        circuits = {json.dumps(e.circuit, sort_keys=True) for e in experiments}
        best_opt = [e for e in experiments if e.optimizer]
        return {
            "total_experiments": total,
            "total_circuits": len(circuits),
            "unique_circuits": len(circuits),
            "max_qubits": max(e.num_qubits for e in experiments),
            "max_qubits_experiment": max(experiments, key=lambda e: e.num_qubits).to_dict(),
            "total_gates": sum(e.gate_count for e in experiments),
            "total_shots": sum(e.shots for e in experiments),
            "total_runtime_seconds": sum(e.runtime_seconds for e in experiments),
            "largest_circuit": max(experiments, key=lambda e: (e.depth, e.gate_count)).to_dict(),
            "most_expensive_run": max(experiments, key=lambda e: e.runtime_seconds).to_dict(),
            "longest_runtime": max(experiments, key=lambda e: e.runtime_seconds).to_dict(),
            "deepest_circuit": max(experiments, key=lambda e: e.depth).to_dict(),
            "lowest_purity": min(
                (e for e in experiments if isinstance(e.metrics.get("purity"), (int, float))),
                key=lambda e: e.metrics["purity"],
                default=None,
            ).to_dict()
            if any(isinstance(e.metrics.get("purity"), (int, float)) for e in experiments)
            else None,
            "highest_entanglement": max(
                (
                    e
                    for e in experiments
                    if isinstance((e.metrics.get("entanglement") or {}).get("max_concurrence"), (int, float))
                ),
                key=lambda e: (e.metrics.get("entanglement") or {}).get("max_concurrence", 0),
                default=None,
            ).to_dict()
            if any(
                isinstance((e.metrics.get("entanglement") or {}).get("max_concurrence"), (int, float))
                for e in experiments
            )
            else None,
            "most_tested_algorithm": max(by_algorithm.items(), key=lambda kv: kv[1])[0] if by_algorithm else None,
            "by_algorithm": [{"key": k, "count": v} for k, v in sorted(by_algorithm.items(), key=lambda kv: -kv[1])],
            "by_backend": [{"key": k, "count": v} for k, v in sorted(by_backend.items(), key=lambda kv: -kv[1])],
            "by_mode": [{"key": k, "count": v} for k, v in sorted(by_mode.items(), key=lambda kv: -kv[1])],
            "optimized_experiments": len(best_opt),
            "recent": [e.to_dict() for e in experiments[-10:][::-1]],
        }

    # ---------------------------------------------------------------- export

    def export_json(self, ids: Sequence[str] | None = None) -> str:
        experiments = [self.get(i) for i in ids] if ids else self.list(limit=10000, descending=False)
        return json.dumps(
            {
                "format": "qscope-experiment-log",
                "schema_version": SCHEMA_VERSION,
                "exported_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "experiments": [e.to_dict(include_circuit=True) for e in experiments if e],
            },
            indent=2,
        )

    def export_csv(self, ids: Sequence[str] | None = None) -> str:
        experiments = [self.get(i) for i in ids] if ids else self.list(limit=10000, descending=False)
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(
            [
                "experiment_id",
                "name",
                "created_at",
                "algorithm",
                "circuit",
                "qubits",
                "gates",
                "depth",
                "backend",
                "mode",
                "shots",
                "seed",
                "noise_model",
                "runtime_seconds",
                "memory_bytes",
                "purity",
                "entropy",
                "dominant_basis",
                "dominant_probability",
                "entanglement_status",
                "top_outcome",
                "top_count",
            ]
        )
        for e in experiments:
            if e is None:
                continue
            top = max(e.counts.items(), key=lambda kv: kv[1]) if e.counts else ("", 0)
            writer.writerow(
                [
                    e.experiment_id,
                    e.name,
                    e.created_at,
                    e.algorithm,
                    e.circuit_name,
                    e.num_qubits,
                    e.gate_count,
                    e.depth,
                    e.backend,
                    e.mode,
                    e.shots,
                    e.seed,
                    e.noise_name,
                    f"{e.runtime_seconds:.6f}",
                    e.memory_bytes,
                    (e.metrics.get("purity") if isinstance(e.metrics.get("purity"), (int, float)) else ""),
                    (e.metrics.get("entropy") if isinstance(e.metrics.get("entropy"), (int, float)) else ""),
                    e.metrics.get("dominant_basis", ""),
                    e.metrics.get("dominant_probability", ""),
                    e.metrics.get("entanglement_status", ""),
                    top[0],
                    top[1],
                ]
            )
        return buffer.getvalue()

    def import_json(self, payload: str | dict[str, Any]) -> int:
        data = json.loads(payload) if isinstance(payload, str) else payload
        count = 0
        for item in data.get("experiments", []):
            experiment = StoredExperiment(
                experiment_id=item["experiment_id"],
                name=item.get("name", "imported"),
                created_at=item.get("created_at", time.strftime("%Y-%m-%dT%H:%M:%S")),
                tags=list(item.get("tags", [])),
                circuit_name=item.get("circuit_name", "circuit"),
                num_qubits=int(item.get("num_qubits", 0)),
                num_clbits=int(item.get("num_clbits", 0)),
                gate_count=int(item.get("gate_count", 0)),
                depth=int(item.get("depth", 0)),
                backend=item.get("backend", ""),
                representation=item.get("representation", ""),
                mode=item.get("mode", ""),
                shots=int(item.get("shots", 0)),
                seed=int(item.get("seed", 0)),
                noise_name=item.get("noise_name", "ideal"),
                noise_json=item.get("noise", {}),
                runtime_seconds=float(item.get("runtime_seconds", 0.0)),
                memory_bytes=int(item.get("memory_bytes", 0)),
                counts=item.get("counts", {}),
                metrics=item.get("metrics", {}),
                circuit=item.get("circuit", {}),
                algorithm=item.get("algorithm", ""),
                optimizer=item.get("optimizer", ""),
                warnings=item.get("warnings", []),
                notes=item.get("notes", []),
                qscope_version=item.get("qscope_version", ""),
                python_version=item.get("python_version", ""),
                parent_id=item.get("parent_id"),
                metadata=item.get("metadata", {}),
            )
            self._insert(experiment)
            count += 1
        return count


def _resources_from_ops(circuit: dict[str, Any]) -> dict[str, Any]:
    n = int(circuit.get("num_qubits", 0))
    ops = circuit.get("operations", [])
    gates = [op for op in ops if op.get("kind", "gate") == "gate"]
    return {
        "num_qubits": n,
        "gates": len(gates),
        "depth": len(ops),
        "two_qubit_gates": sum(1 for op in gates if len(op.get("targets", [])) + len(op.get("controls", [])) == 2),
        "measurements": sum(1 for op in ops if op.get("kind") == "measure"),
    }


def _row_to_experiment(row: sqlite3.Row) -> StoredExperiment:
    return StoredExperiment(
        experiment_id=row["experiment_id"],
        name=row["name"],
        created_at=row["created_at"],
        tags=json.loads(row["tags"] or "[]"),
        circuit_name=row["circuit_name"],
        num_qubits=row["num_qubits"],
        num_clbits=row["num_clbits"],
        gate_count=row["gate_count"],
        depth=row["depth"],
        backend=row["backend"],
        representation=row["representation"],
        mode=row["mode"],
        shots=row["shots"],
        seed=row["seed"],
        noise_name=row["noise_name"],
        noise_json=json.loads(row["noise_json"] or "{}"),
        runtime_seconds=row["runtime_seconds"],
        memory_bytes=row["memory_bytes"],
        counts=json.loads(row["counts"] or "{}"),
        metrics=json.loads(row["metrics"] or "{}"),
        circuit=json.loads(row["circuit"] or "{}"),
        algorithm=row["algorithm"],
        optimizer=row["optimizer"],
        warnings=json.loads(row["warnings"] or "[]"),
        notes=json.loads(row["notes"] or "[]"),
        qscope_version=row["qscope_version"],
        python_version=row["python_version"],
        parent_id=row["parent_id"],
        metadata=json.loads(row["metadata"] or "{}"),
    )


_STORE: ExperimentStore | None = None


def default_store() -> ExperimentStore:
    """Process-wide default store (a single SQLite file)."""
    global _STORE
    if _STORE is None:
        _STORE = ExperimentStore()
    return _STORE


__all__ = [
    "DEFAULT_DB",
    "SCHEMA_VERSION",
    "ExperimentStore",
    "StoredExperiment",
    "default_store",
]
