"""Criteria engine: derives control-performance metrics from a SOURCE
signal evaluated against a POSITION-4 REFERENCE channel.

Pipeline for one criteria signal:

    streamed (t, source, reference) samples
      -> step detection (reference transition + plateau confirmation)
      -> a completed *response window*
      -> the configured criterion's calculator -> one scalar metric

The engine holds the last computed metric between completed steps, so the
derived result is a time-continuous (stepped) series that the plot can
show like any other signal. Steady-state error is the one exception: it is
reported continuously as e(t) = reference - source (optionally normalized).

Calculators are stateless and selected through a registry
(`CRITERION -> CriterionCalculator`), so adding a new criterion later only
requires a new calculator class + registration.
"""
from __future__ import annotations

from models.signal_config import Criterion, CriteriaSignalConfig
from processing.criteria.calculators import (
    CriterionCalculator, get_calculator,
)
from processing.criteria.response import StepResponse

# Step detection tuning (sample-count based; independent of the configured
# criterion so all metrics agree on what "a step" is).
_PLATEAU_CONFIRM_SAMPLES = 5   # ref must sit within band for this many samples
_POST_PLATEAU_SAMPLES = 16     # min samples kept after plateau before finalize
_STABLE_WINDOW = 8             # samples used to estimate the pre-step baseline
_MAX_SEGMENT_SAMPLES = 4096    # safety cap on an unterminated segment
_RESPONSE_HORIZON_S = 5.0      # stop analyzing a response after this long
_SETTLE_BAND_FACTOR = 0.02     # src kept this close to target => "settled"


