"""The AI research assistant.

Design rule: **the assistant may not invent a number.**

The offline engine in this module is a deterministic reasoning layer over QScope
data.  It reads the circuit, the plan, the metrics, the noise model, the trace,
the optimizer verdict, the experiment rows and the benchmark measurements, and
answers questions by *computing from them* — decomposing error budgets, walking
the critical path, finding where entanglement first appears, fitting growth
exponents, and naming the exact quantity behind every sentence.

An optional LLM layer sits on top for fluent prose.  When configured, it receives
only the grounded digest (measured values, with their source), is instructed not
to introduce numbers, and its output is linted: any number in the narrative that
cannot be found in the digest is reported as a violation rather than shown as
fact.  With no LLM configured QScope still answers every question, offline.
"""

from __future__ import annotations

import json
import math
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol, Sequence

import numpy as np

from qscope.ai.knowledge import KnowledgeGraph, build_knowledge_graph

CONFIDENCE_MEASURED = "measured"
CONFIDENCE_DERIVED = "derived"
CONFIDENCE_ESTIMATED = "estimated"
CONFIDENCE_QUALITATIVE = "qualitative"


# ---------------------------------------------------------------------------
# optional LLM providers
# ---------------------------------------------------------------------------


class LLMProvider(Protocol):
    """Anything that can turn a grounded digest into prose."""

    name: str

    def available(self) -> bool: ...

    def complete(self, system: str, user: str) -> str: ...


