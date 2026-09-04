"""Common processing interface for all signal types.

Every processor consumes one raw packet-field value at a time (already
extracted from a `Packet` by `SignalManager`) plus a monotonic sample
time, and produces output samples. Processors are stateful (holding
history where needed) so they must be re-created (or `reset()`) whenever
their configuration changes.

Processors emit output samples rather than return a single value, because
some operations (e.g. a phase-accurate centered derivative) only finish an
output sample some time AFTER the input sample that completes it arrives,
and that output belongs to an EARLIER sample time. `process(value, t)`
therefore yields zero-or-more `(sample_time, value)` pairs in chronological
order; most processors yield exactly one `(t, value)`.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Iterable, Tuple


class SignalProcessor(ABC):
    def __init__(self, config):
        self.config = config

    @abstractmethod
    def process(self, raw_value: float, t: float) -> Iterable[Tuple[float, float]]:
        """Consume one new raw sample arriving at measured time `t`.

        Yields zero or more completed output samples as `(sample_time,
        value)` in chronological order. Must never raise, and must never
        yield NaN/Inf - clamp/guard internally instead so the plot and UI
        stay stable.
        """

    def reset(self) -> None:
        """Clear any internal history/state (e.g. on reconnect or when
        the graph is cleared)."""
        pass

    def _apply_gain_offset(self, raw_value: float) -> float:
        return raw_value * self.config.gain + self.config.offset
