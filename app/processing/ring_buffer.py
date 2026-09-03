"""Fixed-capacity, numpy-backed ring buffer used to hold plot history.

Bounded so memory does not grow unboundedly during long acquisitions, and
so the plot never needs to redraw an ever-growing historical dataset -
only the last `capacity` samples are ever kept.
"""
from __future__ import annotations

import numpy as np


class RingBuffer:
    def __init__(self, capacity: int):
        self.capacity = capacity
        self._data = np.full(capacity, np.nan, dtype=np.float64)
        self._write_idx = 0
        self._count = 0

    def append(self, value: float) -> None:
        self._data[self._write_idx] = value
        self._write_idx = (self._write_idx + 1) % self.capacity
        self._count = min(self._count + 1, self.capacity)

    def as_array(self) -> np.ndarray:
        """Returns buffered values in chronological order (oldest first)."""
        if self._count < self.capacity:
            return self._data[: self._count]
        return np.concatenate(
            (self._data[self._write_idx:], self._data[: self._write_idx])
        )

    def clear(self) -> None:
        self._data.fill(np.nan)
        self._write_idx = 0
        self._count = 0

    def __len__(self) -> int:
        return self._count
