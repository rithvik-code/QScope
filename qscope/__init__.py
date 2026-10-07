"""QScope — See inside quantum computing.

QScope is a quantum computing *research environment*: a simulation engine, a
gate-by-gate debugger, an optimizer, a noise observatory, an experiment
laboratory and a research assistant share one mathematical core.

The package is importable as a library::

    from qscope.core import StateVector
    from qscope.circuit import Circuit

and runnable as an application::

    python -m qscope            # serves the API + built frontend
"""

from __future__ import annotations

__version__ = "0.1.0"
__all__ = ["__version__"]
