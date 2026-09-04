"""Signal configuration data models.

Three signal "kinds" share a common base configuration; each adds its own
kind-specific parameters. These are plain dataclasses so they serialize to
/ from JSON trivially (see config/config_manager.py).

A Criteria signal is a DERIVED signal: it compares one SOURCE (a
configured signal or a raw packet channel) against a REFERENCE (always one
of the Position-4 channels) and reports a single control-performance
metric. One criteria configuration = one metric (ESS, settling time, rise
time, fall time, overshoot, or inverse response).
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Dict

from models.packet import POSITION4_FIELDS


class SignalType(str, Enum):
    RAW = "raw"
    COMPUTATIONAL = "computational"
    CRITERIA = "criteria"


class Operation(str, Enum):
    INTEGRAL = "integral"
    DERIVATIVE = "derivative"


class SourceKind(str, Enum):
    """Where a criteria signal's SOURCE value comes from."""
    SIGNAL = "signal"   # an existing configured signal in the same panel
    FIELD = "field"     # a raw packet channel (gain/offset applied)


class Criterion(str, Enum):
    STEADY_STATE_ERROR = "steady_state_error"
    SETTLING_TIME = "settling_time"
    RISE_TIME = "rise_time"
    FALL_TIME = "fall_time"
    OVERSHOOT = "overshoot"
    INVERSE_RESPONSE = "inverse_response"


@dataclass
class SignalConfig:
    """Common configuration fields shared by all signal kinds.

    `dt` is a per-signal PROCESSING parameter: the assumed time step used
    by that signal's own math (e.g. as delta-t in an integral/derivative
    calculation). It is intentionally NOT the plot's shared time axis and
    NOT literal serial packet arrival timing - those can differ.
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
    """A derived control-performance metric computed from a source signal
    and a Position-4 reference channel (see processing/criteria/engine.py).

    `source_field` (the base field) holds the raw channel when
    `source_kind == FIELD`; `source_signal` names the configured panel
    signal when `source_kind == SIGNAL`. `gain`/`offset` scale a FIELD
    source the same way RawProcessor would. `y_min`/`y_max` set the plot
    range of the derived result. The remaining base fields (dy/dt) are
    unused for criteria signals.
    """

    source_kind: SourceKind = SourceKind.SIGNAL
    source_signal: str = ""
    reference_field: str = POSITION4_FIELDS[0]
    criterion: Criterion = Criterion.STEADY_STATE_ERROR

    ss_error_percent: bool = False
    settling_tolerance_pct: float = 2.0
    rise_low_pct: float = 10.0
    rise_high_pct: float = 90.0
    fall_low_pct: float = 10.0
    fall_high_pct: float = 90.0
    inverse_window_s: float = 0.5
    inverse_min_amplitude: float = 1.0
    inverse_min_duration_s: float = 0.05

    # Reference-step detection threshold in the reference channel's units.
    # 0.0 => the engine derives a sensible threshold automatically.
    step_threshold: float = 0.0

    def __post_init__(self):
        self.signal_type = SignalType.CRITERIA
        self.source_kind = SourceKind(self.source_kind)
        self.criterion = Criterion(self.criterion)

    @property
    def source_label(self) -> str:
        if SourceKind(self.source_kind) == SourceKind.SIGNAL:
            return self.source_signal
        return self.source_field

    def to_dict(self) -> Dict[str, Any]:
        d = super().to_dict()
        d["source_kind"] = SourceKind(self.source_kind).value
        d["criterion"] = Criterion(self.criterion).value
        return d


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
        # Legacy placeholder criteria configs carried only
        # ess_criteria_pct / delay_criteria_pct; map them to the
        # steady-state-error criterion with the legacy tolerance.
        if "ess_criteria_pct" in d:
            d.setdefault("settling_tolerance_pct", float(d["ess_criteria_pct"]))
            d.pop("ess_criteria_pct", None)
        d.pop("delay_criteria_pct", None)
        return CriteriaSignalConfig(**d)
    raise ValueError(f"Unknown signal type: {stype}")
