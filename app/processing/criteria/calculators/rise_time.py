"""Rise time.

Time for the source to travel between the configured lower threshold
(default 10%) and the configured upper threshold (default 90%) of the
step amplitude, measured from the pre-step level toward the reference
target.
"""
from __future__ import annotations

from typing import Optional

from processing.criteria.calculators.base import CriterionCalculator
from processing.criteria.response import StepResponse
from models.signal_config import CriteriaSignalConfig


class RiseTimeCalculator(CriterionCalculator):
    def compute(self, response: StepResponse,
                config: CriteriaSignalConfig) -> Optional[float]:
        return self._band_delta(
            response, config.rise_low_pct, config.rise_high_pct
        )
