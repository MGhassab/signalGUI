"""Fall time.

Time for the source to travel between the configured upper threshold
(default 90%) and the configured lower threshold (default 10%) of the step
amplitude - the 90%-to-10% time. Fractions are measured from the pre-step
level toward the reference target, so a decreasing step crosses the lower
fraction first (nearest the start) - handled correctly by the shared
level-crossing logic.
"""
from __future__ import annotations

from typing import Optional

from processing.criteria.calculators.base import CriterionCalculator
from processing.criteria.response import StepResponse
from models.signal_config import CriteriaSignalConfig


class FallTimeCalculator(CriterionCalculator):
    def compute(self, response: StepResponse,
                config: CriteriaSignalConfig) -> Optional[float]:
        return self._band_delta(
            response, config.fall_low_pct, config.fall_high_pct
        )
