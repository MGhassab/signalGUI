"""Data Type 2: Computational Data.

    transformed(t) = received_value(t) * gain + offset
    output(t)      = Integral(transformed) or Derivative(transformed),
                     applied `x_degree` times in a row (e.g. degree=2
                     derivative applies a first-derivative twice).

Numerical methods used (documented here since none were specified in the
request):

- Integral: cumulative trapezoidal integration, using the MEASURED
  arrival-time delta between consecutive samples as the time step. Each
  sample produces one output immediately at its own time `t`.

- Derivative: a real-time Savitzky-Golay-style differentiator. Instead of a
  one-sided (backward) finite difference - which is only first-order
  accurate, carries a half-sample phase lag, and amplifies the ±1-LSB
  quantization of a 16-bit device stream by 1/dt per applied degree - each
  derivative stage keeps a sliding window of the last W `(measured_time,
  value)` samples, fits a quadratic to them by least squares, and reports
  the slope at the CENTER of the window. Fitting against the real measured
  times (not a fixed dt) handles irregular/variable sample intervals
  exactly.

  Properties:
    - phase-exact (centered, not one-sided) and amplitude-accurate;
    - the least-squares fit smooths quantization/jitter instead of
      amplifying it, so a 2nd derivative no longer blows up on integer data;
    - `x_degree > 1` cascades one such stage per degree; each stage
      differentiates the previous stage's already-smooth output;
    - each stage emits its result time-stamped at its window CENTER time,
      so the plotted trace stays aligned on the global time axis. This
      introduces a fixed group delay of (W-1)/2 samples per stage (~0.1 s
      for a 1st derivative, ~0.25 s for a 2nd at 20 Hz), and the trace
      simply ends that far short of the live edge.

  Window sizes grow with the applied degree (W = 5, 7, 9, ...) so higher
  degrees receive progressively more smoothing where they need it most.
  Polynomial degree 2 (quadratic) is used throughout.

There is deliberately NO configured per-signal dt: `dT` in this app is a
per-panel plot-axis tick setting only. Signal math uses the real elapsed
time between samples, which is physically consistent for irregular arrival
rates too. Both operations are guarded against the "insufficient history"
case (the very first samples of a run, a degenerate/zero time span) - they
emit no output rather than raising or producing NaN/Inf, so there are no
startup spikes, and processing resumes normally on the next sample.
"""
from __future__ import annotations

import math
from collections import deque
from typing import Deque, Dict, Iterable, List, Optional, Tuple

import numpy as np

from processing.base_processor import SignalProcessor

_DERIVATIVE_POLY_DEGREE = 2
_MIN_DERIVATIVE_WINDOW = 5  # odd; windows grow by 2 per applied degree


def _derivative_windows(degree: int) -> List[int]:
    """One window size per applied derivative degree (5, 7, 9, ...)."""
    return [_MIN_DERIVATIVE_WINDOW + 2 * (k - 1) for k in range(1, degree + 1)]


class _DerivativeStage:
    """One centered Savitzky-Golay-style differentiator stage.

    Holds the sliding window of the most recent `window` samples of its
    input stream. Once the window is full, every further push yields the
    smoothed first-derivative of the input at the window's CENTER sample
    (its own measured time), evaluated from a least-squares quadratic fit
    in measured time.
    """

    def __init__(self, window: int, poly_degree: int = _DERIVATIVE_POLY_DEGREE):
        self._window = window
        self._poly_degree = poly_degree
        self._half = (window - 1) // 2
        self._buf: Deque[Tuple[float, float]] = deque(maxlen=window)

    def push(self, t: float, value: float) -> Optional[Tuple[float, float]]:
        """Consume one input sample. Returns `(center_time, derivative)`
        for the sample at the window center once the window is full,
        otherwise None."""
        self._buf.append((t, value))
        if len(self._buf) < self._window:
            return None
        center_t = self._buf[self._half][0]
        times = np.fromiter((p[0] for p in self._buf), dtype=float,
                            count=self._window)
        values = np.fromiter((p[1] for p in self._buf), dtype=float,
                             count=self._window)
        if times[-1] - times[0] <= 0.0:
            return None  # degenerate span: no usable timing information
        # Least-squares fit value(t) ~ c0 + c1*(t - center) + c2*(t - center)^2
        # in MEASURED time. Slope at the center is c1.
        design = np.vander(times - center_t, self._poly_degree + 1,
                           increasing=True)
        coef, *_ = np.linalg.lstsq(design, values, rcond=None)
        slope = float(coef[1])
        if not math.isfinite(slope):
            return None
        return center_t, slope

    def clear(self) -> None:
        self._buf.clear()


