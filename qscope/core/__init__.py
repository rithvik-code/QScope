"""Mathematical core of QScope: tensors, gates, state vectors, density matrices.

Nothing in here knows about circuits, the API or the UI — this layer is pure
linear algebra over complex vector spaces and is the layer the test suite
hammers hardest.
"""

from __future__ import annotations

from qscope.core.density import DensityMatrix
from qscope.core.gates import (
    GATE_CATALOG,
    GateSpec,
    gate_matrix,
    inverse_gate,
    register_custom_gate,
)
from qscope.core.measurement import MeasurementOutcome, MeasurementResult, sample_counts
from qscope.core.statevector import StateVector
from qscope.core.tensor import (
    ATOL,
    RTOL,
    apply_kraus,
    apply_operator,
    basis_label,
    basis_state,
    controlled,
    controlled_matrix,
    is_close,
    kron_list,
    matrix_sqrt,
    partial_trace,
    unitary_distance,
)

__all__ = [
    "ATOL",
    "RTOL",
    "GATE_CATALOG",
    "DensityMatrix",
    "GateSpec",
    "MeasurementOutcome",
    "MeasurementResult",
    "StateVector",
    "apply_kraus",
    "apply_operator",
    "basis_label",
    "basis_state",
    "controlled",
    "controlled_matrix",
    "gate_matrix",
    "inverse_gate",
    "is_close",
    "kron_list",
    "matrix_sqrt",
    "partial_trace",
    "register_custom_gate",
    "sample_counts",
    "unitary_distance",
]