class OpenAICompatibleProvider:
    """Any OpenAI-compatible ``/chat/completions`` endpoint, configured by env.

    ``QSCOPE_LLM_BASE_URL``, ``QSCOPE_LLM_API_KEY``, ``QSCOPE_LLM_MODEL``.
    Nothing is sent anywhere unless the user configures these, and a failure is
    reported rather than silently ignored.
    """

    name = "openai-compatible"

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.base_url = (base_url or os.environ.get("QSCOPE_LLM_BASE_URL", "")).rstrip("/")
        self.api_key = api_key or os.environ.get("QSCOPE_LLM_API_KEY", "")
        self.model = model or os.environ.get("QSCOPE_LLM_MODEL", "gpt-4o-mini")
        self.timeout = timeout

    def available(self) -> bool:
        return bool(self.base_url)

    def complete(self, system: str, user: str) -> str:
        if not self.available():
            raise RuntimeError("no LLM endpoint configured (set QSCOPE_LLM_BASE_URL)")
        payload = json.dumps(
            {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": 0.2,
            }
        ).encode()
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=payload,
            headers={
                "Content-Type": "application/json",
                **({"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}),
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = json.loads(response.read().decode())
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            raise RuntimeError(f"LLM request failed: {exc}") from exc
        try:
            return body["choices"][0]["message"]["content"].strip()
        except (KeyError, IndexError) as exc:
            raise RuntimeError(f"unexpected LLM response shape: {body}") from exc


SYSTEM_PROMPT = (
    "You are the QScope research assistant. You explain quantum simulation results.\n"
    "Hard rules:\n"
    "1. Use ONLY the numbers in the GROUNDED DATA block. Never compute, round to a new value, "
    "estimate or invent a number.\n"
    "2. If the data does not answer the question, say exactly what is missing.\n"
    "3. Never claim results from real quantum hardware: everything here is simulation unless the "
    "data says otherwise.\n"
    "4. Distinguish measured values from model estimates, and say which is which.\n"
    "5. Be concise and technical; no filler."
)


# ---------------------------------------------------------------------------
# context: everything the assistant is allowed to talk about
# ---------------------------------------------------------------------------


@dataclass
class ResearchContext:
    """The grounded evidence bundle the assistant reasons over."""

    circuit: Any | None = None
    result: Any | None = None
    ideal_result: Any | None = None
    trace: Any | None = None
    optimization: Any | None = None
    evolution: Any | None = None
    outcome: Any | None = None
    comparison: dict[str, Any] | None = None
    benchmark: dict[str, Any] | None = None
    hardware_report: dict[str, Any] | None = None
    stored: list[Any] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    # ------------------------------------------------------------- assembly

    def knowledge(self) -> KnowledgeGraph:
        return build_knowledge_graph(
            circuit=self.circuit,
            result=self.result,
            optimization=self.optimization,
            outcome=self.outcome,
            stored=self.stored,
            trace=self.trace,
        )

    def available_sources(self) -> list[str]:
        sources = []
        for name in ("circuit", "result", "ideal_result", "trace", "optimization", "evolution", "outcome", "comparison", "benchmark", "hardware_report"):
            if getattr(self, name) is not None:
                sources.append(name)
        if self.stored:
            sources.append(f"stored({len(self.stored)})")
        return sources

    def facts(self) -> list[dict[str, Any]]:
        """Flat list of ``{label, value, source, kind}`` used for citations."""
        facts: list[dict[str, Any]] = []

        def add(label: str, value: Any, source: str, kind: str = CONFIDENCE_MEASURED) -> None:
            facts.append({"label": label, "value": value, "source": source, "kind": kind})

        circuit = self.circuit or (getattr(self.result, "_circuit", None) if self.result else None)
        if self.circuit is not None:
            resources = self.circuit.resources()
            for key in ("num_qubits", "gates", "depth", "two_qubit_gates", "t_count", "operations", "measurements"):
                add(f"circuit.{key}", resources.get(key), "circuit.resources()")
            add("circuit.histogram", resources.get("histogram"), "circuit.resources()")
            add("circuit.critical_path", self.critical_path(), "circuit scheduling (computed)")
        if self.result is not None:
            timing = self.result.timing or {}
            plan = self.result.plan or {}
            add("run.backend", self.result.backend, "result.backend")
            add("run.mode", self.result.mode, "result.mode")
            add("run.representation", plan.get("representation"), "plan")
            add("run.exact", plan.get("exact"), "plan")
            add("run.shots", self.result.shots, "result.shots")
            add("run.total_seconds", timing.get("total_seconds"), "measured wall clock")
            add("run.operations_per_second", timing.get("operations_per_second"), "measured wall clock")
            add("run.state_mb", (self.result.memory or {}).get("state_mb"), "measured (numpy nbytes)")
            add("run.fidelity_vs_ideal", self.result.fidelity_vs_ideal, "analysis.fidelity")
            add("run.trace_distance_vs_ideal", self.result.trace_distance_vs_ideal, "analysis.fidelity")
            add("run.noise_model", (self.result.noise or {}).get("name"), "noise model")
            add("run.noise_channels", (self.result.noise or {}).get("channels"), "noise model")
            for key, value in (self.result.metrics or {}).items():
                add(f"metrics.{key}", value if not isinstance(value, dict) else json.dumps(value)[:400], "analysis.metrics")
            add("run.counts", self.result.counts, "measurement sampling")
            add("run.ideal_probabilities", self.result.ideal_probabilities, "Born rule on final state")
        if self.ideal_result is not None:
            add("ideal.fidelity_vs_ideal", self.ideal_result.fidelity_vs_ideal, "ideal reference run")
            for key in ("purity", "entropy", "dominant_basis", "dominant_probability"):
                add(f"ideal.{key}", (self.ideal_result.metrics or {}).get(key), "ideal reference run")
        if self.trace is not None:
            summary = self.trace.summary()
            add("trace.steps", summary.get("steps"), "debugger.trace")
            add("trace.layers", summary.get("layers"), "debugger.trace")
            add("trace.total_seconds", summary.get("total_seconds"), "debugger.trace")
            add("trace.slowest", summary.get("slowest_operation"), "debugger.trace")
            add("trace.largest_change", summary.get("largest_state_change"), "debugger.trace")
            add("trace.entanglement_created_at", summary.get("entanglement_created_at"), "debugger.trace")
        if self.optimization is not None:
            add("optimization.before", self.optimization.before, "optimizer.optimise")
            add("optimization.after", self.optimization.after, "optimizer.optimise")
            add("optimization.improvements", self.optimization.improvements, "optimizer.optimise")
            add("optimization.verification", self.optimization.verification, "optimizer verification")
            add("optimization.steps", [s.to_dict() for s in self.optimization.steps], "optimizer.optimise")
        if self.evolution is not None:
            add("evolution.candidates", [c.to_dict() for c in self.evolution.candidates], "evolution.rank")
            add("evolution.headline", self.evolution.headline(), "evolution.rank")
        if self.outcome is not None:
            add("experiment.spec", {k: v for k, v in self.outcome.spec.items() if k != "noise"}, "experiment spec")
            add("experiment.rows", [r.to_dict() for r in self.outcome.rows], "experiment runner")
            add("experiment.aggregates", self.outcome.aggregates, "experiment runner")
        if self.comparison is not None:
            add("comparison", self.comparison, "history.compare / runner.comparison")
        if self.benchmark is not None:
            add("benchmark", {k: v for k, v in self.benchmark.items() if k != "measurements"}, "benchmarks (measured)")
        if self.hardware_report is not None:
            add("hardware", self.hardware_report.get("hardware"), "hardware model")
            add("hardware.estimate", self.hardware_report.get("estimate_before_routing"), "ESTIMATED (model)")
            add("hardware.assumptions", (self.hardware_report.get("estimate_before_routing") or {}).get("assumptions"), "ESTIMATED (model)")
        for stored in self.stored:
            add(f"stored.{stored.experiment_id}", stored.to_dict(), "SQLite history")
        return facts

    # ------------------------------------------------------------ analysis

    def critical_path(self) -> dict[str, Any]:
        """The longest dependency chain, computed from per-wire finish times.

        QScope never claims this is the *minimum* depth — it is the depth of a
        specific greedy schedule, and the chain below is the sequence of gates
        that forces it.
        """
        if self.circuit is None:
            return {}
        n = self.circuit.num_qubits
        finish: dict[int, int] = {q: 0 for q in range(n)}
        last_on_wire: dict[int, int | None] = {q: None for q in range(n)}
        starts: list[int] = []
        ends: list[int] = []
        parents: list[list[int]] = []
        for index, op in enumerate(self.circuit.operations):
            wires = list(op.targets) + list(op.controls)
            if not wires:
                wires = list(range(n))
            start = max((finish.get(w, 0) for w in wires), default=0)
            parents.append([last_on_wire[w] for w in wires if last_on_wire.get(w) is not None and finish[w] == start])
            starts.append(start)
            for wire in wires:
                finish[wire] = start + 1
                last_on_wire[wire] = index
            ends.append(start + 1)
        if not ends:
            return {"length": 0, "gates": [], "histogram": {}, "ops_with_controls": 0}
        cursor: int | None = max(range(len(ends)), key=lambda i: (ends[i], -i))
        chain: list[int] = []
        while cursor is not None:
            chain.append(cursor)
            current = cursor
            cursor = None
            for parent in parents[current]:
                if ends[parent] == starts[current]:
                    cursor = parent
                    break
        chain.reverse()
        path = [
            {
                "index": index,
                "display": self.circuit.operations[index].display,
                "targets": list(self.circuit.operations[index].targets),
                "depth": ends[index],
            }
            for index in chain
        ]
        histogram: dict[str, int] = {}
        for entry in path:
            head = entry["display"].split("(")[0].strip()
            histogram[head] = histogram.get(head, 0) + 1
        return {
            "length": len(path),
            "gates": path,
            "histogram": histogram,
            "scheduled_depth": max(ends),
            "ops_with_controls": sum(1 for op in self.circuit.operations if op.controls),
        }

    def token_summary(self) -> str:
        """Compact human-readable digest for an LLM prompt."""
        lines: list[str] = []
        for fact in self.facts():
            value = fact["value"]
            if isinstance(value, (dict, list)):
                text = json.dumps(value, default=str)
                if len(text) > 900:
                    text = text[:900] + "…"
            else:
                text = str(value)
            lines.append(f"- {fact['label']} = {text}   [{fact['kind']}; {fact['source']}]")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# answer object
# ---------------------------------------------------------------------------


@dataclass
class Answer:
    """A grounded answer, with the evidence that produced it."""

    question: str
    intent: str
    title: str
    body: str
    bullets: list[str] = field(default_factory=list)
    citations: list[dict[str, Any]] = field(default_factory=list)
    confidence: str = CONFIDENCE_DERIVED
    limitations: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    narrative: str | None = None
    narrative_provider: str | None = None
    narrative_violations: list[str] = field(default_factory=list)
    narrative_error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "intent": self.intent,
            "title": self.title,
            "body": self.body,
            "bullets": self.bullets,
            "citations": self.citations,
            "confidence": self.confidence,
            "limitations": self.limitations,
            "suggestions": self.suggestions,
            "narrative": self.narrative,
            "narrative_provider": self.narrative_provider,
            "narrative_violations": self.narrative_violations,
            "narrative_error": self.narrative_error,
        }

    def to_text(self) -> str:
        parts = [self.title, "", self.body]
        if self.bullets:
            parts.append("")
            parts.extend(f"· {b}" for b in self.bullets)
        parts.append("")
        parts.append(f"[{self.confidence}] evidence: " + ", ".join(f"{c['label']}={c['value']}" for c in self.citations[:8]))
        if self.limitations:
            parts.append("limitations: " + " | ".join(self.limitations))
        if self.narrative:
            parts.append("")
            parts.append(self.narrative)
        return "\n".join(parts)


# ---------------------------------------------------------------------------
# intent routing
# ---------------------------------------------------------------------------

INTENTS: list[tuple[str, tuple[str, ...]]] = [
    ("fidelity", ("fidelity", "decrease", "dropped", "why is the result wrong", "error", "degrad", "noise affect", "trustworthy")),
    ("depth", ("depth", "contribut", "most expensive", "critical path", "longest", "dominant gate")),
    ("probability", ("50/50", "50-50", "probabilit", "why is", "distribution", "histogram", "dominant outcome")),
    ("entanglement", ("entangl", "concurrence", "bell", "correlat", "where is")),
    ("optimization", ("optimi", "simplif", "reduce", "fewer gates", "shorter")),
    ("noise", ("noise", "depolar", "damping", "decoher", "t1", "t2", "readout")),
    ("performance", ("runtime", "performance", "slow", "memory", "scal", "fast", "cost")),
    ("comparison", ("compare", "versus", " vs ", "better", "difference between")),
    ("hardware", ("hardware", "topology", "coupl", "swap", "device", "routing")),
    ("hypothesis", ("hypothes", "test", "next experiment", "what should i")),
    ("beginner", ("beginner", "simple terms", "eli5", "plain english", "explain this circuit like")),
    ("mathematical", ("mathematic", "unitary", "matrix", "formally", "amplitude")),
]


def classify(question: str) -> str:
    text = question.lower().strip()
    for intent, keys in INTENTS:
        for key in keys:
            if key in text:
                return intent
    return "overview"


# ---------------------------------------------------------------------------
# main entry point
# ---------------------------------------------------------------------------


def ask(
    question: str,
    context: ResearchContext,
    *,
    provider: LLMProvider | None = None,
    use_llm: bool = False,
) -> Answer:
    """Answer a question from grounded QScope data, optionally narrated by an LLM."""
    intent = classify(question)
    handler: Callable[[str, ResearchContext], Answer] = _HANDLERS.get(intent, _answer_overview)
    answer = handler(question, context)
    if use_llm:
        active = provider if provider is not None else OpenAICompatibleProvider()
        _narrate(answer, context, active)
    return answer


def _narrate(answer: Answer, context: ResearchContext, provider: LLMProvider) -> None:
    if not provider.available():
        answer.narrative_error = (
            "no LLM configured; the computed answer above is complete on its own "
            "(set QSCOPE_LLM_BASE_URL to enable narration)"
        )
        return
    digest = context.token_summary()
    user = (
        f"QUESTION: {answer.question}\n\n"
        f"GROUNDED DATA (the only numbers you may use):\n{digest}\n\n"
        f"COMPUTED ANSWER (already correct; rewrite it fluently without changing any number):\n"
        f"{answer.to_text()}"
    )
    try:
        text = provider.complete(SYSTEM_PROMPT, user)
    except Exception as exc:  # provider failures must never break the answer
        answer.narrative_error = str(exc)
        return
    allowed = _allowed_numbers(digest + " " + answer.to_text())
    violations = [n for n in _numbers_in(text) if n not in allowed]
    answer.narrative = text
    answer.narrative_provider = provider.name
    answer.narrative_violations = violations
    if violations:
        answer.limitations = answer.limitations + [
            "The LLM narrative introduced numbers absent from the grounded data "
            f"({', '.join(violations[:6])}); treat those as unverified."
        ]


def _numbers_in(text: str) -> list[str]:
    return re.findall(r"-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?", text)


def _allowed_numbers(text: str) -> set[str]:
    allowed: set[str] = set()
    for raw in _numbers_in(text):
        allowed.add(raw)
        try:
            value = float(raw)
        except ValueError:
            continue
        # Accept reasonable textual renderings of the same magnitude.
        for digits in (0, 1, 2, 3, 4, 6):
            allowed.add(f"{value:.{digits}f}")
            allowed.add(f"{value:.{digits}g}")
        allowed.add(str(int(value)))
    return allowed


def _cite(context: ResearchContext, *labels: str) -> list[dict[str, Any]]:
    """Pull the exact facts referenced by an answer (so every claim is traceable)."""
    facts = {f["label"]: f for f in context.facts()}
    out = []
    for label in labels:
        fact = facts.get(label)
        if fact is None:
            continue
        value = fact["value"]
        if isinstance(value, (dict, list)):
            text = json.dumps(value, default=str)
            value = text if len(text) <= 160 else text[:157] + "…"
        out.append({"label": label, "value": value, "source": fact["source"], "kind": fact["kind"]})
    return out


# ---------------------------------------------------------------------------
# handlers
# ---------------------------------------------------------------------------


def _answer_fidelity(question: str, context: ResearchContext) -> Answer:
    result = context.result
    if result is None:
        return _missing(question, "fidelity", "a completed run (no simulation result is in context)")
    metrics = result.metrics or {}
    noise = result.noise or {}
    bullets: list[str] = []
    limitations: list[str] = []
    fidelity = result.fidelity_vs_ideal
    if fidelity is None:
        body = (
            f"This run has no ideal reference to compare against, so a fidelity decrease cannot be "
            f"quantified. The run is {result.mode} on the {result.backend} engine, and its state "
            f"purity is {metrics.get('purity'):.6f}."
            if metrics.get("purity") is not None
            else "This run has no ideal reference, so fidelity against ideal is undefined here."
        )
        return Answer(
            question=question,
            intent="fidelity",
            title="Fidelity cannot be quantified for this run",
            body=body,
            citations=_cite(context, "run.mode", "run.backend", "metrics.purity"),
            confidence=CONFIDENCE_QUALITATIVE,
            limitations=["No ideal (noiseless) reference run is in context."],
        )

    body = (
        f"State fidelity against the ideal reference is {fidelity:.6f} "
        f"(trace distance {result.trace_distance_vs_ideal:.6f}), so the run deviates from the ideal "
        f"state by {1 - fidelity:.6f} in fidelity terms."
    )
    bullets.append(f"engine: {result.backend} ({result.mode}); exact={result.plan.get('exact')}")
    if metrics.get("purity") is not None:
        ideal_purity = (result.ideal_metrics or {}).get("purity")
        bullets.append(
            f"purity {metrics['purity']:.6f}"
            + (f" vs ideal {ideal_purity:.6f}" if isinstance(ideal_purity, (int, float)) else "")
            + (" — pure states only reach purity 1" if result.backend == "density_matrix" else "")
        )
    if metrics.get("entropy") is not None:
        bullets.append(f"von Neumann entropy {metrics['entropy']:.6f} bits")

    channels = noise.get("channels") or []
    if channels:
        bullets.append("active noise channels:")
        for channel in channels:
            scope = channel.get("scope", "all")
            qubits = channel.get("qubits")
            where = f"qubits {qubits}" if qubits else f"scope {scope}"
            param_text = ", ".join(f"{k}={v}" for k, v in (channel.get("params") or {}).items())
            bullets.append(f"  {channel.get('kind')} ({param_text}) on {where}")
        strength = sorted(
            (
                (max(float(v) for v in (c.get("params") or {}).values() if isinstance(v, (int, float))), c)
                for c in channels
                if any(isinstance(v, (int, float)) for v in (c.get("params") or {}).values())
            ),
            key=lambda item: -item[0],
        )
        if strength:
            strongest = strength[0][1]
            bullets.append(
                f"strongest single channel: {strongest.get('kind')} "
                f"({max(float(v) for v in (strongest.get('params') or {}).values() if isinstance(v, (int, float))):.4g})"
            )
        limitations.append("Channel ordering is by parameter magnitude, not a formal error decomposition.")
    else:
        bullets.append("no noise channels are active in this model")

    two_q = (context.circuit.resources().get("two_qubit_gates") if context.circuit else None)
    if two_q is not None:
        bullets.append(
            f"{two_q} two-qubit gates — in this noise model the error applied per two-qubit gate is "
            f"{noise.get('two_qubit_gate_error') or 0:.6g}"
        )
    if noise.get("readout_error"):
        bullets.append(f"readout error {noise['readout_error']:.6g} applied at measurement")

    limitations.extend(result.warnings or [])
    if result.backend == "trajectory":
        limitations.append(
            f"Trajectory sampling has ~1/sqrt({result.shots}) statistical error; a single trajectory is "
            "one stochastic draw, not the ensemble average."
        )
    if noise.get("approximate"):
        limitations.append("The noise model is flagged approximate by its author.")
    limitations.append("Simulated degradation only — this is not a hardware fidelity measurement.")

    suggestions = [
        "Re-run on the density-matrix engine for the exact mixed state.",
        "Sweep the noise strength to see the degradation curve (noise_sweep experiment).",
        "Optimize the circuit to remove two-qubit gates, which dominate gate error.",
    ]
    return Answer(
        question=question,
        intent="fidelity",
        title="Why the fidelity decreased — error budget",
        body=body,
        bullets=bullets,
        citations=_cite(
            context,
            "run.fidelity_vs_ideal",
            "run.trace_distance_vs_ideal",
            "metrics.purity",
            "metrics.entropy",
            "run.noise_model",
            "run.noise_channels",
            "run.backend",
        ),
        confidence=CONFIDENCE_MEASURED if result.backend == "density_matrix" else CONFIDENCE_ESTIMATED,
        limitations=limitations,
        suggestions=suggestions,
    )


def _answer_depth(question: str, context: ResearchContext) -> Answer:
    if context.circuit is None:
        return _missing(question, "depth", "a circuit")
    resources = context.circuit.resources()
    path = context.critical_path()
    histogram = resources.get("histogram") or {}
    bullets = [
        f"gate histogram: " + ", ".join(f"{k}×{v}" for k, v in sorted(histogram.items(), key=lambda kv: -kv[1])),
        f"two-qubit gates: {resources.get('two_qubit_gates')} (these set the depth floor: a layer can hold at "
        f"most one two-qubit gate per disjoint pair, so depth >= two-qubit gate count / max matching)",
        f"measurements: {resources.get('measurements')} (do not contribute to gate depth)",
        f"unused qubits: {resources.get('unused_qubits') or 'none'}",
    ]
    if path:
        top = path["histogram"]
        bullets.append(
            "longest dependency chain: "
            + ", ".join(f"{k}×{v}" for k, v in sorted(top.items(), key=lambda kv: -kv[1]))
            + f" (length {path['length']})"
        )
        bullets.append(
            "chain order: " + " → ".join(entry["display"] for entry in path["gates"][:14])
            + (" …" if len(path["gates"]) > 14 else "")
        )
    if context.optimization is not None:
        bullets.append(
            f"optimizer verdict: {context.optimization.headline()} "
            f"(verification: {context.optimization.verification.get('status')})"
        )
    body = (
        f"The circuit has {resources.get('gates')} gates over {resources.get('depth')} layers on "
        f"{resources.get('num_qubits')} qubits. Depth is bounded below by the longest dependency chain, "
        f"not by the gate count."
    )
    return Answer(
        question=question,
        intent="depth",
        title="What contributes to depth",
        body=body,
        bullets=bullets,
        citations=_cite(context, "circuit.gates", "circuit.depth", "circuit.two_qubit_gates", "circuit.histogram", "circuit.critical_path"),
        confidence=CONFIDENCE_DERIVED,
        limitations=[
            "Depth is computed by a greedy left-to-right scheduler; a different schedule can sometimes be "
            "one layer shorter (QScope never claims the absolute minimum).",
        ],
        suggestions=["Ask the optimizer to restructure the circuit", "Inspect the trace to see which layer dominates wall-clock time"],
    )


def _answer_probability(question: str, context: ResearchContext) -> Answer:
    if context.result is None and context.outcome is None:
        return _missing(question, "probability", "a completed run or experiment")
    bullets: list[str] = []
    if context.result is not None:
        result = context.result
        probs = result.ideal_probabilities or {}
        top = sorted(probs.items(), key=lambda kv: -kv[1])[:6]
        counts = result.counts or {}
        total = sum(counts.values()) or 1
        bullets.append(
            "exact Born distribution (top): "
            + ", ".join(f"|{k}⟩ {v:.4f}" for k, v in top)
        )
        bullets.append(
            "measured (top): "
            + ", ".join(f"|{k}⟩ {counts.get(k, 0) / total:.4f}" for k, _ in top)
        )
        dominant = (result.metrics or {}).get("dominant_basis")
        metrics = result.metrics or {}
        if dominant:
            bullets.append(
                f"dominant basis state {dominant} at {metrics.get('dominant_probability', 0):.4f}; "
                f"support size {metrics.get('support_size')} of {2 ** (context.circuit.num_qubits if context.circuit else 0)}"
            )
        if metrics.get("support_size") == 1:
            bullets.append("the state is a single computational basis state — no superposition remains (a measurement has collapsed it, or the circuit computed a classical function)")
        entanglement = metrics.get("entanglement_status")
        if entanglement:
            bullets.append(f"entanglement: {entanglement}")
        body = (
            f"The distribution comes from the Born rule |⟨x|ψ⟩|² on the final state. "
            f"{'The two outcomes are close to equal, which is what an even superposition predicts.' if _is_near_5050(probs) else 'The distribution is not even; the amplitudes interfere toward the listed outcomes.'}"
        )
    else:
        rows = context.outcome.rows
        body = f"The experiment recorded {len(rows)} parameter points; per-point distributions are in the row data."
        for row in rows[:8]:
            top = sorted(row.counts.items(), key=lambda kv: -kv[1])[:3]
            bullets.append(f"{row.label}: " + ", ".join(f"|{k}⟩ {v / max(sum(row.counts.values()), 1):.3f}" for k, v in top))
    return Answer(
        question=question,
        intent="probability",
        title="Where the probabilities come from",
        body=body,
        bullets=bullets,
        citations=_cite(context, "run.ideal_probabilities", "run.counts", "metrics.dominant_basis", "metrics.dominant_probability", "metrics.support_size", "metrics.entanglement_status"),
        confidence=CONFIDENCE_MEASURED,
        limitations=["Exact probabilities are properties of the final state; measured frequencies carry 1/sqrt(shots) shot noise."],
        suggestions=["Ask for the Quantum Diff at the gate where the distribution changed most", "Increase shots to tighten the measured frequencies"],
    )


def _is_near_5050(probabilities: dict[str, float]) -> bool:
    values = sorted(probabilities.values(), reverse=True)
    if len(values) < 2:
        return False
    return abs(values[0] - values[1]) < 0.05 and len([v for v in values if v > 0.01]) == 2


def _answer_entanglement(question: str, context: ResearchContext) -> Answer:
    bullets: list[str] = []
    limitations: list[str] = []
    body = "Entanglement detection uses reduced density matrices: purity and entropy of each single qubit, and concurrence on every pair."
    citations = _cite(context, "metrics.entanglement_status", "trace.entanglement_created_at", "metrics.entanglement")

    if context.trace is not None:
        summary = context.trace.summary()
        created = summary.get("entanglement_created_at") or []
        if created:
            bullets.append("entanglement first appeared at:")
            for entry in created[:6]:
                bullets.append(
                    f"  step {entry.get('index')} {entry.get('display')} on wires {entry.get('targets')} "
                    f"(Δ entropy {entry.get('delta_entropy')})"
                )
        else:
            bullets.append("no step in the trace created entanglement according to the per-step diff")
        bullets.append(f"final entanglement: {summary.get('final_entanglement_status')}")
    if context.result is not None:
        metrics = context.result.metrics or {}
        entanglement = metrics.get("entanglement") or {}
        bullets.append(f"status after the run: {metrics.get('entanglement_status')}")
        pairs = entanglement.get("pairs") or []
        if pairs:
            ranked = sorted(pairs, key=lambda p: -(p.get("concurrence") or 0.0))[:6]
            bullets.append("strongest pairwise entanglement (concurrence, negativity):")
            for pair in ranked:
                bullets.append(
                    f"  q{pair.get('a')}–q{pair.get('b')}: {pair.get('concurrence'):.4f}, "
                    f"{pair.get('negativity'):.4f} "
                    f"(entanglement of formation {pair.get('entanglement_of_formation'):.4f})"
                )
        per_qubit = entanglement.get("per_qubit_entropy") or []
        if per_qubit:
            worst = max(per_qubit, key=lambda p: p.get("entanglement_entropy") or 0.0)
            bullets.append(
                f"most entangled qubit with the rest: q{worst.get('qubit')} "
                f"(entropy {worst.get('entanglement_entropy'):.4f} bits)"
            )
        if entanglement.get("limitations"):
            limitations.extend(entanglement["limitations"])
    if context.circuit is not None:
        entanglers = [op.display for op in context.circuit.operations if op.controls and op.name in {"CX", "CNOT", "CZ", "CY", "SWAP", "RXX", "RYY", "RZZ", "RZX", "CCX", "TOFFOLI"}]
        bullets.append(f"{len(entanglers)} entangling operations in the circuit: " + ", ".join(entanglers[:10]) + (" …" if len(entanglers) > 10 else ""))
    if not limitations:
        limitations.append(
            "Single-qubit entropy is an exact entanglement measure only for a pure global state; for mixed "
            "states the concurrence/negativity values are the reliable indicators."
        )
    return Answer(
        question=question,
        intent="entanglement",
        title="Where entanglement is created",
        body=body,
        bullets=bullets,
        citations=citations,
        confidence=CONFIDENCE_MEASURED,
        limitations=limitations,
        suggestions=["Ask for the entanglement map to see all pairs", "Compare against an ideal run with no noise"],
    )


def _answer_optimization(question: str, context: ResearchContext) -> Answer:
    optimization = context.optimization
    if optimization is None and context.circuit is not None:
        from qscope.optimizer.optimizer import optimise

        optimization = optimise(context.circuit, level="standard")
    if optimization is None:
        return _missing(question, "optimization", "a circuit to optimize")
    before, after, imp = optimization.before, optimization.after, optimization.improvements
    bullets = [
        f"gates {before['gates']} → {after['gates']} ({imp['gates_percent']:.1f}%)",
        f"depth {before['depth']} → {after['depth']} ({imp['depth_percent']:.1f}%)",
        f"two-qubit gates {before['two_qubit_gates']} → {after['two_qubit_gates']}",
        f"T-count {before['t_count']} → {after['t_count']}",
        f"verification: {optimization.verification.get('status')} ({optimization.verification.get('method')})",
    ]
    for step in optimization.steps[:8]:
        bullets.append(
            f"rewrite {step.rule}: {step.description} — removed {', '.join(step.removed) or 'nothing'}, "
            f"added {', '.join(step.added) or 'nothing'} ({step.reasoning})"
        )
    if not optimization.steps:
        bullets.append("no rewrite applied: this circuit is already minimal for the enabled rule set")
    body = (
        f"The optimizer found {imp['gates_saved']} removable gates. "
        + (f"It saved {imp['two_qubit_gates_saved']} two-qubit gates, which matter most on real hardware."
           if imp.get("two_qubit_gates_saved") else "No two-qubit gate reduction was possible without changing the computation.")
        + f" Verification status: {optimization.verification.get('status')}."
    )
    limitations = list(optimization.verification.get("limitations", []))
    limitations.append("Optimization is exact but greedy: a different rule order might remove more.")
    return Answer(
        question=question,
        intent="optimization",
        title="Optimization opportunity",
        body=body,
        bullets=bullets,
        citations=_cite(context, "optimization.before", "optimization.after", "optimization.improvements", "optimization.verification"),
        confidence=CONFIDENCE_MEASURED if optimization.verification.get("status", "").startswith("verified") else CONFIDENCE_DERIVED,
        limitations=limitations,
        suggestions=["Run the optimization study experiment to measure the effect on fidelity", "Try the aggressive rule set"],
    )


def _answer_noise(question: str, context: ResearchContext) -> Answer:
    result = context.result
    noise = (result.noise if result else None) or {}
    if not noise and context.hardware_report is None:
        return _missing(question, "noise", "a run with a noise model, or a hardware model")
    bullets: list[str] = []
    limitations: list[str] = []
    for channel in noise.get("channels") or []:
        bullets.append(
            f"{channel.get('kind')} on {channel.get('qubits') or channel.get('scope', 'all')}: "
            + ", ".join(f"{k}={v}" for k, v in (channel.get("params") or {}).items())
        )
    if noise.get("readout_error"):
        bullets.append(f"readout: symmetric bit-flip with probability {noise['readout_error']}")
    for label, key in (("one-qubit gate error", "one_qubit_gate_error"), ("two-qubit gate error", "two_qubit_gate_error"), ("idle error", "idle_error")):
        if noise.get(key):
            bullets.append(f"{label}: {noise[key]}")
    if context.hardware_report is not None:
        estimate = context.hardware_report.get("estimate_before_routing") or {}
        bullets.append(
            f"hardware model estimate: success {estimate.get('estimated_success_probability'):.4f} "
            f"(gate {estimate.get('contributors', {}).get('gate_errors'):.4g}, "
            f"readout {estimate.get('contributors', {}).get('readout_errors'):.4g}, "
            f"decoherence {estimate.get('contributors', {}).get('decoherence'):.4g}); "
            f"dominant: {estimate.get('dominant_contributor')}"
        )
        limitations.extend(estimate.get("assumptions", []))
    if result is not None:
        bullets.append(f"noise is applied as {noise.get('description') or 'per-gate channels'}")
        bullets.append(
            f"engine {result.backend} ({result.mode}), exact={result.plan.get('exact')} — "
            + ("exact mixed-state evolution" if result.backend == "density_matrix" else
               "sampled trajectories" if result.backend == "trajectory" else "no noise is representable")
        )
    if noise.get("calibrated") is False:
        limitations.append("The channel parameters are illustrative, not device-calibrated.")
    body = (
        "This is a configured noise model applied inside the simulation — not a hardware measurement. "
        "QScope labels it NOISY SIMULATION everywhere it appears."
    )
    return Answer(
        question=question,
        intent="noise",
        title="What noise is doing here",
        body=body,
        bullets=bullets,
        citations=_cite(context, "run.noise_model", "run.noise_channels", "run.backend", "hardware.estimate"),
        confidence=CONFIDENCE_ESTIMATED,
        limitations=limitations + ["Model-based reasoning only; no hardware data is involved."],
        suggestions=["Run a noise sweep to get the degradation curve", "Compare against the same circuit with the ideal model"],
    )


def _answer_performance(question: str, context: ResearchContext) -> Answer:
    bullets: list[str] = []
    limitations: list[str] = []
    body_parts: list[str] = []
    if context.result is not None:
        timing = context.result.timing or {}
        resources = context.circuit.resources() if context.circuit else {}
        body_parts.append(
            f"This run took {timing.get('total_seconds', 0):.6f} s for {timing.get('operations', 0)} operations "
            f"({(timing.get('operations_per_second') or 0):.0f} ops/s)."
        )
        bullets.append(f"state memory {((context.result.memory or {}).get('state_mb') or 0):.6f} MB")
        if resources:
            bullets.append(f"gates {resources.get('gates')} over depth {resources.get('depth')} on {resources.get('num_qubits')} qubits")
        per_op = timing.get("per_operation") or []
        if per_op:
            slowest = max(per_op, key=lambda op: op["seconds"])
            bullets.append(f"slowest single operation: #{slowest['index']} {slowest['display']} ({slowest['seconds']:.6f} s)")
        limitations.append("Wall-clock timings are single-process and machine-specific; they are not a cross-platform benchmark.")
        limitations.append("Per-operation timings come from one pass and include Python dispatch overhead.")
    if context.outcome is not None:
        growth = (context.outcome.aggregates or {}).get("growth")
        rows = context.outcome.rows
        if rows:
            bullets.append(
                "measured runtime across the sweep: "
                + ", ".join(f"{r.label} → {r.runtime_seconds:.4f} s" for r in rows[:8])
            )
        if growth:
            body_parts.append(
                f"Runtime grew {growth['runtime_ratio']:.2f}× across the sweep"
                + (f" ({growth['seconds_per_added_qubit']:.6f} s per added qubit)." if growth.get("seconds_per_added_qubit") else ".")
            )
            limitations.append(growth.get("note", ""))
        exponent = _scaling_exponent(rows)
        if exponent is not None:
            bullets.append(
                f"log-log fit of runtime against qubit count: exponent {exponent:.3f} "
                "(2.0 or higher is the expected classical-simulation regime; a value near 1 means this size "
                "range is still dominated by constant overhead)"
            )
    if context.benchmark is not None:
        for key, value in context.benchmark.items():
            if key in {"measurements", "notes"}:
                continue
            bullets.append(f"benchmark.{key}: {json.dumps(value, default=str)[:200]}")
    if not body_parts:
        return _missing(question, "performance", "a run or experiment with timing data")
    return Answer(
        question=question,
        intent="performance",
        title="Performance and scaling",
        body=" ".join(body_parts),
        bullets=bullets,
        citations=_cite(context, "run.total_seconds", "run.operations_per_second", "run.state_mb", "circuit.gates", "circuit.depth"),
        confidence=CONFIDENCE_MEASURED,
        limitations=[l for l in limitations if l],
        suggestions=["Benchmark the scaling curve to see where the memory wall is", "Compare engines on the same circuit"],
    )


def _scaling_exponent(rows: Sequence[Any]) -> float | None:
    pairs = [(r.qubits, r.runtime_seconds) for r in rows if r.runtime_seconds and r.runtime_seconds > 0 and r.qubits]
    if len(pairs) < 3:
        return None
    x = np.log(np.array([p[0] for p in pairs], dtype=float))
    y = np.log(np.array([p[1] for p in pairs], dtype=float))
    if np.ptp(x) == 0:
        return None
    slope = float(np.polyfit(x, y, 1)[0])
    return slope


def _answer_comparison(question: str, context: ResearchContext) -> Answer:
    comparison = context.comparison
    if comparison is None:
        return _missing(question, "comparison", "two circuits or two stored experiments")
    if "resource_rows" in comparison:
        rows = comparison["resource_rows"] + comparison["metric_rows"]
        name_a = comparison["circuit_a"]["name"]
        name_b = comparison["circuit_b"]["name"]
        bullets = [
            f"{row['metric']}: {row['a']} → {row['b']} (Δ {row['delta']})"
            for row in rows
            if row.get("delta") not in (None, 0)
        ]
        body = " ".join(comparison.get("verdict", [])) or "Comparison complete."
        if comparison.get("output_total_variation") is not None:
            body += f" Output distributions differ by {comparison['output_total_variation']:.4f} (total variation)."
        return Answer(
            question=question,
            intent="comparison",
            title=f"{name_a} vs {name_b}",
            body=body,
            bullets=bullets,
            citations=_cite(context, "comparison"),
            confidence=CONFIDENCE_MEASURED,
            limitations=["Resource counts are gate-model counts; a device may need extra routing gates."],
        )
    bullets = [f"{row['metric']}: " + " vs ".join(str(v) for v in row["values"]) for row in comparison.get("rows", [])]
    return Answer(
        question=question,
        intent="comparison",
        title="Experiment comparison",
        body=" ".join(comparison.get("verdict", [])) or "Comparison complete.",
        bullets=bullets,
        citations=_cite(context, "comparison"),
        confidence=CONFIDENCE_MEASURED,
        limitations=["Runtimes from different engines represent different physics and are not directly comparable."],
    )


def _answer_hardware(question: str, context: ResearchContext) -> Answer:
    report = context.hardware_report
    if report is None:
        return _missing(question, "hardware", "a circuit analysed against a hardware model")
    hardware = report["hardware"]
    estimate = report["estimate_before_routing"]
    bullets = [
        f"device {hardware['name']} ({hardware['source']}): {hardware['num_qubits']} qubits, "
        f"median degree {hardware['topology'].get('median_degree')}",
        f"connectivity violations: {len(report.get('connectivity_violations', []))}",
        f"unsupported gates: {len(report.get('unsupported_gates', []))}",
        f"estimated success {estimate['estimated_success_probability']:.4f}, dominant contributor {estimate['dominant_contributor']}",
    ]
    if report.get("routing"):
        routing = report["routing"]
        bullets.append(
            f"routing: {routing['swaps_inserted']} SWAPs inserted, depth {routing['depth_before']} → "
            f"{routing['depth_after']} ({routing['depth_overhead_percent']:.1f}% overhead)"
        )
    return Answer(
        question=question,
        intent="hardware",
        title="Hardware feasibility (model estimate)",
        body=(
            "This is an ESTIMATE from a device model, not a hardware measurement. It tells you whether the "
            "circuit is even expressible on the topology, and roughly how much success probability the device "
            "parameters would cost."
        ),
        bullets=bullets,
        citations=_cite(context, "hardware", "hardware.estimate", "hardware.assumptions"),
        confidence=CONFIDENCE_ESTIMATED,
        limitations=estimate.get("assumptions", []) + ["No hardware was contacted or used."],
        suggestions=["Optimize the circuit first, then re-run the hardware analysis", "Try a device with higher connectivity"],
    )


def _answer_hypothesis(question: str, context: ResearchContext) -> Answer:
    hypotheses: list[str] = []
    designs: list[str] = []
    if context.outcome is not None:
        spec = context.outcome.spec
        rows = context.outcome.rows
        if rows:
            best = max(rows, key=lambda r: r.success_probability if r.success_probability is not None else -1)
            hypotheses.append(
                f"The success probability peaks at {best.label} ({best.success_probability}); "
                f"a follow-up that doubles shots there would separate sampling error from systematic error."
            )
            noisy = [r for r in rows if r.fidelity_vs_ideal is not None]
            if noisy:
                worst = min(noisy, key=lambda r: r.fidelity_vs_ideal)
                hypotheses.append(
                    f"Fidelity is lowest at {worst.label} ({worst.fidelity_vs_ideal:.4f}); if the dominant noise "
                    "channel is a single-qubit channel, the loss should scale with gate count, not depth — "
                    "testable by comparing two circuits with equal gate counts and different depths."
                )
            exponent = _scaling_exponent(rows)
            if exponent is not None:
                hypotheses.append(
                    f"The runtime exponent is {exponent:.3f} over the sampled sizes; extending the sweep one size "
                    "further would confirm whether it has reached the 2^n regime."
                )
            designs.append(
                f"kind: {spec.get('kind')}, axes: " + "; ".join(
                    f"{a['label']} ∈ {a['values']}" for a in spec.get("axes", [])
                )
            )
            designs.append(f"fixed: {json.dumps(spec.get('fixed', {}))}")
            designs.append(f"shots: {spec.get('shots')}, seed: {spec.get('seed')}, noise: {spec.get('noise', {}).get('name')}")
    if context.optimization is not None:
        hypotheses.append(
            f"The optimizer removed {context.optimization.improvements['gates_saved']} gates with verification "
            f"'{context.optimization.verification.get('status')}'; the hypothesis that gate count (not depth) "
            "controls fidelity in this noise model can be tested by running both circuits under identical noise."
        )
    if not hypotheses:
        return _missing(question, "hypothesis", "an experiment or optimization to reason about")
    body = (
        "These are testable hypotheses derived from the recorded numbers. Each one names the quantity to measure "
        "and the comparison that would falsify it."
    )
    return Answer(
        question=question,
        intent="hypothesis",
        title="Hypotheses you can test next",
        body=body,
        bullets=hypotheses + (["reproduction recipe: " + " | ".join(designs)] if designs else []),
        citations=_cite(context, "experiment.aggregates", "experiment.spec", "optimization.improvements"),
        confidence=CONFIDENCE_DERIVED,
        limitations=["Hypotheses are suggestions grounded in the data, not conclusions; each needs a new run to confirm."],
        suggestions=["Run the suggested sweep", "Compare the hypothesis against the stored history"],
    )


def _answer_beginner(question: str, context: ResearchContext) -> Answer:
    bullets: list[str] = []
    if context.circuit is not None:
        circuit = context.circuit
        bullets.append(f"this circuit uses {circuit.num_qubits} qubits and {circuit.gate_count()} quantum operations")
        bullets.append("each gate is a physical instruction that rotates or links those qubits:")
        for op in circuit.operations[:14]:
            bullets.append(f"  {op.display} — " + _plain_gate(op.name))
        if len(circuit.operations) > 14:
            bullets.append(f"  … and {len(circuit.operations) - 14} more")
    if context.result is not None:
        counts = context.result.counts
        total = sum(counts.values()) or 1
        top = sorted(counts.items(), key=lambda kv: -kv[1])[:4]
        bullets.append("when the circuit was run and measured many times, the outcomes were:")
        for outcome, count in top:
            bullets.append(f"  '{outcome}' came up {count} times out of {total} ({count / total:.1%})")
        metrics = context.result.metrics or {}
        if metrics.get("entanglement_status"):
            bullets.append(
                "entanglement check: " + metrics["entanglement_status"].lower()
                + " — entangled qubits cannot be described independently, which is the property that makes "
                "quantum computers different from classical ones"
            )
    body = (
        "In plain terms: the circuit prepares qubits, applies gates in order, and then measures. "
        "The output is a probability distribution over bitstrings, not a single answer — you read it by "
        "looking at which bitstrings are most likely."
    )
    return Answer(
        question=question,
        intent="beginner",
        title="The circuit in plain language",
        body=body,
        bullets=bullets,
        citations=_cite(context, "circuit.gates", "circuit.depth", "run.counts", "metrics.entanglement_status"),
        confidence=CONFIDENCE_QUALITATIVE,
        limitations=["This is a pedagogical explanation of simulation output, not a hardware description."],
    )


_PLAIN_GATES = {
    "H": "puts a qubit into an even superposition of 0 and 1",
    "X": "flips a qubit (quantum NOT)",
    "Y": "flips a qubit with a phase twist",
    "Z": "flips the phase of the 1 component",
    "S": "quarter-turn phase gate",
    "T": "eighth-turn phase gate",
    "RX": "rotates a qubit about the X axis by the given angle",
    "RY": "rotates a qubit about the Y axis by the given angle",
    "RZ": "rotates a qubit about the Z axis by the given angle",
    "CX": "controlled-NOT: flips the target only when the control is 1 — this creates entanglement",
    "CNOT": "controlled-NOT: flips the target only when the control is 1 — this creates entanglement",
    "CZ": "controlled phase flip — entangles two qubits without flipping either",
    "SWAP": "exchanges the states of two qubits",
    "CCX": "Toffoli: flips the target only when both controls are 1",
    "MEASURE": "reads a qubit out as a classical bit, collapsing it",
    "BARRIER": "a scheduling hint; it does not change the state",
    "RESET": "returns a qubit to |0>",
}


def _plain_gate(name: str) -> str:
    return _PLAIN_GATES.get(name, "a gate whose exact action is listed in the gate reference")


def _answer_mathematical(question: str, context: ResearchContext) -> Answer:
    bullets: list[str] = []
    if context.circuit is not None:
        n = context.circuit.num_qubits
        bullets.append(f"state space dimension 2^{n} = {2 ** n}")
        try:
            unitary = context.circuit.to_unitary()
            identity_error = float(np.max(np.abs(unitary.conj().T @ unitary - np.eye(unitary.shape[0]))))
            bullets.append(
                f"the circuit is a single {unitary.shape[0]}×{unitary.shape[0]} unitary U with "
                f"max|U†U - I| = {identity_error:.3e} (checked numerically)"
            )
            if context.result is not None and context.result.statevector:
                bullets.append("final state vector amplitudes (top):")
                for entry in (context.result.statevector.get("amplitudes") or [])[:5]:
                    bullets.append(
                        f"  |{entry['basis']}⟩ : {entry['real']:+.6f}{entry['imag']:+.6f}i "
                        f"(magnitude {entry['magnitude']:.6f}, phase {entry['phase']:.6f} rad, probability {entry['probability']:.6f})"
                    )
        except Exception as exc:
            bullets.append(f"unitary construction not available for this circuit: {exc}")
    if context.result is not None:
        metrics = context.result.metrics or {}
        pauli = metrics.get("pauli_expectations")
        if pauli:
            bullets.append("Pauli expectation values: " + ", ".join(f"⟨{k}⟩={v:+.6f}" for k, v in list(pauli.items())[:8]))
        if context.result.density_matrix:
            bullets.append("mixed state: ρ with Tr ρ = 1, purity Tr ρ² measured as " f"{metrics.get('purity')}")
        if metrics.get("entropy") is not None:
            bullets.append(f"von Neumann entropy S(ρ) = -Tr(ρ log₂ ρ) = {metrics['entropy']:.6f} bits")
        if metrics.get("coherence_l1") is not None:
            bullets.append(f"l1 coherence (sum of off-diagonal magnitudes) = {metrics['coherence_l1']:.6f}")
    body = (
        "Formally, a circuit is a product of gate unitaries acting on a 2^n-dimensional complex vector; "
        "measurement applies the Born rule to the resulting state."
    )
    if not bullets:
        return _missing(question, "mathematical", "a circuit or run")
    return Answer(
        question=question,
        intent="mathematical",
        title="The mathematics of this circuit",
        body=body,
        bullets=bullets,
        citations=_cite(context, "run.ideal_probabilities", "metrics.purity", "metrics.entropy", "metrics.coherence_l1", "circuit.gates"),
        confidence=CONFIDENCE_MEASURED,
        limitations=["Numerical values are double-precision results of this simulation, subject to floating-point error at the 1e-15 level."],
    )


def _answer_overview(question: str, context: ResearchContext) -> Answer:
    if not context.available_sources():
        return Answer(
            question=question,
            intent="overview",
            title="Nothing to analyse yet",
            body="No circuit, run, experiment or stored history is in context, so there is nothing to reason about.",
            confidence=CONFIDENCE_QUALITATIVE,
            limitations=["Load or run something first."],
        )
    bullets: list[str] = [f"available sources: {', '.join(context.available_sources())}"]
    if context.circuit is not None:
        resources = context.circuit.resources()
        bullets.append(
            f"circuit {context.circuit.name}: {resources['num_qubits']} qubits, {resources['gates']} gates, "
            f"depth {resources['depth']}, {resources['two_qubit_gates']} two-qubit gates"
        )
    if context.result is not None:
        counts = context.result.counts
        total = sum(counts.values()) or 1
        top = max(counts.items(), key=lambda kv: kv[1]) if counts else None
        bullets.append(
            f"run: {context.result.mode} on {context.result.backend}, {context.result.shots} shots, "
            + (f"top outcome |{top[0]}⟩ at {top[1] / total:.4f}, " if top else "")
            + f"runtime {context.result.timing.get('total_seconds', 0):.6f} s"
        )
        if context.result.fidelity_vs_ideal is not None:
            bullets.append(f"fidelity vs ideal {context.result.fidelity_vs_ideal:.6f}")
    if context.outcome is not None:
        bullets.append(f"experiment: {context.outcome.spec['name']} ({len(context.outcome.rows)} rows). {context.outcome.headline()}")
    if context.trace is not None:
        summary = context.trace.summary()
        bullets.append(f"trace: {summary['steps']} operations, {summary['layers']} layers, final entanglement {summary['final_entanglement_status']}")
    body = (
        "Here is the state of the current research context. Ask about fidelity, depth, probabilities, "
        "entanglement, optimization, noise, performance, hardware, or ask for hypotheses and explanations."
    )
    return Answer(
        question=question,
        intent="overview",
        title="What QScope can tell you right now",
        body=body,
        bullets=bullets,
        citations=_cite(context, "circuit.gates", "run.backend", "run.fidelity_vs_ideal", "run.counts"),
        confidence=CONFIDENCE_MEASURED,
    )


def _missing(question: str, intent: str, need: str) -> Answer:
    return Answer(
        question=question,
        intent=intent,
        title=f"Not enough grounded data for that answer",
        body=f"Answering this needs {need}. QScope will not estimate it: run the relevant step first.",
        confidence=CONFIDENCE_QUALITATIVE,
        limitations=[f"missing input: {need}"],
        suggestions=[f"Provision {need} and ask again"],
    )


_HANDLERS: dict[str, Callable[[str, ResearchContext], Answer]] = {
    "fidelity": _answer_fidelity,
    "depth": _answer_depth,
    "probability": _answer_probability,
    "entanglement": _answer_entanglement,
    "optimization": _answer_optimization,
    "noise": _answer_noise,
    "performance": _answer_performance,
    "comparison": _answer_comparison,
    "hardware": _answer_hardware,
    "hypothesis": _answer_hypothesis,
    "beginner": _answer_beginner,
    "mathematical": _answer_mathematical,
    "overview": _answer_overview,
}


def suggested_questions() -> list[dict[str, str]]:
    """Question prompts for the UI, each mapped to the intent it exercises."""
    return [
        {"intent": "fidelity", "question": "Why did the fidelity decrease?"},
        {"intent": "depth", "question": "Which gates contribute most to the depth?"},
        {"intent": "probability", "question": "Why is this circuit producing 50/50 probabilities?"},
        {"intent": "entanglement", "question": "Where is entanglement created?"},
        {"intent": "optimization", "question": "Can this circuit be optimized?"},
        {"intent": "comparison", "question": "Compare these two runs."},
        {"intent": "noise", "question": "How does the noise model affect this result?"},
        {"intent": "performance", "question": "How does runtime scale with qubits?"},
        {"intent": "hardware", "question": "Would this circuit fit that hardware topology?"},
        {"intent": "beginner", "question": "Explain this circuit like I'm a beginner."},
        {"intent": "mathematical", "question": "Explain this circuit mathematically."},
        {"intent": "hypothesis", "question": "Generate a research hypothesis from these results."},
    ]


__all__ = [
    "Answer",
    "LLMProvider",
    "OpenAICompatibleProvider",
    "ResearchContext",
    "ask",
    "classify",
    "suggested_questions",
]
