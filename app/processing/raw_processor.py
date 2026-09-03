"""Data Type 1: Raw Data.

output = received_value * gain + offset
"""
from __future__ import annotations

from processing.base_processor import SignalProcessor


class RawProcessor(SignalProcessor):
    def process(self, raw_value: float, t: float) -> float:
        return self._apply_gain_offset(raw_value)
