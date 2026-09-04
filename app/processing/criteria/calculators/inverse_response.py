"""Inverse response detection.

Returns 1.0 when the source initially moves AWAY from the reference
direction (opposite to the step) with enough amplitude and for long enough
that it cannot be dismissed as noise; otherwise 0.0. The detection window,
minimum opposing amplitude and minimum opposing duration are configurable
and act as noise guards.
"""
from __future__ import annotations

from typing import Optional

from processing.criteria.calculators.base import CriterionCalculator
from processing.criteria.response import StepResponse
from models.signal_config import CriteriaSignalConfig


class InverseResponseCalculator(CriterionCalculator):
    def compute(self, response: StepResponse,
                config: CriteriaSignalConfig) -> Optional[float]:
        t = response.t
        src = response.source
        if not src:
            return None
        direction = response.direction
        if direction == 0:
            return 0.0

        window_end = response.step_start_time + config.inverse_window_s
        min_amp = max(0.0, config.inverse_min_amplitude)
        min_duration = max(0.0, config.inverse_min_duration_s)

        run_start: Optional[int] = None
        n = len(t)
        for i in range(n):
            if t[i] > window_end:
                break
            opposing = (src[i] - response.start_level) * direction
            active = opposing <= -min_amp
            if active and run_start is None:
                run_start = i
            elif not active and run_start is not None:
                if t[i - 1] - t[run_start] >= min_duration:
                    return 1.0
                run_start = None
        if run_start is not None and n > 0:
            if t[n - 1] - t[run_start] >= min_duration:
                return 1.0
        return 0.0
