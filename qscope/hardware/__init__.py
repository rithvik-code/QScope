"""Hardware-aware layer: topology, routing and device-model noise estimation."""

from __future__ import annotations

from qscope.hardware.topology import (
    HARDWARE_PRESETS,
    CouplingMap,
    HardwareModel,
    RoutingResult,
    connectivity_violations,
    estimate_noise,
    hardware_report,
    preset_catalog,
    route_circuit,
    unsupported_gates,
)

__all__ = [
    "CouplingMap",
    "HARDWARE_PRESETS",
    "HardwareModel",
    "RoutingResult",
    "connectivity_violations",
    "estimate_noise",
    "hardware_report",
    "preset_catalog",
    "route_circuit",
    "unsupported_gates",
]
