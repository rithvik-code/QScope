"""Optimiser layer: rewrite rules, verified optimisation and opportunity audits."""

from __future__ import annotations

from qscope.optimizer.optimizer import (
    DEFAULT_PROOF_QUBITS,
    LEVEL_PASSES,
    OptimizationResult,
    OptimizationStep,
    PASS_AGGRESSIVE,
    PASS_SAFE,
    PASS_STANDARD,
    VERIFIED_FAILED,
    VERIFIED_PROVEN,
    VERIFIED_SKIPPED,
    VERIFIED_STATISTICAL,
    opportunities,
    optimization_levels,
    optimise,
    verify_equivalence,
)
from qscope.optimizer.rules import (
    CLIFFORD_PAIRS,
    FULL_TURN,
    RuleMatch,
    commutes,
    compact_qubits,
    find_opportunities,
    segment_bounds,
)

__all__ = [
    "CLIFFORD_PAIRS",
    "DEFAULT_PROOF_QUBITS",
    "FULL_TURN",
    "LEVEL_PASSES",
    "OptimizationResult",
    "OptimizationStep",
    "PASS_AGGRESSIVE",
    "PASS_SAFE",
    "PASS_STANDARD",
    "RuleMatch",
    "VERIFIED_FAILED",
    "VERIFIED_PROVEN",
    "VERIFIED_SKIPPED",
    "VERIFIED_STATISTICAL",
    "commutes",
    "compact_qubits",
    "find_opportunities",
    "opportunities",
    "optimization_levels",
    "optimise",
    "segment_bounds",
    "verify_equivalence",
]
