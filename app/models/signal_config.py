"""Signal configuration data models.

Three signal "types" share a common base configuration; each adds its own
type-specific parameters. These are plain dataclasses so they serialize to
/ from JSON trivially (see config/config_manager.py).
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Dict


class SignalType(str, Enum):
    RAW = "raw"
    COMPUTATIONAL = "computational"
    CRITERIA = "criteria"


class Operation(str, Enum):
    INTEGRAL = "integral"
    DERIVATIVE = "derivative"


@dataclass
class SignalConfig:
    """Common configuration fields shared by all signal types.

    `dt` is a per-signal PROCESSING parameter: the assumed time step used
    by that signal's own math (e.g. as delta-t in an integral/derivative
    calculation). It is intentionally NOT the plot's shared time axis and
    NOT literal serial packet arrival timing - those can differ. If a
    signal's math should instead track real packet arrival time, that
    would need to be an explicit future option; it wasn't requested here,
    so we don't invent it.
    """
    name: str
    source_field: str
    signal_type: SignalType = SignalType.RAW
    enabled: bool = True
    gain: float = 1.0
    offset: float = 0.0
    y_min: float = -1.0
    y_max: float = 1.0
    dy: float = 0.1
    dt: float = 0.01

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["signal_type"] = SignalType(self.signal_type).value
        return d


@dataclass
class RawSignalConfig(SignalConfig):
    """Data Type 1: output = received_value * gain + offset."""

    def __post_init__(self):
        self.signal_type = SignalType.RAW


@dataclass
class ComputationalSignalConfig(SignalConfig):
    """Data Type 2: gain/offset followed by Integral or Derivative,
    applied `x_degree` times."""

    operation: Operation = Operation.INTEGRAL
    x_degree: int = 1

    def __post_init__(self):
        self.signal_type = SignalType.COMPUTATIONAL

    def to_dict(self) -> Dict[str, Any]:
        d = super().to_dict()
        d["operation"] = Operation(self.operation).value
        return d


@dataclass
class CriteriaSignalConfig(SignalConfig):
    """Data Type 3: criteria-based signal. The ESS/Delay algorithm itself
    is NOT implemented (see processing/criteria_processor.py) - only its
    configuration is stored here."""

    ess_criteria_pct: float = 2.0
    delay_criteria_pct: float = 5.0

    def __post_init__(self):
        self.signal_type = SignalType.CRITERIA


def signal_config_from_dict(d: Dict[str, Any]) -> SignalConfig:
    """Reconstruct the correct SignalConfig subclass from a plain dict
    (as loaded from JSON)."""
    d = dict(d)
    stype = SignalType(d.pop("signal_type"))
    if stype == SignalType.RAW:
        return RawSignalConfig(**d)
    if stype == SignalType.COMPUTATIONAL:
        d["operation"] = Operation(d.get("operation", Operation.INTEGRAL.value))
        return ComputationalSignalConfig(**d)
    if stype == SignalType.CRITERIA:
        return CriteriaSignalConfig(**d)
    raise ValueError(f"Unknown signal type: {stype}")
