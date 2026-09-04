"""Criteria signal response window model.

A `StepResponse` is the data handed to a criterion calculator: the samples
captured between the moment a reference step began and the moment its new
plateau was confirmed (plus a short post-plateau tail used by settling
time).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List


@dataclass
class StepResponse:
    t: List[float]            # monotonic sample times within the segment
    source: List[float]       # source-signal values over the segment
    target: float             # confirmed reference plateau (final value)
    start_level: float        # source level just before the step began
    step_start_time: float    # t of the first transition sample

    @property
    def direction(self) -> int:
        """+1 when the step is upward, -1 downward, 0 flat."""
        delta = self.target - self.start_level
        if abs(delta) < 1e-12:
            return 0
        return 1 if delta > 0 else -1

    @property
    def amplitude(self) -> float:
        return abs(self.target - self.start_level)
