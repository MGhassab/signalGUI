"""Overshoot.

Peak excursion of the source beyond the reference target, relative to the
step amplitude, as a percentage. Direction-aware: for a downward reference
step the "overshoot" is how far the source dips *below* the (lower) target.
"""
from __future__ import annotations

from typing import Optional

from processing.criteria.calculators.base import CriterionCalculator
from processing.criteria.response import StepResponse
from models.signal_config import CriteriaSignalConfig


class OvershootCalculator(CriterionCalculator):
    def compute(self, response: StepResponse,
                config: CriteriaSignalConfig) -> Optional[float]:
        src = response.source
        if not src:
            return None
        amplitude = response.amplitude
        if amplitude <= 1e-12:
            return 0.0
        direction = response.direction

        worst = 0.0
        for value in src:
            excursion = (value - response.target) * direction
            if excursion > worst:
                worst = excursion
        return max(0.0, 100.0 * worst / amplitude)
