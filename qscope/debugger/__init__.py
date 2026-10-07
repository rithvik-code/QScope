"""Debugger layer: the gate-by-gate tracer and the Quantum Diff engine."""

from __future__ import annotations

from qscope.debugger.state_diff import (
    CHANGE_TOL,
    diff_circuits,
    diff_states,
    quantum_diff,
    summarise_diff,
)
from qscope.debugger.trace import (
    ENTANGLEMENT_PAIR_LIMIT,
    TRACE_FAST,
    TRACE_FULL,
    TRACE_STANDARD,
    TraceResult,
    TraceStep,
    replay_states,
    states_at,
    trace_circuit,
)

__all__ = [
    "CHANGE_TOL",
    "ENTANGLEMENT_PAIR_LIMIT",
    "TRACE_FAST",
    "TRACE_FULL",
    "TRACE_STANDARD",
    "TraceResult",
    "TraceStep",
    "diff_circuits",
    "diff_states",
    "quantum_diff",
    "replay_states",
    "states_at",
    "summarise_diff",
    "trace_circuit",
]
