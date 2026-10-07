"""Automatic research report generation.

A QScope report is assembled entirely from recorded data — no number in it is
invented, and every section that matters is generated from the actual objects
(circuit, plan, metrics, noise model, timings, warnings) that produced the run.
The report has the shape a lab note should have:

    Title · Objective · Circuit · Methodology · Parameters · Simulation conditions
    Results · Graphs · Metrics · Observations · Limitations · Conclusion
    Reproducibility appendix

Export formats: HTML (self-contained, printable to PDF), PDF (vector, generated
directly), JSON (machine-readable), CSV (the result tables) and Markdown.
"""

from __future__ import annotations

import csv
import html
import io
import json
import math
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

from qscope.experiments.pdf import MARGIN, PAGE_HEIGHT, PAGE_WIDTH, PDFDocument, Page

SECTION_TEXT = "text"
SECTION_LIST = "list"
SECTION_KV = "kv"
SECTION_TABLE = "table"
SECTION_CHART = "chart"
SECTION_DIAGRAM = "diagram"
SECTION_CODE = "code"

PALETTE = ["#4cc9f0", "#f72585", "#b5179e", "#480ca8", "#4895ef", "#7209b7", "#3a0ca3", "#4361ee"]


@dataclass
class ReportSection:
    """One report section."""

    heading: str
    kind: str
    body: Any
    note: str = ""
    caption: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"heading": self.heading, "kind": self.kind, "body": self.body, "note": self.note, "caption": self.caption}


@dataclass
class Report:
    """A generated report with all its export renderers."""

    title: str
    subtitle: str
    objective: str
    generated_at: str
    qscope_version: str
    mode: str
    sections: list[ReportSection] = field(default_factory=list)
    observations: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    conclusion: str = ""
    reproducibility: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------- structure

    def add(self, heading: str, kind: str, body: Any, note: str = "", caption: str = "") -> None:
        self.sections.append(ReportSection(heading, kind, body, note, caption))

    def table(self, heading: str, columns: Sequence[str], rows: Sequence[Sequence[Any]], note: str = "") -> None:
        self.add(heading, SECTION_TABLE, {"columns": list(columns), "rows": [list(r) for r in rows]}, note)

    def to_dict(self) -> dict[str, Any]:
        return {
            "format": "qscope-report",
            "title": self.title,
            "subtitle": self.subtitle,
            "objective": self.objective,
            "generated_at": self.generated_at,
            "qscope_version": self.qscope_version,
            "mode": self.mode,
            "sections": [s.to_dict() for s in self.sections],
            "observations": self.observations,
            "limitations": self.limitations,
            "conclusion": self.conclusion,
            "reproducibility": self.reproducibility,
            "metadata": self.metadata,
        }

    # ---------------------------------------------------------------- export

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, default=str)

    def to_csv(self) -> str:
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(["section", "column", "value"])
        writer.writerow(["meta", "title", self.title])
        writer.writerow(["meta", "objective", self.objective])
        writer.writerow(["meta", "generated_at", self.generated_at])
        writer.writerow(["meta", "mode", self.mode])
        for section in self.sections:
            if section.kind == SECTION_TABLE:
                writer.writerow([section.heading, "", ""])
                writer.writerow([section.heading, "columns", "; ".join(str(c) for c in section.body["columns"])])
                for row in section.body["rows"]:
                    writer.writerow([section.heading, "row", "; ".join(str(v) for v in row)])
            elif section.kind == SECTION_KV:
                for key, value in section.body.items():
                    writer.writerow([section.heading, key, value])
            elif section.kind == SECTION_LIST:
                for item in section.body:
                    writer.writerow([section.heading, "item", item])
            elif section.kind == SECTION_TEXT:
                writer.writerow([section.heading, "text", section.body])
            elif section.kind == SECTION_CHART:
                writer.writerow([section.heading, "x", "; ".join(str(v) for v in section.body.get("x", []))])
                for series in section.body.get("series", []):
                    writer.writerow([section.heading, series.get("label", series.get("key", "")), "; ".join(str(v) for v in series.get("y", []))])
        for observation in self.observations:
            writer.writerow(["Observations", "item", observation])
        for limitation in self.limitations:
            writer.writerow(["Limitations", "item", limitation])
        return buffer.getvalue()

    def to_markdown(self) -> str:
        lines = [f"# {self.title}", "", f"_{self.subtitle}_", "", f"**Objective.** {self.objective}", ""]
        lines.append(f"- Generated: {self.generated_at}")
        lines.append(f"- Mode: {self.mode}")
        lines.append(f"- QScope: {self.qscope_version}")
        lines.append("")
        for section in self.sections:
            lines.append(f"## {section.heading}")
            if section.caption:
                lines.append(f"*{section.caption}*")
            if section.kind == SECTION_TEXT:
                lines.append(str(section.body))
            elif section.kind == SECTION_LIST:
                lines.extend(f"- {item}" for item in section.body)
            elif section.kind == SECTION_KV:
                lines.extend(f"- **{k}**: {v}" for k, v in section.body.items())
            elif section.kind == SECTION_TABLE:
                columns = section.body["columns"]
                lines.append("| " + " | ".join(str(c) for c in columns) + " |")
                lines.append("|" + "|".join(["---"] * len(columns)) + "|")
                for row in section.body["rows"]:
                    lines.append("| " + " | ".join(_fmt_cell(v) for v in row) + " |")
            elif section.kind == SECTION_CODE:
                lines.append("```")
                lines.append(str(section.body))
                lines.append("```")
            elif section.kind == SECTION_CHART:
                lines.append("x: " + ", ".join(str(v) for v in section.body.get("x", [])))
                for series in section.body.get("series", []):
                    lines.append(f"{series.get('label')}: " + ", ".join(_fmt_cell(v) for v in series.get("y", [])))
            if section.note:
                lines.append("")
                lines.append(f"> {section.note}")
            lines.append("")
        lines.append("## Observations")
        lines.extend(f"- {o}" for o in self.observations)
        lines.append("")
        lines.append("## Limitations")
        lines.extend(f"- {l}" for l in self.limitations)
        lines.append("")
        lines.append("## Conclusion")
        lines.append(self.conclusion)
        lines.append("")
        lines.append("## Reproducibility")
        for key, value in self.reproducibility.items():
            lines.append(f"- **{key}**: {value}")
        return "\n".join(lines)

    def to_html(self) -> str:
        return _render_html(self)

    def to_pdf(self) -> bytes:
        return _render_pdf(self)

    def save(self, directory: str | Path, basename: str | None = None) -> dict[str, str]:
        """Write every export format into ``directory`` and return the paths."""
        target = Path(directory)
        target.mkdir(parents=True, exist_ok=True)
        stem = basename or _slug(self.title)
        paths = {
            "html": str(target / f"{stem}.html"),
            "json": str(target / f"{stem}.json"),
            "csv": str(target / f"{stem}.csv"),
            "markdown": str(target / f"{stem}.md"),
            "pdf": str(target / f"{stem}.pdf"),
        }
        Path(paths["html"]).write_text(self.to_html(), encoding="utf-8")
        Path(paths["json"]).write_text(self.to_json(), encoding="utf-8")
        Path(paths["csv"]).write_text(self.to_csv(), encoding="utf-8")
        Path(paths["markdown"]).write_text(self.to_markdown(), encoding="utf-8")
        with open(paths["pdf"], "wb") as handle:
            handle.write(self.to_pdf())
        return paths


def _slug(text: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in text.lower()).strip("-")[:80] or "report"