class CriteriaEngine:
    def __init__(self, config: CriteriaSignalConfig):
        self.config = config
        self.reset()

    def reset(self) -> None:
        self._current: float = 0.0
        self._stable = True
        self._base_ref: float | None = None
        self._stable_ref_buf = []
        self._stable_src_buf = []
        self._start_level: float = 0.0

        self._seg_t: list[float] = []
        self._seg_src: list[float] = []
        self._seg_ref: list[float] = []
        self._plateau_idx: int | None = None
        self._plateau_run = 0
        self._plateau_probe: float | None = None
        self._plateau_time: float | None = None

    @property
    def current_value(self) -> float:
        return self._current

    def update(self, t: float, source: float, reference: float) -> float:
        """Feed one synchronized (source, reference) sample.

        Returns the derived metric to plot at time `t` (the newly computed
        value, or the previously-held value while no step has finished).
        Never raises.
        """
        cfg = self.config
        if cfg.criterion == Criterion.STEADY_STATE_ERROR:
            self._current = self._steady_error(source, reference)
            return self._current
        if not self._stable:
            self._during_step(t, source, reference)
        else:
            self._before_step(t, source, reference)
        return self._current

    # -- steady-state error (continuous) -------------------------------------
    def _steady_error(self, source: float, reference: float) -> float:
        error = reference - source
        if self.config.ss_error_percent:
            if abs(reference) <= 1e-12:
                return 0.0
            return 100.0 * abs(error) / abs(reference)
        return error

    # -- step detection state machine ----------------------------------------
    def _threshold(self) -> float:
        if self.config.step_threshold and self.config.step_threshold > 0:
            return self.config.step_threshold
        base = self._base_ref if self._base_ref is not None else 0.0
        # Auto threshold: ~1% of the reference level, floored at 1.0 (raw
        # channel units). Tune via CriteriaSignalConfig.step_threshold.
        return max(1.0, 0.01 * abs(base))

    def _before_step(self, t: float, source: float, reference: float) -> None:
        """Idle state: track the reference/source baselines and detect the
        start of a reference transition."""
        if self._base_ref is None:
            self._base_ref = reference
        self._stable_ref_buf.append(reference)
        self._stable_src_buf.append(source)
        self._stable_ref_buf = self._stable_ref_buf[-_STABLE_WINDOW:]
        self._stable_src_buf = self._stable_src_buf[-_STABLE_WINDOW:]
        base_ref = sum(self._stable_ref_buf) / len(self._stable_ref_buf)

        if abs(reference - base_ref) > self._threshold():
            # Reference moved -> begin a response segment.
            self._stable = False
            self._start_level = (
                sum(self._stable_src_buf) / len(self._stable_src_buf)
            )
            self._seg_t = [t]
            self._seg_src = [source]
            self._seg_ref = [reference]
            self._plateau_idx = None
            self._plateau_run = 0
            self._plateau_probe = reference
        else:
            self._base_ref = base_ref

    def _during_step(self, t: float, source: float, reference: float) -> None:
        """Collecting samples for an in-progress step."""
        self._seg_t.append(t)
        self._seg_src.append(source)
        self._seg_ref.append(reference)

        # Detect a plateau: reference stops moving and stays within the band.
        if self._plateau_idx is None:
            if self._plateau_probe is None:
                self._plateau_probe = reference
            band = self._threshold()
            if abs(reference - self._plateau_probe) <= band:
                self._plateau_run += 1
                if self._plateau_run == _PLATEAU_CONFIRM_SAMPLES:
                    self._plateau_idx = (
                        len(self._seg_ref) - _PLATEAU_CONFIRM_SAMPLES
                    )
                    self._plateau_time = self._seg_t[self._plateau_idx]
            else:
                # Reference moved again before confirming a plateau - restart
                # plateau tracking from the current (newer) level.
                self._plateau_probe = reference
                self._plateau_run = 1

            if self._plateau_idx is None and \
                    len(self._seg_t) >= _MAX_SEGMENT_SAMPLES:
                # Safety: the reference never plateaus (e.g. a slow ramp).
                # Treat the most recent tail as the plateau and finalize now.
                self._plateau_idx = len(self._seg_ref) - _PLATEAU_CONFIRM_SAMPLES
                self._plateau_time = self._seg_t[self._plateau_idx]

        if self._plateau_idx is None:
            return

        # Wait for a minimum post-plateau tail, then finalize once either the
        # response has observably settled (source stayed within the settle band)
        # or the analysis horizon elapsed (slow/unsettled response).
        tail = len(self._seg_t) - self._plateau_idx
        if tail < _POST_PLATEAU_SAMPLES:
            return
        if self._plateau_time is not None and \
                t - self._plateau_time >= _RESPONSE_HORIZON_S:
            self._finalize()
            return

        plateau_ref = self._seg_ref[self._plateau_idx]
        magnitude = max(abs(plateau_ref), abs(self._start_level), 1.0)
        band = _SETTLE_BAND_FACTOR * magnitude
        settled = all(
            abs(v - plateau_ref) <= band
            for v in self._seg_src[-_POST_PLATEAU_SAMPLES:]
        )
        if settled:
            self._finalize()

    def _finalize(self) -> None:
        assert self._plateau_idx is not None
        end = len(self._seg_t) - 1
        t = self._seg_t[:end + 1]
        src = self._seg_src[:end + 1]
        ref_tail = self._seg_ref[self._plateau_idx:end + 1]

        response = StepResponse(
            t=t,
            source=src,
            target=float(sum(ref_tail) / len(ref_tail)),
            start_level=self._start_level,
            step_start_time=self._seg_t[0],
        )
        calculator: CriterionCalculator = get_calculator(self.config.criterion)
        value = calculator.compute(response, self.config)
        if value is not None:
            self._current = value

        # Return to idle, seeding the new baseline from the plateau tail.
        tail_src = src[-_STABLE_WINDOW:]
        tail_ref = ref_tail[-_STABLE_WINDOW:]
        self._stable = True
        self._base_ref = float(sum(tail_ref) / len(tail_ref)) if tail_ref else response.target
        self._stable_ref_buf = [self._base_ref]
        self._stable_src_buf = [float(sum(tail_src) / len(tail_src)) if tail_src else src[-1]]
        self._seg_t = []
        self._seg_src = []
        self._seg_ref = []
        self._plateau_idx = None
        self._plateau_run = 0
        self._plateau_probe = None
        self._plateau_time = None
