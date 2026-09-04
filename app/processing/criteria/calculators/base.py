"""Shared helpers + base class for criteria calculators.

A calculator is stateless: it turns a completed `StepResponse` plus the
signal's configuration into one scalar metric (or None when the metric
cannot be determined from this response, e.g. the response never reached
the requested threshold). Calculators never raise.
"""
from __future__ import annotations

from typing import Optional, Tuple

from processing.criteria.response import StepResponse
from models.signal_config import CriteriaSignalConfig


class CriterionCalculator:
    def compute(self, response: StepResponse,
                config: CriteriaSignalConfig) -> Optional[float]:
        raise NotImplementedError

    # -- helpers ------------------------------------------------------------
    @staticmethod
    def _cross(t, y, level, direction: int, start_index: int = 0
               ) -> Optional[Tuple[int, float]]:
        """First directed crossing of `level`.

        direction = +1: first sample reaching >= level while moving up.
        direction = -1: first sample reaching <= level while moving down.
        Returns (index, interpolated_time) or None if never reached.
        """
        n = len(y)
        for i in range(start_index, n):
            yi = y[i]
            if direction >= 0:
                reached = yi >= level
            else:
                reached = yi <= level
            if not reached:
                continue
            if i == 0:
                return 0, t[0]
            y0, y1 = y[i - 1], yi
            span = y1 - y0
            if abs(span) < 1e-12:
                frac = 0.0
            else:
                frac = (level - y0) / span
            frac = max(0.0, min(1.0, frac))
            return i, t[i - 1] + frac * (t[i] - t[i - 1])
        return None

    @staticmethod
    def _level_value(start: float, target: float, pct: float) -> float:
        return start + (pct / 100.0) * (target - start)

    @classmethod
    def _band_delta(cls, response: StepResponse, low_pct: float,
                    high_pct: float) -> Optional[float]:
        """Time between crossing the `low_pct` and `high_pct` fraction
        levels of the start->target transition.

        Works for both step directions: a decreasing step crosses the lower
        fraction (nearest the start level) before the higher fraction
        (nearest the target), which is the conventional 90%->10% fall time.
        """
        src = response.source
        t = response.t
        direction = response.direction
        if not src or direction == 0:
            return None
        low_level = cls._level_value(response.start_level, response.target, low_pct)
        high_level = cls._level_value(response.start_level, response.target, high_pct)
        lo = cls._cross(t, src, low_level, direction)
        if lo is None:
            return None
        hi = cls._cross(t, src, high_level, direction, start_index=lo[0])
        if hi is None:
            return None
        delta = hi[1] - lo[1]
        return delta if delta >= 0 else None
