"""QScope HTTP API and application server.

``qscope.api.app`` is a module; the FastAPI instance it builds is available as the
module attribute ``app``.  It is deliberately *not* re-exported here, because
re-exporting would bind the name ``app`` on this package and shadow the submodule
for anyone writing ``import qscope.api.app``.  Use :func:`create_app` for a fresh
instance, or ``from qscope.api.app import app`` for the module-level one.
"""

from __future__ import annotations

from qscope.api.app import (
    REPORTS_DIR,
    circuit_document,
    create_app,
    resolve_circuit,
    resolve_noise,
)

__all__ = [
    "REPORTS_DIR",
    "circuit_document",
    "create_app",
    "resolve_circuit",
    "resolve_noise",
]
