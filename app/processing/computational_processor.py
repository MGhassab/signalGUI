"""Data Type 2: Computational Data.

    transformed(t) = received_value(t) * gain + offset
    output(t)      = Integral(transformed) or Derivative(transformed),
                     applied `x_degree` times in a row (e.g. degree=2
                     derivative applies a first-derivative twice).

Numerical methods used (documented here since none were specified in the
request):

- Integral: cumulative trapezoidal integration, using the signal's own
  configured `dt` as the time step between samples.
- Derivative: backward finite difference: (y[n] - y[n-1]) / dt.

Both are guarded against the "insufficient history" case (the very first
sample of a run, or a degenerate dt) - they return a safe 0.0 instead of
raising or producing NaN/Inf, and the running state resumes normally on
the next sample.

Adding a new operation later: implement a new `_op_*` method with the
same `(value, degree) -> float` signature and register it in
`_OPERATIONS`. Nothing else needs to change.
"""
from __future__ import annotations

import math
from typing import Callable, Dict

from processing.base_processor import SignalProcessor


class ComputationalProcessor(SignalProcessor):
    def __init__(self, config):
        super().__init__(config)
        # Keyed by "degree" (1..x_degree) since each successive application
        # of the operation needs its own independent running state.
        self._prev_values: Dict[int, float] = {}
        self._running_integral: Dict[int, float] = {}
        self._OPERATIONS: Dict[str, Callable[[float, int], float]] = {
            "integral": self._op_integral,
            "derivative": self._op_derivative,
        }

    def reset(self) -> None:
        self._prev_values.clear()
        self._running_integral.clear()

    def process(self, raw_value: float, t: float) -> float:
        transformed = self._apply_gain_offset(raw_value)

        op = self.config.operation
        op_name = op.value if hasattr(op, "value") else str(op)
        op_fn = self._OPERATIONS.get(op_name)
        if op_fn is None:
            return transformed  # unknown operation: pass through safely

        value = transformed
        degree_count = max(1, int(self.config.x_degree))
        for degree in range(1, degree_count + 1):
            value = op_fn(value, degree)
            if not math.isfinite(value):
                # Guard against NaN/Inf propagating into the plot / UI.
                value = 0.0
        return value

    def _op_integral(self, value: float, degree: int) -> float:
        dt = self.config.dt
        prev = self._prev_values.get(degree)
        running = self._running_integral.get(degree, 0.0)
        if prev is not None:
            running += 0.5 * (value + prev) * dt
        # else: first sample for this degree - contribute nothing yet
        # rather than guessing a slice width.
        self._prev_values[degree] = value
        self._running_integral[degree] = running
        return running

    def _op_derivative(self, value: float, degree: int) -> float:
        dt = self.config.dt
        prev = self._prev_values.get(degree)
        self._prev_values[degree] = value
        if prev is None or dt <= 0:
            # First sample (or degenerate dt): no derivative information
            # yet - report 0 instead of dividing by zero / producing NaN.
            return 0.0
        return (value - prev) / dt
