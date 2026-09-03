"""Common processing interface for all signal types.

Every processor consumes one raw packet-field value at a time (already
extracted from a `Packet` by `SignalManager`) plus a monotonic sample
time, and produces one output sample. Processors are stateful (holding
history where needed) so they must be re-created (or `reset()`) whenever
their configuration changes.
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class SignalProcessor(ABC):
    def __init__(self, config):
        self.config = config

    @abstractmethod
    def process(self, raw_value: float, t: float) -> float:
        """Process one new raw sample. Returns the signal's output value
        for this sample. Must never raise, and must never return NaN/Inf -
        clamp/guard internally instead so the plot and UI stay stable.
        """

    def reset(self) -> None:
        """Clear any internal history/state (e.g. on reconnect or when
        the graph is cleared)."""
        pass

    def _apply_gain_offset(self, raw_value: float) -> float:
        return raw_value * self.config.gain + self.config.offset
