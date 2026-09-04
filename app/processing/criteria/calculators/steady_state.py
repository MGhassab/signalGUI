"""Steady-state error.

Used as the derived, continuously-recomputed value in the engine
(`e = reference - source`, optionally percent), so this calculator only
documents the per-response final ESS form for completeness/registry.
"""
from __future__ import annotations

from typing import Optional

from processing.criteria.calculators.base import CriterionCalculator
from processing.criteria.response import StepResponse
from models.signal_config import CriteriaSignalConfig


class SteadyStateErrorCalculator(CriterionCalculator):
    def compute(self, response: StepResponse,
                config: CriteriaSignalConfig) -> Optional[float]:
        if not response.source:
            return None
        error = abs(response.target - response.source[-1])
        if config.ss_error_percent and abs(response.target) > 1e-12:
            return 100.0 * error / abs(response.target)
        return error
