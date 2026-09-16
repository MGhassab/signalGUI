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
        """Returns buffered values in chronological order (oldest first).

        NOTE: for a not-yet-full buffer this is a VIEW into the internal
        storage. Callers that read from a different thread than the one
        appending must use `snapshot()` (a copy) instead.
        """
        if self._count < self.capacity:
            return self._data[: self._count]
        return np.concatenate(
            (self._data[self._write_idx:], self._data[: self._write_idx])
        )

    def snapshot(self) -> np.ndarray:
        """A detached copy of the buffered values (oldest first).

        Safe to hand to another thread: further appends cannot mutate it.
        """
        if self._count == 0:
            return np.empty(0, dtype=np.float64)
        if self._count < self.capacity:
            return self._data[: self._count].copy()
        return np.concatenate(
            (self._data[self._write_idx:], self._data[: self._write_idx])
        ).copy()

    def last(self) -> float:
        """Most recently appended value, or NaN if empty. O(1)."""
        if self._count == 0:
            return float("nan")
        return float(self._data[(self._write_idx - 1) % self.capacity])

    def first(self) -> float:
        """Oldest retained value, or NaN if empty. O(1)."""
        if self._count == 0:
            return float("nan")
        if self._count < self.capacity:
            return float(self._data[0])
        return float(self._data[self._write_idx])

    def grown(self, new_capacity: int) -> "RingBuffer":
        """Return a buffer with a larger capacity holding the same values in
        chronological order. At high sample rates this lets a signal retain
        the same TIME span (see SignalManager) instead of wrapping early -
        without inflating memory at low rates, where it is never needed."""
        if new_capacity <= self.capacity:
            return self
        bigger = RingBuffer(new_capacity)
        for value in self.as_array():
            bigger.append(float(value))
        return bigger

    def clear(self) -> None:
        self._data.fill(np.nan)
        self._write_idx = 0
        self._count = 0

    def __len__(self) -> int:
        return self._count