def _fmt_cell(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return "—"
        return f"{value:.6g}"
    return str(value)


def _new_report(title: str, subtitle: str, objective: str, mode: str) -> Report:
    from qscope import __version__

    return Report(
        title=title,
        subtitle=subtitle,
        objective=objective,
        generated_at=time.strftime("%Y-%m-%d %H:%M:%S"),
        qscope_version=__version__,
        mode=mode,
    )


# ---------------------------------------------------------------------------
# builders
# ---------------------------------------------------------------------------


def report_from_result(
    result: Any,
    circuit: Any | None = None,
    *,
    title: str | None = None,
    objective: str | None = None,
    extra_observations: Sequence[str] = (),
) -> Report:
    """Report for a single simulation run."""
    plan = result.plan or {}
    resources = (circuit.resources() if circuit is not None else {}) or {}
    circuit_payload = circuit.to_dict() if circuit is not None else result.circuit
    report = _new_report(
        title or f"Simulation report — {result.circuit_name}",
        f"{result.backend} engine · {result.mode}",
        objective
        or f"Execute '{result.circuit_name}' and record the resulting state, distribution and cost.",
        result.mode,
    )
    report.add(
        "Circuit",
        SECTION_KV,
        {
            "name": result.circuit_name,
            "qubits": circuit_payload.get("num_qubits", plan.get("num_qubits")),
            "classical bits": circuit_payload.get("num_clbits", 0),
            "gates": resources.get("gates"),
            "depth": resources.get("depth"),
            "two-qubit gates": resources.get("two_qubit_gates"),
            "measurements": resources.get("measurements"),
            "clifford": resources.get("is_clifford"),
            "parameterised": resources.get("is_parameterized"),
        },
    )
    if circuit is not None:
        report.add("Circuit diagram", SECTION_CODE, circuit.diagram(max_wires=min(circuit.num_qubits, 10)))
    report.add(
        "Methodology",
        SECTION_KV,
        {
            "engine": result.backend,
            "representation": plan.get("representation"),
            "exact": plan.get("exact"),
            "sampling": result.timing.get("sampling"),
            "shots": result.shots,
            "random seed": result.seed,
            "noise model": result.noise.get("name"),
            "noise calibrated": result.noise.get("calibrated"),
            "noise approximate": result.noise.get("approximate"),
        },
        note="The engine and its exactness are recorded because a result is only meaningful "
        "alongside the representation that produced it.",
    )
    report.add(
        "Simulation conditions",
        SECTION_KV,
        {
            "estimated state memory": f"{plan.get('estimated_mb', 0):.3f} MB",
            "estimated peak memory": f"{plan.get('estimated_peak_mb', 0):.3f} MB",
            "memory budget": f"{plan.get('budget_mb', 0):.1f} MB",
            "runtime": f"{result.timing.get('total_seconds', 0):.6f} s",
            "operations per second": f"{result.timing.get('operations_per_second', 0) or 0:.1f}",
            "process RSS": f"{result.memory.get('process_rss_mb') or 0:.1f} MB",
            "python": result.timing.get("python"),
        },
    )
    observed = sorted(result.counts.items(), key=lambda kv: -kv[1])[:12]
    report.table(
        "Results — measured counts",
        ["outcome", "counts", "frequency", "exact probability"],
        [
            [outcome, count, f"{count / max(sum(result.counts.values()), 1):.4f}", f"{result.ideal_probabilities.get(outcome, 0.0):.4f}"]
            for outcome, count in observed
        ],
        note=f"{result.shots} shots. 'Exact probability' is the Born probability of the reported "
        "state, not an estimate.",
    )
    report.add(
        "Graphs — outcome distribution",
        SECTION_CHART,
        {
            "x": [o for o, _ in observed[:12]],
            "x_label": "measured outcome",
            "series": [
                {"key": "counts", "label": "shots", "y": [c for _, c in observed[:12]], "kind": "bar"},
                {
                    "key": "probability",
                    "label": "exact probability",
                    "y": [result.ideal_probabilities.get(o, 0.0) for o, _ in observed[:12]],
                    "kind": "line",
                },
            ],
        },
        caption="Measured histogram against the exact Born distribution of the reported state.",
    )
    metrics = result.metrics or {}
    report.table(
        "Metrics",
        ["metric", "value"],
        [
            ["representation", metrics.get("representation")],
            ["purity", _fmt_cell(metrics.get("purity"))],
            ["von Neumann entropy (bits)", _fmt_cell(metrics.get("entropy"))],
            ["linear entropy", _fmt_cell(metrics.get("linear_entropy"))],
            ["support size", metrics.get("support_size")],
            ["participation ratio", _fmt_cell(metrics.get("participation_ratio"))],
            ["dominant basis state", metrics.get("dominant_basis")],
            ["dominant probability", _fmt_cell(metrics.get("dominant_probability"))],
            ["entanglement status", metrics.get("entanglement_status")],
            ["max concurrence", _fmt_cell((metrics.get("entanglement") or {}).get("max_concurrence"))],
            ["coherence (l1 off-diagonal)", _fmt_cell(metrics.get("coherence_l1"))],
            ["state fidelity vs ideal", _fmt_cell(result.fidelity_vs_ideal)],
            ["trace distance vs ideal", _fmt_cell(result.trace_distance_vs_ideal)],
        ],
        note="Formula for every metric is available from the QScope metric glossary.",
    )
    if result.ideal_metrics:
        ideal = result.ideal_metrics
        report.table(
            "Ideal reference (no noise)",
            ["metric", "ideal", "observed"],
            [
                ["dominant basis", ideal.get("dominant_basis"), metrics.get("dominant_basis")],
                ["dominant probability", _fmt_cell(ideal.get("dominant_probability")), _fmt_cell(metrics.get("dominant_probability"))],
                ["purity", _fmt_cell(ideal.get("purity")), _fmt_cell(metrics.get("purity"))],
                ["entropy", _fmt_cell(ideal.get("entropy")), _fmt_cell(metrics.get("entropy"))],
                ["entanglement", ideal.get("entanglement_status"), metrics.get("entanglement_status")],
            ],
            note="Both columns are simulations; the ideal column uses the unitary engine with no noise.",
        )
    per_op = (result.timing.get("per_operation") or [])[:40]
    if per_op:
        report.table(
            "Timing — per operation (first pass)",
            ["#", "operation", "targets", "seconds"],
            [[op["index"], op["display"], ",".join(str(t) for t in op["targets"]), f"{op['seconds']:.6f}"] for op in per_op],
            note="Per-operation timings come from the first shot; later shots reuse the same code path.",
        )
    report.observations = _observations_from_result(result) + list(extra_observations)
    report.limitations = _limitations_from_result(result, plan)
    report.conclusion = _conclusion_from_result(result)
    report.reproducibility = {
        "experiment id": result.extra.get("experiment_id", "not stored"),
        "circuit": result.circuit_name,
        "qubits": circuit_payload.get("num_qubits"),
        "gate count": resources.get("gates"),
        "depth": resources.get("depth"),
        "engine": result.backend,
        "representation": plan.get("representation"),
        "noise model": result.noise.get("name"),
        "noise parameters": json.dumps(result.noise.get("channels") or [], default=str),
        "readout error": result.noise.get("readout_error"),
        "shots": result.shots,
        "random seed": result.seed,
        "runtime (s)": f"{result.timing.get('total_seconds', 0):.6f}",
        "state memory (MB)": f"{(result.memory.get('state_mb') or 0):.6f}",
        "qscope version": report.qscope_version,
        "python": result.timing.get("python"),
        "timestamp": result.timestamp,
    }
    return report


def report_from_experiment(
    outcome: Any,
    *,
    title: str | None = None,
    objective: str | None = None,
) -> Report:
    """Report for a parameter sweep / experiment."""
    spec = outcome.spec
    report = _new_report(
        title or f"Experiment report — {spec['name']}",
        f"{spec['kind']} · {len(outcome.rows)} runs",
        objective or spec.get("description") or f"Run the '{spec['name']}' experiment and analyse the results.",
        "MIXED" if len({r.mode for r in outcome.rows}) > 1 else (outcome.rows[0].mode if outcome.rows else "SIMULATED"),
    )
    report.add(
        "Objective",
        SECTION_TEXT,
        spec.get("description") or "Measure how the circuit behaves as the swept parameters change.",
    )
    report.add("Methodology", SECTION_TEXT, spec.get("methodology") or _methodology_text(spec))
    report.add(
        "Parameters",
        SECTION_KV,
        {
            "experiment key": spec["key"],
            "kind": spec["kind"],
            "algorithm": spec.get("algorithm") or "custom",
            "axes": "; ".join(
                f"{a['label']} = {a['values']}" for a in spec.get("axes", [])
            )
            or "none (single point)",
            "fixed parameters": json.dumps(spec.get("fixed", {})),
            "shots": spec.get("shots"),
            "backend selection": spec.get("backend"),
            "random seed": spec.get("seed"),
            "optimizer level": spec.get("optimizer_level") or "disabled",
        },
    )
    report.add(
        "Simulation conditions",
        SECTION_KV,
        {
            "noise model": spec.get("noise", {}).get("name"),
            "noise parameters": json.dumps(spec.get("noise", {}).get("channels", []), default=str),
            "readout error": spec.get("noise", {}).get("readout_error"),
            "engines used": ", ".join(sorted({r.backend for r in outcome.rows})),
            "modes used": ", ".join(sorted({r.mode for r in outcome.rows})),
            "wall-clock total": f"{outcome.seconds:.4f} s",
            "started": outcome.started_at,
            "finished": outcome.finished_at,
        },
    )
    report.table(
        "Results",
        [
            "run",
            "parameters",
            "qubits",
            "gates",
            "depth",
            "runtime (s)",
            "memory (MB)",
            "success",
            "fidelity vs ideal",
            "purity",
            "entropy",
            "engine",
        ],
        [
            [
                r.index,
                ", ".join(f"{k}={v}" for k, v in r.params.items() if k not in {"algorithm", "vector"}),
                r.qubits,
                r.gates,
                r.depth,
                f"{r.runtime_seconds:.6f}",
                f"{r.memory_mb:.6f}",
                _fmt_cell(r.success_probability),
                _fmt_cell(r.fidelity_vs_ideal),
                _fmt_cell(r.purity),
                _fmt_cell(r.entropy),
                r.backend,
            ]
            for r in outcome.rows
        ],
        note="Success probability is defined per row in the CSV export; the definition differs per "
        "algorithm and is never assumed.",
    )
    series = outcome.series.get("series", [])
    if series:
        report.add(
            "Graphs",
            SECTION_CHART,
            {"x": outcome.series.get("x", []), "x_label": outcome.series.get("x_label", ""), "series": series},
            caption="Every series is measured data except 'Analytic prediction', which is theory.",
        )
    if outcome.aggregates:
        aggregates = outcome.aggregates
        report.table(
            "Metrics — aggregates",
            ["metric", "min", "max", "mean"],
            [
                [key, _fmt_cell(stats["min"]), _fmt_cell(stats["max"]), _fmt_cell(stats["mean"])]
                for key, stats in aggregates.get("summary", {}).items()
            ],
        )
        if aggregates.get("growth"):
            report.add("Growth analysis", SECTION_KV, aggregates["growth"])
    report.observations = list(outcome.observations)
    report.limitations = _limitations_from_experiment(outcome)
    best = outcome.aggregates.get("best_success") if outcome.aggregates else None
    report.conclusion = (
        f"Across {len(outcome.rows)} runs the best success probability was "
        f"{_fmt_cell(best.get('success_probability'))} at {best.get('label')}."
        if best
        else f"The experiment produced {len(outcome.rows)} runs; see the results table for detail."
    ) + " " + _growth_conclusion(outcome.aggregates)
    report.reproducibility = {
        "experiment key": spec["key"],
        "runs stored": len(outcome.experiment_ids),
        "experiment ids": ", ".join(outcome.experiment_ids) or "not stored",
        "random seed": spec.get("seed"),
        "shots": spec.get("shots"),
        "noise model": spec.get("noise", {}).get("name"),
        "noise parameters": json.dumps(spec.get("noise", {}).get("channels", []), default=str),
        "engines": ", ".join(sorted({r.backend for r in outcome.rows})),
        "optimizer": spec.get("optimizer_level") or "none",
        "wall-clock seconds": f"{outcome.seconds:.6f}",
        "started": outcome.started_at,
        "finished": outcome.finished_at,
        "qscope version": report.qscope_version,
    }
    report.metadata = {"spec": spec}
    return report


def report_from_optimization(optimization: Any, *, title: str | None = None) -> Report:
    """Report for a verified circuit optimization."""
    report = _new_report(
        title or f"Optimization report — {optimization.original.name}",
        "verified circuit simplification",
        "Reduce the cost of a circuit while proving the circuit still computes the same thing.",
        "ANALYSIS",
    )
    report.add("Objective", SECTION_TEXT, report.objective)
    report.add(
        "Methodology",
        SECTION_TEXT,
        f"Rule-based rewriting over unitary segments, followed by equivalence verification. "
        f"Verification method: {optimization.verification.get('method')}.",
    )
    report.table(
        "Before / after",
        ["metric", "before", "after", "change"],
        [
            ["gates", optimization.before['gates'], optimization.after['gates'], optimization.improvements['gates_saved']],
            ["depth", optimization.before['depth'], optimization.after['depth'], optimization.improvements['depth_saved']],
            [
                "two-qubit gates",
                optimization.before['two_qubit_gates'],
                optimization.after['two_qubit_gates'],
                optimization.improvements['two_qubit_gates_saved'],
            ],
            ["T-count", optimization.before['t_count'], optimization.after['t_count'], optimization.improvements['t_count_saved']],
            ["operations", optimization.before['operations'], optimization.after['operations'], optimization.improvements['operations_saved']],
            ["qubits", optimization.before['num_qubits'], optimization.after['num_qubits'], -optimization.improvements['qubits_removed']],
        ],
        note=f"Headline: {optimization.headline()}",
    )
    if optimization.steps:
        report.table(
            "Rewrites applied",
            ["rule", "change", "why it is valid", "verified"],
            [
                [s.rule, s.description, s.reasoning, "yes" if s.verified in (True, None) else "ROLLED BACK"]
                for s in optimization.steps
            ],
        )
    report.add(
        "Verification",
        SECTION_KV,
        {
            "status": optimization.verification.get("status"),
            "method": optimization.verification.get("method"),
            "max deviation": _fmt_cell(optimization.verification.get("max_deviation")),
            "tolerance": _fmt_cell(optimization.verification.get("tolerance")),
            "phase policy": optimization.verification.get("phase_policy", "exact operator equivalence"),
            "qubit map (compaction)": json.dumps(optimization.qubit_map),
        },
    )
    report.add(
        "Graphs",
        SECTION_CHART,
        {
            "x": ["gates", "depth", "two-qubit", "T-count"],
            "x_label": "cost metric",
            "series": [
                {"key": "before", "label": "before", "y": [
                    optimization.before['gates'], optimization.before['depth'],
                    optimization.before['two_qubit_gates'], optimization.before['t_count']], "kind": "bar"},
                {"key": "after", "label": "after", "y": [
                    optimization.after['gates'], optimization.after['depth'],
                    optimization.after['two_qubit_gates'], optimization.after['t_count']], "kind": "bar"},
            ],
        },
        caption="Cost before and after. Each unit is a gate, so mixing metrics in one chart is a "
        "summary view, not a precise comparison.",
    )
    report.observations = [
        f"{optimization.improvements['gates_saved']} gates removed "
        f"({optimization.improvements['gates_percent']:.1f}%).",
        f"Depth {optimization.before['depth']} → {optimization.after['depth']} "
        f"({optimization.improvements['depth_percent']:.1f}% lower).",
        f"Two-qubit gates saved: {optimization.improvements['two_qubit_gates_saved']} "
        "(these dominate error rates on real hardware).",
        f"Verification: {optimization.verification.get('status')}.",
        *([f"Rule {name} was rolled back: {reason}" for name, reason in (optimization.verification.get('disabled_rules') or {}).items()]),
        *optimization.notes,
    ]
    report.limitations = list(optimization.verification.get("limitations", [])) or [
        "Optimization is exact but not exhaustive: a different rule set might reduce the circuit further."
    ]
    report.conclusion = (
        f"The optimized circuit is {optimization.verification.get('status')} against the original "
        f"and {optimization.headline().lower()}"
    )
    report.reproducibility = {
        "optimization level": optimization.passes_applied,
        "rules applied": optimization.passes_applied,
        "verification": optimization.verification.get("status"),
        "seconds": f"{optimization.seconds:.4f}",
        "qscope version": report.qscope_version,
    }
    return report


def report_from_trace(trace: Any, *, title: str | None = None) -> Report:
    """Report for a gate-by-gate execution trace."""
    summary = trace.summary()
    report = _new_report(
        title or f"Trace report — {trace.circuit_name}",
        f"gate-by-gate analysis ({trace.depth_mode})",
        "Record the state after every operation and identify which operation changed what.",
        "ANALYSIS",
    )
    report.add("Objective", SECTION_TEXT, report.objective)
    report.add(
        "Methodology",
        SECTION_TEXT,
        "The circuit was evolved one operation at a time with full state snapshots and an exact diff "
        "against the previous step. Measurements collapse for real, using a fixed seed.",
    )
    report.add(
        "Summary",
        SECTION_KV,
        {
            "operations traced": summary["steps"],
            "scheduling layers": summary["layers"],
            "trace wall-clock": f"{summary['total_seconds']:.6f} s",
            "slowest operation": f"#{summary['slowest_operation']['index']} "
            f"{summary['slowest_operation']['display']} ({summary['slowest_operation']['seconds']:.6f} s)"
            if summary["slowest_operation"]
            else None,
            "largest state change": f"#{summary['largest_state_change']['index']} "
            f"{summary['largest_state_change']['display']} (TV {summary['largest_state_change']['total_variation']:.4f})"
            if summary["largest_state_change"]
            else None,
            "final entanglement": summary["final_entanglement_status"],
        },
    )
    report.table(
        "Per-operation analysis",
        ["#", "layer", "operation", "targets", "seconds", "total variation", "entanglement before → after", "max pair concurrence"],
        [
            [
                s.index,
                s.layer,
                s.display,
                ",".join(str(t) for t in s.targets),
                f"{s.seconds:.6f}",
                f"{s.diff.get('total_variation', 0):.4f}",
                f"{s.diff.get('entanglement', {}).get('before_status', '-')} → "
                f"{s.diff.get('entanglement', {}).get('after_status', '-')}"
                if s.diff.get("entanglement")
                else "-",
                _fmt_cell(s.diff.get("entanglement", {}).get("max_concurrence_after") if s.diff.get("entanglement") else None),
            ]
            for s in trace.steps
        ],
    )
    steps_with_changes = [s for s in trace.steps if s.diff.get("changed_basis_states")]
    if steps_with_changes:
        report.add(
            "Graphs — state change per step",
            SECTION_CHART,
            {
                "x": [f"#{s.index}" for s in trace.steps],
                "x_label": "step",
                "series": [
                    {"key": "tv", "label": "total variation", "y": [s.diff.get("total_variation", 0.0) for s in trace.steps]},
                    {"key": "tv", "label": "max entanglement entropy", "y": [
                        (s.diff.get("entanglement") or {}).get("max_entropy_after", 0.0) for s in trace.steps
                    ]},
                ],
            },
            caption="Total variation between consecutive states, and the entanglement created.",
        )
    observations = [
        (
            "Entanglement was created by: "
            + "; ".join(f"#{e['index']} {e['display']} on {e['targets']}" for e in summary["entanglement_created_at"])
            if summary["entanglement_created_at"]
            else "No operation created entanglement according to the per-step diff."
        ),
        (
            f"Slowest step: #{summary['slowest_operation']['index']} {summary['slowest_operation']['display']} "
            f"({summary['slowest_operation']['seconds']:.6f} s)."
            if summary["slowest_operation"]
            else "Timing recorded for all steps."
        ),
    ]
    if summary["largest_state_change"]:
        largest = summary["largest_state_change"]
        observations.insert(
            1,
            f"Largest state change at step #{largest['index']} "
            f"({largest['display']}, TV {largest['total_variation']:.4f})",
        )
    report.observations = observations
    report.limitations = [
        "Trace timing reflects a single pass and includes Python overhead per operation.",
        "Entanglement status per step uses single-qubit entropies (exact for pure states); the "
        "pairwise detail requires the full entanglement report.",
    ]
    report.conclusion = (
        f"Traced {summary['steps']} operations over {summary['layers']} layers; "
        f"final state is {summary['final_entanglement_status']}."
    )
    report.reproducibility = {
        "circuit": trace.circuit_name,
        "depth mode": trace.depth_mode,
        "operations": trace.n_operations,
        "seed": 20260101,
        "qscope version": report.qscope_version,
    }
    return report


def report_from_comparison(comparison: dict[str, Any], *, title: str | None = None) -> Report:
    """Report for a two-circuit comparison."""
    report = _new_report(
        title or "Comparison report",
        "circuit A vs circuit B",
        "Compare two circuits on cost, output distribution and measured metrics.",
        "COMPARISON",
    )
    name_a = comparison["circuit_a"]["name"]
    name_b = comparison["circuit_b"]["name"]
    report.table(
        "Resources",
        ["metric", name_a, name_b, "B − A"],
        [[row["metric"], _fmt_cell(row["a"]), _fmt_cell(row["b"]), _fmt_cell(row["delta"])] for row in comparison["resource_rows"]],
    )
    report.table(
        "Metrics",
        ["metric", name_a, name_b, "B − A"],
        [[row["metric"], _fmt_cell(row["a"]), _fmt_cell(row["b"]), _fmt_cell(row["delta"])] for row in comparison["metric_rows"]],
    )
    counts_a = comparison["a"]["counts"]
    counts_b = comparison["b"]["counts"]
    keys = sorted(set(counts_a) | set(counts_b), key=lambda k: -(counts_a.get(k, 0) + counts_b.get(k, 0)))[:12]
    report.add(
        "Graphs — outcome distributions",
        SECTION_CHART,
        {
            "x": keys,
            "x_label": "outcome",
            "series": [
                {"key": "a", "label": name_a, "y": [counts_a.get(k, 0) for k in keys], "kind": "bar"},
                {"key": "b", "label": name_b, "y": [counts_b.get(k, 0) for k in keys], "kind": "bar"},
            ],
        },
        caption="Both circuits were sampled with the same seed and shot count.",
    )
    report.observations = list(comparison.get("verdict", []))
    report.observations.append(
        f"Output total variation distance: {comparison['output_total_variation']:.4f} "
        f"(threshold 0.05 for 'agree closely')."
    )
    report.limitations = [
        "Shot noise sets a floor on distribution differences; identical circuits can differ by ~1/sqrt(shots).",
        "Resource counts are gate-model counts; a device may need extra routing gates.",
    ]
    report.conclusion = " ".join(comparison.get("verdict", [])) or "Comparison complete."
    report.reproducibility = {
        "circuit a": name_a,
        "circuit b": name_b,
        "seed": 11,
        "shots": 2048,
        "qscope version": report.qscope_version,
    }
    return report


def report_from_evolution(evolution: Any, *, title: str | None = None) -> Report:
    """Report for a circuit evolution / synthesis run."""
    report = _new_report(
        title or "Circuit evolution report",
        f"{len(evolution.candidates)} candidates",
        f"Generate and rank circuit implementations for {evolution.target_description}.",
        "SEARCH",
    )
    report.add("Objective", SECTION_TEXT, report.objective)
    report.add(
        "Methodology",
        SECTION_TEXT,
        "Candidate sources: verified rule-based optimization, exact algebraic templates, greedy "
        "equivalence-preserving search, and a genetic loop whose fitness is the process fidelity "
        "against the target minus a cost penalty.",
    )
    report.table(
        "Candidates (ranked)",
        ["#", "label", "source", "gates", "depth", "two-qubit", "fidelity", "estimated success (model)", "verification"],
        [
            [
                c.rank,
                c.label,
                c.source,
                c.gate_count,
                c.depth,
                c.two_qubit_gates,
                f"{c.fidelity:.6f}",
                _fmt_cell(c.estimated_success),
                c.verification.get("status"),
            ]
            for c in evolution.candidates
        ],
        note="A candidate that does not reproduce the target is never ranked as an implementation; "
        "fidelity is a hard gate in the ranking.",
    )
    if evolution.generations:
        report.add(
            "Graphs — search convergence",
            SECTION_CHART,
            {
                "x": [g.get("generation", g.get("step")) for g in evolution.generations],
                "x_label": "generation / step",
                "series": [
                    {"key": "best", "label": "best fitness", "y": [g.get("best_fitness", g.get("score", 0)) for g in evolution.generations]},
                    {"key": "mean", "label": "mean fitness", "y": [g.get("mean_fitness", 0) for g in evolution.generations]},
                ],
            },
            caption="Genetic search only: best and mean population fitness per generation.",
        )
    report.observations = [evolution.headline()] + evolution.notes + evolution.search_log[:20]
    report.limitations = [
        "Search-based candidates are verified against the target unitary, which is exact only up to "
        "the comparison threshold used.",
        "Genetic search explores stochastically: a better circuit might exist that this seed did not find.",
    ]
    report.conclusion = evolution.headline()
    report.reproducibility = {
        "target": evolution.target_description,
        "seed": evolution.seed,
        "candidates": len(evolution.candidates),
        "seconds": f"{evolution.seconds:.4f}",
        "qscope version": report.qscope_version,
    }
    return report


def report_from_hardware(hardware_report_payload: dict[str, Any], *, title: str | None = None) -> Report:
    """Report for a hardware-mapping analysis."""
    hardware = hardware_report_payload["hardware"]
    report = _new_report(
        title or f"Hardware analysis — {hardware['name']}",
        "ESTIMATED (hardware model)",
        "Check whether a logical circuit fits a device topology and estimate the cost of running it.",
        "ESTIMATION",
    )
    report.add("Objective", SECTION_TEXT, report.objective)
    report.add(
        "Simulation conditions",
        SECTION_KV,
        {
            "device": hardware["name"],
            "source": hardware["source"],
            "qubits": hardware["num_qubits"],
            "topology": f"{hardware['topology']['edges']} edges, diameter {hardware['topology']['diameter']:.0f}",
            "two-qubit gate error": hardware["two_qubit_gate_error"],
            "one-qubit gate error": hardware["one_qubit_gate_error"],
            "readout error": hardware["readout_error"],
            "T1 / T2 (us)": f"{hardware['t1_us']} / {hardware['t2_us']}",
        },
        note="Every number here comes from a device model, not from hardware. Results are labelled "
        "ESTIMATED everywhere they appear.",
    )
    report.table(
        "Connectivity",
        ["issue", "gate", "wires", "detail"],
        [
            ["violation", v.get("gate"), ",".join(str(w) for w in v.get("wires", [])), v.get("issue")]
            for v in hardware_report_payload.get("connectivity_violations", [])
        ]
        + [
            ["unsupported", u.get("gate"), ",".join(str(w) for w in u.get("qubits", [])), "not native"]
            for u in hardware_report_payload.get("unsupported_gates", [])
        ],
        note="Empty means the circuit already matches the device's gate set and connectivity.",
    )
    estimation_before = hardware_report_payload["estimate_before_routing"]
    rows = [["before routing", _fmt_cell(estimation_before["estimated_success_probability"]),
             _fmt_cell(estimation_before["contributors"]["gate_errors"]),
             _fmt_cell(estimation_before["contributors"]["readout_errors"]),
             _fmt_cell(estimation_before["contributors"]["decoherence"])]]
    if "estimate_after_routing" in hardware_report_payload:
        after = hardware_report_payload["estimate_after_routing"]
        rows.append(["after routing", _fmt_cell(after["estimated_success_probability"]),
                     _fmt_cell(after["contributors"]["gate_errors"]),
                     _fmt_cell(after["contributors"]["readout_errors"]),
                     _fmt_cell(after["contributors"]["decoherence"])])
    report.table(
        "Estimated success probability",
        ["stage", "success", "gate error", "readout error", "decoherence"],
        rows,
    )
    if "routing" in hardware_report_payload:
        routing = hardware_report_payload["routing"]
        report.add(
            "Routing",
            SECTION_KV,
            {
                "SWAPs inserted": routing["swaps_inserted"],
                "depth before": routing["depth_before"],
                "depth after": routing["depth_after"],
                "depth overhead": f"{routing['depth_overhead_percent']:.1f}%",
                "violations remaining": len(routing["violations_after"]),
            },
        )
    report.observations = [
        f"Dominant error contribution: {estimation_before['dominant_contributor']}.",
        f"{len(hardware_report_payload.get('connectivity_violations', []))} connectivity violation(s) "
        "before routing.",
        *hardware_report_payload.get("limitations", []),
    ]
    report.limitations = estimation_before.get("assumptions", []) + hardware_report_payload.get("limitations", [])
    report.conclusion = (
        f"Model estimate: {estimation_before['estimated_success_probability']:.4f} success probability on "
        f"{hardware['name']}. This is an estimate from a device model, not a measurement."
    )
    report.reproducibility = {
        "device": hardware["name"],
        "device source": hardware["source"],
        "qscope version": report.qscope_version,
    }
    return report


# ---------------------------------------------------------------------------
# narrative helpers (all grounded in measured values)
# ---------------------------------------------------------------------------


def _methodology_text(spec: dict[str, Any]) -> str:
    kind = spec.get("kind", "custom")
    shots = spec.get("shots")
    base = {
        "algorithm_scaling": "One circuit per system size, executed with identical settings so that "
        "cost, runtime and success rate can be compared across sizes.",
        "noise_sweep": "One circuit evaluated repeatedly with every noise channel probability scaled, "
        "so the degradation curve is attributable to the noise level alone.",
        "backend_comparison": "The same circuit executed on each engine; differences reflect the "
        "representation, not the physics.",
        "optimizer_comparison": "The unoptimized circuit and each verified optimized variant executed "
        "with identical settings.",
        "shots_convergence": "One circuit sampled at increasing shot counts to separate sampling error "
        "from systematic error.",
        "parameter_sweep": "One circuit evaluated across a parameter range, recording the objective at "
        "each value.",
        "custom": "A cartesian sweep over the specified axes.",
    }.get(kind, "A parameter sweep.")
    return f"{base} Each point uses {shots} shots with a fixed random seed, so results are reproducible."


def _observations_from_result(result: Any) -> list[str]:
    observations: list[str] = []
    counts = result.counts
    total = sum(counts.values()) or 1
    if counts:
        top, count = max(counts.items(), key=lambda kv: kv[1])
        observations.append(
            f"Most frequent outcome {top} with {count}/{total} shots ({count / total:.4f}); "
            f"exact probability {result.ideal_probabilities.get(top, 0.0):.4f}."
        )
        if len(counts) > 1:
            second, second_count = sorted(counts.items(), key=lambda kv: -kv[1])[1]
            observations.append(f"Second outcome {second} at {second_count / total:.4f}.")
    resources = (result.circuit or {}).get("resources") or {}
    observations.append(
        f"{result.timing.get('operations', 0)} operations in "
        f"{resources.get('depth', 'unknown')} layers at depth, "
        f"runtime {result.timing.get('total_seconds', 0):.6f} s."
    )
    if result.fidelity_vs_ideal is not None:
        observations.append(
            f"Noisy state fidelity {result.fidelity_vs_ideal:.4f} against the ideal reference "
            f"(trace distance {result.trace_distance_vs_ideal:.4f})."
        )
        if result.fidelity_vs_ideal < 0.9:
            observations.append(
                "Fidelity below 0.9: the dominant error source is listed in the noise model; "
                "consider reducing two-qubit gate count or shot-noise-limited readout."
            )
    metrics = result.metrics or {}
    if metrics.get("entanglement_status"):
        observations.append(f"Entanglement: {metrics['entanglement_status']}.")
    if metrics.get("participation_ratio"):
        observations.append(
            f"Effective occupied states (participation ratio): {metrics['participation_ratio']:.2f} "
            f"of {2 ** metrics.get('num_qubits', 0)} possibilities."
        )
    return observations


def _limitations_from_result(result: Any, plan: dict[str, Any]) -> list[str]:
    limitations: list[str] = []
    if result.mode == "SIMULATED":
        limitations.append("Ideal simulation: no noise, no decoherence, no readout error.")
    else:
        limitations.append(
            f"Noisy simulation on the {result.backend} engine"
            + (" (exact mixed state)." if result.backend == "density_matrix" else " (Monte-Carlo sampled, approximate per shot).")
        )
    limitations.extend(result.noise.get("description", "") and [result.noise["description"]] or [])
    if result.noise.get("approximate"):
        limitations.append("The noise model is flagged approximate by its author.")
    limitations.extend(result.warnings)
    if result.noise.get("readout_error"):
        limitations.append("Readout error is modelled as an independent classical bit flip.")
    limitations.append(
        "Simulated results are not hardware results. QScope distinguishes SIMULATED, NOISY "
        "SIMULATION and REAL HARDWARE explicitly."
    )
    if not plan.get("exact"):
        limitations.append(
            "This engine is approximate by construction: per-shot trajectory sampling has "
            "1/sqrt(shots) statistical error."
        )
    return limitations


def _conclusion_from_result(result: Any) -> str:
    metrics = result.metrics or {}
    parts = [
        f"The circuit produced a state with purity {metrics.get('purity', 0):.4f} and "
        f"entropy {metrics.get('entropy', 0):.4f} bits."
    ]
    if result.ideal_metrics:
        ideal_prob = result.ideal_metrics.get("dominant_probability") or 0.0
        observed = metrics.get("dominant_probability") or 0.0
        parts.append(
            f"The dominant outcome probability moved from {ideal_prob:.4f} (ideal) to "
            f"{observed:.4f} (this run)."
        )
    parts.append(
        f"Runtime {result.timing.get('total_seconds', 0):.6f} s for {result.timing.get('operations', 0)} operations."
    )
    return " ".join(parts)


def _limitations_from_experiment(outcome: Any) -> list[str]:
    limitations: list[str] = []
    modes = {r.mode for r in outcome.rows}
    if "NOISY SIMULATION" in modes:
        limitations.append(
            "Some points in this experiment used a noise model; the backend field in each row says "
            "whether that was exact (density matrix) or sampled (trajectories)."
        )
    if len({r.backend for r in outcome.rows}) > 1:
        limitations.append(
            "Runtimes across different engines are not directly comparable: they represent different physics."
        )
    limitations.extend(outcome.warnings)
    limitations.append(
        "Wall-clock runtime is machine-specific and single-process; it is not a hardware or "
        "cross-platform benchmark."
    )
    return limitations


def _growth_conclusion(aggregates: dict[str, Any]) -> str:
    growth = (aggregates or {}).get("growth")
    if not growth:
        return ""
    return (
        f"Runtime grew {growth['runtime_ratio']:.2f}x across the sweep"
        + (
            f" ({growth['seconds_per_added_qubit']:.6f} s per added qubit)."
            if growth.get("seconds_per_added_qubit")
            else "."
        )
    )


# ---------------------------------------------------------------------------
# renderers
# ---------------------------------------------------------------------------


def _render_html(report: Report) -> str:
    parts: list[str] = []
    parts.append("<!doctype html><html lang='en'><head><meta charset='utf-8'>")
    parts.append(f"<title>{html.escape(report.title)}</title>")
    parts.append(
        "<style>"
        ":root{--fg:#e8ecf4;--bg:#0b0f16;--muted:#93a1b5;--line:#1f2a3a;--accent:#4cc9f0;--accent2:#f72585}"
        "body{margin:0;padding:40px;background:var(--bg);color:var(--fg);"
        "font:13px/1.55 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}"
        ".wrap{max-width:1000px;margin:0 auto}"
        "h1{font-size:22px;margin:0 0 4px;letter-spacing:.02em}"
        "h2{font-size:14px;margin:28px 0 8px;color:var(--accent);text-transform:uppercase;letter-spacing:.08em}"
        ".sub{color:var(--muted);margin-bottom:18px}"
        "table{border-collapse:collapse;width:100%;margin:8px 0}"
        "th,td{border:1px solid var(--line);padding:5px 8px;text-align:left;vertical-align:top}"
        "th{background:#121a26;color:var(--muted);font-weight:600}"
        "td.num{text-align:right;font-variant-numeric:tabular-nums}"
        ".kv{display:grid;grid-template-columns:minmax(180px,1fr) 2fr;gap:2px 16px}"
        ".kv div{padding:3px 0;border-bottom:1px solid var(--line)}"
        ".kv .k{color:var(--muted)}"
        "pre{background:#0f1622;border:1px solid var(--line);padding:12px;overflow-x:auto;color:#c8d4e4}"
        ".note{color:var(--muted);font-size:12px;border-left:2px solid var(--accent);padding-left:10px;margin:8px 0}"
        "ul{margin:6px 0 6px 18px;padding:0}li{margin:3px 0}"
        ".badge{display:inline-block;border:1px solid var(--accent);color:var(--accent);"
        "border-radius:999px;padding:1px 9px;font-size:11px;margin-right:6px}"
        ".badge.warn{border-color:var(--accent2);color:var(--accent2)}"
        "@media print{body{background:#fff;color:#111;padding:0}h2{color:#0a58a8}"
        "th{background:#eee;color:#111}.kv .k,.sub,.note{color:#444}"
        "th,td{border-color:#bbb}pre{background:#f7f7f7;color:#111}a{color:#0a58a8}}"
        "</style></head><body><div class='wrap'>"
    )
    parts.append(f"<h1>{html.escape(report.title)}</h1>")
    parts.append(
        f"<div class='sub'>{html.escape(report.subtitle)} · generated {html.escape(report.generated_at)} · "
        f"QScope {html.escape(report.qscope_version)}</div>"
    )
    parts.append(
        f"<div><span class='badge'>{html.escape(report.mode)}</span>"
        f"<span class='badge warn'>{'NO REAL HARDWARE IN THIS REPORT' if 'HARDWARE' not in report.mode else 'HARDWARE MODEL ESTIMATE'}</span></div>"
    )
    parts.append(f"<h2>Objective</h2><div>{html.escape(report.objective)}</div>")
    for section in report.sections:
        parts.append(f"<h2>{html.escape(section.heading)}</h2>")
        if section.caption:
            parts.append(f"<div class='note'>{html.escape(section.caption)}</div>")
        if section.kind == SECTION_TEXT:
            parts.append(f"<div>{html.escape(str(section.body))}</div>")
        elif section.kind == SECTION_LIST:
            parts.append("<ul>" + "".join(f"<li>{html.escape(str(i))}</li>" for i in section.body) + "</ul>")
        elif section.kind == SECTION_KV:
            parts.append("<div class='kv'>")
            for key, value in section.body.items():
                parts.append(
                    f"<div class='k'>{html.escape(str(key))}</div><div>{html.escape(str(value))}</div>"
                )
            parts.append("</div>")
        elif section.kind == SECTION_TABLE:
            parts.append("<table><thead><tr>")
            for column in section.body["columns"]:
                parts.append(f"<th>{html.escape(str(column))}</th>")
            parts.append("</tr></thead><tbody>")
            for row in section.body["rows"]:
                parts.append("<tr>")
                for cell in row:
                    css = " class='num'" if isinstance(cell, (int, float)) and not isinstance(cell, bool) else ""
                    parts.append(f"<td{css}>{html.escape(_fmt_cell(cell))}</td>")
                parts.append("</tr>")
            parts.append("</tbody></table>")
        elif section.kind == SECTION_CODE:
            parts.append(f"<pre>{html.escape(str(section.body))}</pre>")
        elif section.kind == SECTION_CHART:
            parts.append(_svg_chart(section.body))
        if section.note:
            parts.append(f"<div class='note'>{html.escape(section.note)}</div>")
    parts.append("<h2>Observations</h2><ul>")
    parts.extend(f"<li>{html.escape(str(o))}</li>" for o in report.observations)
    parts.append("</ul><h2>Limitations</h2><ul>")
    parts.extend(f"<li>{html.escape(str(l))}</li>" for l in report.limitations)
    parts.append("</ul>")
    parts.append(f"<h2>Conclusion</h2><div>{html.escape(report.conclusion)}</div>")
    parts.append("<h2>Reproducibility</h2><div class='kv'>")
    for key, value in report.reproducibility.items():
        parts.append(f"<div class='k'>{html.escape(str(key))}</div><div>{html.escape(str(value))}</div>")
    parts.append("</div></div></body></html>")
    return "".join(parts)


def _svg_chart(payload: dict[str, Any], *, width: int = 900, height: int = 260) -> str:
    """Inline SVG chart for the HTML report (no external assets, print-friendly)."""
    x_values = payload.get("x", [])
    series = payload.get("series", [])
    if not x_values or not series:
        return "<div class='note'>no chart data</div>"
    padding_left, padding_right, padding_top, padding_bottom = 56, 16, 18, 42
    plot_w = width - padding_left - padding_right
    plot_h = height - padding_top - padding_bottom
    numeric_series = []
    for s in series:
        values = [abs(float(v)) if isinstance(v, (int, float)) else 0.0 for v in s.get("y", [])]
        numeric_series.append((s, values))
    y_max = max((max(v) for _, v in numeric_series if v), default=1.0) or 1.0
    y_max *= 1.08
    count = len(x_values)
    step = plot_w / max(count - 1, 1)
    parts = [f"<svg viewBox='0 0 {width} {height}' width='100%' height='auto' role='img'>"]
    parts.append(f"<rect x='0' y='0' width='{width}' height='{height}' fill='#0f1622' rx='6'/>")
    for tick in range(5):
        y = padding_top + plot_h * tick / 4
        value = y_max * (1 - tick / 4)
        parts.append(
            f"<line x1='{padding_left}' y1='{y:.1f}' x2='{width - padding_right}' y2='{y:.1f}' stroke='#1f2a3a' stroke-width='1'/>"
        )
        parts.append(
            f"<text x='{padding_left - 8}' y='{y + 4:.1f}' fill='#93a1b5' font-size='10' text-anchor='end'>{value:.3g}</text>"
        )
    for index, label in enumerate(x_values):
        if count > 14 and index % 2:
            continue
        x = padding_left + step * index
        parts.append(
            f"<text x='{x:.1f}' y='{height - 14}' fill='#93a1b5' font-size='10' text-anchor='middle'>{html.escape(str(label))}</text>"
        )
    legend_x = padding_left
    for s_index, (s, values) in enumerate(numeric_series):
        color = PALETTE[s_index % len(PALETTE)]
        is_bar = s.get("kind") == "bar"
        if is_bar:
            bar_w = max(step * 0.36, 3)
            for index, value in enumerate(values):
                bar_h = plot_h * (value / y_max)
                x = padding_left + step * index - bar_w / 2 + (s_index - len(numeric_series) / 2 + 0.5) * bar_w * 0.4
                y = padding_top + plot_h - bar_h
                parts.append(
                    f"<rect x='{x:.1f}' y='{y:.1f}' width='{bar_w:.1f}' height='{bar_h:.1f}' fill='{color}' opacity='0.75'/>"
                )
        else:
            points = " ".join(
                f"{padding_left + step * i:.1f},{padding_top + plot_h - plot_h * (v / y_max):.1f}"
                for i, v in enumerate(values)
            )
            parts.append(f"<polyline points='{points}' fill='none' stroke='{color}' stroke-width='2'/>")
            for index, value in enumerate(values):
                cx = padding_left + step * index
                cy = padding_top + plot_h - plot_h * (value / y_max)
                parts.append(f"<circle cx='{cx:.1f}' cy='{cy:.1f}' r='2.4' fill='{color}'/>")
        parts.append(
            f"<text x='{legend_x}' y='{height - 2}' fill='{color}' font-size='10'>{html.escape(str(s.get('label', s.get('key', ''))))}</text>"
        )
        legend_x += 12 + 7 * len(str(s.get("label", "")))
    if payload.get("x_label"):
        parts.append(
            f"<text x='{width - padding_right}' y='{height - 2}' fill='#93a1b5' font-size='10' text-anchor='end'>{html.escape(str(payload['x_label']))}</text>"
        )
    parts.append("</svg>")
    return "".join(parts)


def _render_pdf(report: Report) -> bytes:
    """Vector PDF rendering of the same content."""
    document = PDFDocument(title=report.title, author="QScope")
    page = document.new_page()
    y = PAGE_HEIGHT - MARGIN
    primary = (0.30, 0.79, 0.94)
    accent = (0.97, 0.15, 0.52)
    body = (0.12, 0.14, 0.18)

    def new_page_if_needed(needed: float = 60.0) -> None:
        nonlocal page, y
        if y < MARGIN + needed:
            page = document.new_page()
            y = PAGE_HEIGHT - MARGIN

    y = page.text(MARGIN, y, report.title, size=17, font="bold", color=(0.05, 0.08, 0.14))
    y = page.text(MARGIN, y, report.subtitle, size=9, color=(0.35, 0.4, 0.48))
    y = page.text(
        MARGIN,
        y,
        f"{report.mode} | generated {report.generated_at} | QScope {report.qscope_version}",
        size=8.5,
        color=(0.35, 0.4, 0.48),
    )
    y -= 6

    def heading(text: str) -> None:
        nonlocal y
        new_page_if_needed(70)
        y -= 8
        page.rect(MARGIN, y - 2, 3, 11, fill=primary)
        y = page.text(MARGIN + 10, y, text.upper(), size=10.5, font="bold", color=(0.10, 0.45, 0.62))
        y -= 4

    heading("Objective")
    y = page.text(MARGIN, y, report.objective, size=9.5, color=body, max_width=PAGE_WIDTH - 2 * MARGIN)

    for section in report.sections:
        heading(section.heading)
        if section.caption:
            y = page.text(MARGIN, y, section.caption, size=8.5, color=(0.4, 0.45, 0.52), max_width=PAGE_WIDTH - 2 * MARGIN)
        if section.kind == SECTION_TEXT:
            y = page.text(MARGIN, y, str(section.body), size=9.5, color=body, max_width=PAGE_WIDTH - 2 * MARGIN)
        elif section.kind == SECTION_LIST:
            for item in section.body:
                y = page.text(MARGIN + 8, y, f"- {item}", size=9, color=body, max_width=PAGE_WIDTH - 2 * MARGIN - 8)
        elif section.kind == SECTION_KV:
            for key, value in section.body.items():
                new_page_if_needed(30)
                y = page.text(MARGIN, y, f"{key}: {value}", size=9, color=body, max_width=PAGE_WIDTH - 2 * MARGIN)
        elif section.kind == SECTION_CODE:
            for line in str(section.body).splitlines()[:80]:
                new_page_if_needed(24)
                y = page.text(MARGIN, y, line, size=7.5, font="mono", color=(0.2, 0.22, 0.28))
        elif section.kind == SECTION_TABLE:
            y = _pdf_table(page, section, MARGIN, y, PAGE_WIDTH - 2 * MARGIN, new_page_if_needed)
        elif section.kind == SECTION_CHART:
            y = _pdf_chart(page, section.body, MARGIN, y, PAGE_WIDTH - 2 * MARGIN, new_page_if_needed)
        if section.note:
            y = page.text(MARGIN, y, section.note, size=8.5, color=(0.4, 0.45, 0.52), max_width=PAGE_WIDTH - 2 * MARGIN)

    heading("Observations")
    for observation in report.observations:
        new_page_if_needed(28)
        y = page.text(MARGIN + 8, y, f"- {observation}", size=9, color=body, max_width=PAGE_WIDTH - 2 * MARGIN - 8)
    heading("Limitations")
    for limitation in report.limitations:
        new_page_if_needed(28)
        y = page.text(MARGIN + 8, y, f"- {limitation}", size=9, color=(0.55, 0.2, 0.35), max_width=PAGE_WIDTH - 2 * MARGIN - 8)
    heading("Conclusion")
    y = page.text(MARGIN, y, report.conclusion, size=9.5, color=body, max_width=PAGE_WIDTH - 2 * MARGIN)
    heading("Reproducibility")
    for key, value in report.reproducibility.items():
        new_page_if_needed(26)
        y = page.text(MARGIN, y, f"{key}: {value}", size=8.5, color=(0.2, 0.25, 0.32), max_width=PAGE_WIDTH - 2 * MARGIN)
    _ = accent
    return document.to_bytes()


def _pdf_table(
    page: Page,
    section: ReportSection,
    x: float,
    y: float,
    width: float,
    new_page_if_needed: Any,
    max_rows: int = 40,
) -> float:
    columns = section.body["columns"]
    rows = section.body["rows"][:max_rows]
    col_width = width / max(len(columns), 1)
    row_height = 14.0
    new_page_if_needed(row_height * (len(rows) + 1) + 10)
    header_y = y
    page.rect(x, header_y - 4, width, row_height, fill=(0.93, 0.95, 0.98))
    for index, column in enumerate(columns):
        page.text(x + 3 + index * col_width, header_y, str(column)[:22], size=7.5, font="bold", color=(0.15, 0.2, 0.3))
    y = header_y - row_height - 2
    for row in rows:
        if y < MARGIN + row_height:
            new_page_if_needed(row_height * 3)
            y = PAGE_HEIGHT - MARGIN
        for index, cell in enumerate(row):
            page.text(x + 3 + index * col_width, y, _fmt_cell(cell)[:26], size=7.5, color=(0.15, 0.18, 0.24))
        y -= row_height
    if len(section.body["rows"]) > max_rows:
        y -= 4
        y = page.text(x, y, f"({len(section.body['rows']) - max_rows} further rows omitted in PDF; see CSV/JSON export)", size=7.5, color=(0.4, 0.45, 0.52))
    return y - 6


def _pdf_chart(
    page: Page,
    payload: dict[str, Any],
    x: float,
    y_top: float,
    width: float,
    new_page_if_needed: Any,
    height: float = 150.0,
) -> float:
    x_values = payload.get("x", [])
    series = payload.get("series", [])
    if not x_values or not series:
        return y_top
    new_page_if_needed(height + 30)
    top = y_top
    bottom = y_top - height
    page.rect(x, bottom, width, height, fill=(0.97, 0.98, 0.99), stroke=(0.82, 0.85, 0.9))
    y_max = max((max(abs(float(v)) for v in s.get("y", []) if isinstance(v, (int, float))) if s.get("y") else 0.0) for s in series) or 1.0
    y_max *= 1.08
    for tick in range(5):
        gy = bottom + height * tick / 4
        page.line(x, gy, x + width, gy, color=(0.88, 0.9, 0.93), width=0.4)
        page.text(x + 2, gy + 2, f"{y_max * tick / 4:.3g}", size=6.5, color=(0.45, 0.5, 0.58))
    step = width / max(len(x_values) - 1, 1)
    for index, s in enumerate(series):
        color = _hex_to_rgb(PALETTE[index % len(PALETTE)])
        values = [abs(float(v)) if isinstance(v, (int, float)) else 0.0 for v in s.get("y", [])]
        if s.get("kind") == "bar":
            bar_w = max(step * 0.5, 2)
            for i, value in enumerate(values):
                bar_h = height * (value / y_max)
                bx = x + step * i - bar_w / 2 + (index - len(series) / 2 + 0.5) * bar_w * 0.5
                page.rect(bx, bottom, bar_w, bar_h, fill=color)
        else:
            points = [
                (x + step * i, bottom + height * (value / y_max)) for i, value in enumerate(values)
            ]
            page.polyline(points, color=color, width=1.3)
        page.text(x + 4, top - 8 - index * 8, str(s.get("label", "")), size=7, color=color)
    if payload.get("x_label"):
        page.text(x + 4, bottom + 3, str(payload["x_label"]), size=6.5, color=(0.45, 0.5, 0.58))
    return bottom - 16


def _hex_to_rgb(value: str) -> tuple[float, float, float]:
    value = value.lstrip("#")
    return tuple(int(value[i : i + 2], 16) / 255.0 for i in (0, 2, 4))  # type: ignore[return-value]


__all__ = [
    "Report",
    "ReportSection",
    "report_from_comparison",
    "report_from_evolution",
    "report_from_experiment",
    "report_from_hardware",
    "report_from_optimization",
    "report_from_result",
    "report_from_trace",
]
