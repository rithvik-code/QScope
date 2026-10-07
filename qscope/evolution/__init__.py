"""Circuit evolution layer: candidate generation, search and ranking."""

from __future__ import annotations

from qscope.evolution.evolve import (
    TEMPLATES,
    Candidate,
    EvolutionResult,
    apply_templates,
    comparison_table,
    evolve_circuit,
    genetic_search,
    greedy_search,
    optimize_candidates,
    score_candidate,
)

__all__ = [
    "Candidate",
    "EvolutionResult",
    "TEMPLATES",
    "apply_templates",
    "comparison_table",
    "evolve_circuit",
    "genetic_search",
    "greedy_search",
    "optimize_candidates",
    "score_candidate",
]
