"""Per-panel Play/Pause + historical navigation state.

`PlaybackController` is pure logic (no Qt widgets): it tracks whether a
panel's DISPLAY is paused and, while paused, which sample index `n` of the
panel's shared sample timeline is shown. Data acquisition is intentionally
NOT paused - the signal buffers keep filling so the user can step back
through history or jump back to live at any time. Pausing one panel never
affects another: each `GraphPanel` owns its own controller.
"""
from __future__ import annotations

from typing import Optional


class PlaybackController:
    def __init__(self) -> None:
        self._paused = False
        self._cut: Optional[int] = None  # None => follow the live/latest sample

    # -- state ---------------------------------------------------------------
    @property
    def paused(self) -> bool:
        return self._paused

    def is_paused(self) -> bool:
        return self._paused

    def pause_at(self, latest_index: int) -> None:
        """Freeze the displayed view at the current live sample."""
        self._paused = True
        if self._cut is None:
            self._cut = max(1, latest_index)

    def resume(self) -> None:
        """Resume live display (also 'return to Latest')."""
        self._paused = False
        self._cut = None

    def toggle(self, latest_index: int) -> None:
        if self._paused:
            self.resume()
        else:
            self.pause_at(latest_index)

    # -- navigation ------------------------------------------------------------
    def display_end_index(self, latest_index: int) -> int:
        """Which sample (exclusive end) the view should show."""
        if not self._paused or self._cut is None:
            return latest_index
        return min(max(0, self._cut), latest_index)

    def step(self, delta: int, latest_index: int) -> None:
        """Move the frozen view by `delta` samples (backward/forward)."""
        if not self._paused:
            return
        current = self.display_end_index(latest_index)
        self._cut = min(max(1, current + delta), max(1, latest_index))

    def back(self, latest_index: int) -> None:
        self.step(-1, latest_index)

    def forward(self, latest_index: int) -> None:
        self.step(1, latest_index)