class ComputationalProcessor(SignalProcessor):
    def __init__(self, config):
        super().__init__(config)
        self._mode: Optional[str] = None
        self._last_t: Optional[float] = None
        self._dt: float = 0.0
        self._integral_prev: Dict[int, float] = {}
        self._integral_running: Dict[int, float] = {}
        self._derivative_stages: List[_DerivativeStage] = []

    def reset(self) -> None:
        """Clear all per-operation running state (integral accumulators,
        derivative windows, measured-dt bookkeeping)."""
        self._mode = None
        self._last_t = None
        self._dt = 0.0
        self._integral_prev.clear()
        self._integral_running.clear()
        for stage in self._derivative_stages:
            stage.clear()
        self._derivative_stages.clear()

    def _ensure_mode(self, op_name: str, degree: int) -> None:
        if self._mode == op_name:
            return
        # Operation changed (e.g. Integral <-> Derivative after an edit):
        # rebuild clean state for the new operation.
        self._integral_prev.clear()
        self._integral_running.clear()
        for stage in self._derivative_stages:
            stage.clear()
        self._derivative_stages.clear()
        if op_name == "derivative":
            self._derivative_stages = [
                _DerivativeStage(w) for w in _derivative_windows(degree)
            ]
        self._last_t = None
        self._dt = 0.0
        self._mode = op_name

    def _update_dt(self, t: float) -> None:
        if self._last_t is not None:
            self._dt = max(0.0, t - self._last_t)
        else:
            self._dt = 0.0
        self._last_t = t

    def process(self, raw_value: float, t: float) -> Iterable[Tuple[float, float]]:
        transformed = self._apply_gain_offset(raw_value)

        op = self.config.operation
        op_name = op.value if hasattr(op, "value") else str(op)
        degree_count = max(1, int(self.config.x_degree))

        if op_name == "integral":
            self._ensure_mode("integral", degree_count)
            self._update_dt(t)
            value = transformed
            for degree in range(1, degree_count + 1):
                value = self._op_integral(value, degree)
            if not math.isfinite(value):
                value = 0.0
            yield t, value

        elif op_name == "derivative":
            self._ensure_mode("derivative", degree_count)
            emitted = self._cascade_derivative(transformed, t)
            if emitted is not None:
                yield emitted

        else:  # unknown operation: pass through safely
            yield t, transformed

    def _cascade_derivative(self, value: float, t: float
                            ) -> Optional[Tuple[float, float]]:
        """Run one input sample through every derivative stage. Only the
        final stage's output is meaningful; intermediate stages just get
        primed. Returns `(center_time, final_derivative)` once every stage
        has enough history, otherwise None."""
        cur_t = t
        cur_val = value
        for stage in self._derivative_stages:
            emitted = stage.push(cur_t, cur_val)
            if emitted is None:
                return None  # this stage is still collecting history
            cur_t, cur_val = emitted
        if not math.isfinite(cur_val):
            return None
        return cur_t, cur_val

    def _op_integral(self, value: float, degree: int) -> float:
        dt = self._dt
        prev = self._integral_prev.get(degree)
        running = self._integral_running.get(degree, 0.0)
        if prev is not None and dt > 0:
            running += 0.5 * (value + prev) * dt
        # else: first sample for this degree (or degenerate dt) - contribute
        # nothing yet rather than guessing a slice width.
        self._integral_prev[degree] = value
        self._integral_running[degree] = running
        return running
