"""Per-panel Play/Pause + historical navigation state.

`PlaybackController` is pure logic (no Qt widgets): it tracks whether a
panel's DISPLAY is paused and, while paused, which point of the panel's
shared TIME axis is shown. The playhead is a TIME on the global acquisition
timeline (not a sample index), because signals on a panel can have
different start times (a signal enabled mid-session begins later than its
older siblings). Slicing every signal by a single shared sample index is
only valid when every signal started on the same packet, so alignment is
done on time instead - see GraphPanel.refresh_plot.

Data acquisition is intentionally NOT paused - the signal buffers keep
filling so the user can step back through history or jump back to live at
any time. Pausing one panel never affects another: each `GraphPanel` owns
its own controller.
"""
from __future__ import annotations

from typing import Optional


class PlaybackController:
    def __init__(self) -> None:
        self._paused = False
        self._cut: Optional[float] = None  # None => follow the live/latest sample

    # -- state ---------------------------------------------------------------
    @property
    def paused(self) -> bool:
        return self._paused

    def is_paused(self) -> bool:
        return self._paused

    def pause_at(self, latest_time: Optional[float]) -> None:
        """Freeze the displayed view at the given time (usually the live
        sample time of the panel)."""
        self._paused = True
        if latest_time is not None:
            self._cut = float(latest_time)

    def seek(self, cut_time: float) -> None:
        """Move the frozen view to a specific time on the shared axis."""
        self._paused = True
        self._cut = float(cut_time)

    def resume(self) -> None:
        """Resume live display (also 'return to Latest')."""
        self._paused = False
        self._cut = None

    def toggle(self, latest_time: Optional[float]) -> None:
        if self._paused:
            self.resume()
        else:
            self.pause_at(latest_time)

    # -- navigation ------------------------------------------------------------
    def cut_time(self) -> Optional[float]:
        """Time the frozen view currently shows (None = live)."""
        return self._cut
