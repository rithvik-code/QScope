"""The AI research assistant layer.

The assistant is grounded by construction: it can only speak about the circuit,
run, trace, optimization, experiment rows, benchmark measurements and stored
history that were actually produced, and every answer carries the evidence it
used.  An LLM can narrate the grounded answer when one is configured, but it is
never the source of a number and its output is linted against the data.
"""

from __future__ import annotations

from qscope.ai.assistant import (
    Answer,
    LLMProvider,
    OpenAICompatibleProvider,
    ResearchContext,
    ask,
    classify,
    suggested_questions,
)
from qscope.ai.knowledge import KnowledgeGraph, build_knowledge_graph

__all__ = [
    "Answer",
    "KnowledgeGraph",
    "LLMProvider",
    "OpenAICompatibleProvider",
    "ResearchContext",
    "ask",
    "build_knowledge_graph",
    "classify",
    "suggested_questions",
]
