"""Settling time.

The time at which the source signal last ENTERS the tolerance band around
the reference target and then REMAINS inside it for the rest of the
captured response. Scanning backwards for the last out-of-band sample makes
this robust: a response that re-exits the band and re-enters later settles
at the final re-entry, not the first dip inside.
"""
from __future__ import annotations

from typing import Optional

from processing.criteria.calculators.base import CriterionCalculator
from processing.criteria.response import StepResponse
from models.signal_config import CriteriaSignalConfig


class SettlingTimeCalculator(CriterionCalculator):
    def compute(self, response: StepResponse,
                config: CriteriaSignalConfig) -> Optional[float]:
        src = response.source
        t = response.t
        if not src:
            return None
        # A percentage band around a (near-)zero target is meaningless, so
        # scale the band by the larger of the target or start magnitude.
        magnitude = max(abs(response.target), abs(response.start_level), 1e-9)
        tol = magnitude * (config.settling_tolerance_pct / 100.0)

        last_out = -1
        for i in range(len(src) - 1, -1, -1):
            if abs(src[i] - response.target) > tol:
                last_out = i
                break
        settle_idx = last_out + 1
        if settle_idx >= len(t):
            return None
        # Time measured from the start of the step response.
        return max(0.0, t[settle_idx] - response.step_start_time)
