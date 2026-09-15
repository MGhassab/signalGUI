"""One shared-time-axis plot supporting an independent Y-axis per
enabled signal.

Each panel owns one PlotWidget instance (a "single graph" widget). Per
signal we never create a separate PlotWidget - instead, multiple
independent Y-axes on one shared X (time) axis are implemented with
pyqtgraph's standard "multiple ViewBoxes layered on one PlotItem" pattern
(the same technique used in pyqtgraph's own "MultiplePlotAxes" example):

- One base `PlotItem` supplies the shared X axis, grid, and legend.
- Every additional enabled signal gets its own `pg.ViewBox` (not a new
  PlotItem/new plot) plus its own `AxisItem`, both layered into the same
  scene and X-linked to the base PlotItem's ViewBox. This is what lets
  each signal have a completely different Y range/scale while staying on
  one graph and one shared time vector.

Axis configuration vs. live plot state
--------------------------------------
Signal configuration (y_min / y_max / dY) is applied to an axis ONLY when
that axis' configuration actually changes (`sync_axis_config` compares a
recorded "applied" tuple and is otherwise a no-op). The real-time update
loop only feeds curve data + the shared X range; it never reconfigures any
axis, so manual user adjustments (mouse wheel / pan) are never overwritten
by incoming data.

Tick spacing (dY / dT) is applied once when the configuration is applied.
On the FIRST manual wheel/pan on an axis the fixed tick override is
released to pyqtgraph's adaptive tick engine (via `sigRangeChangedManually`).
This keeps the configured step as the initial scale while guaranteeing that
zooming outward never explodes the number of forced tick labels (which is
what previously froze the UI).

Redraws only update the curve data for the signal(s) that changed
(`setData` on an existing PlotCurveItem) - the whole scene is never
rebuilt on every packet, and a bounded ring buffer (see
processing/ring_buffer.py) keeps the plotted history from growing without
limit.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import numpy as np
import pyqtgraph as pg

from PySide6.QtCore import Qt

_AXIS_COLORS = [
    "#1f77b4", "#d62728", "#2ca02c", "#9467bd",
    "#ff7f0e", "#17becf", "#e377c2", "#8c564b",
]

# Display-only smoothing. Raw device samples arrive at ~20 Hz; drawing them as
# straight chords makes a trace look angular/stair-stepped once you zoom in.
# Before handing the data to pyqtgraph we resample it with a shape-preserving
# cubic (PCHIP) so the drawn line follows a smooth curve. This never changes
# the stored/semantic data - only what is painted. The cap keeps the render
# cost bounded regardless of how much history is buffered.
SMOOTH_DISPLAY = True
DISPLAY_POINTS_PER_SECOND = 120
MAX_RENDER_POINTS = 4000


def _pchip_display_resample(x: np.ndarray, y: np.ndarray,
                            points_per_second: int,
                            max_output: int) -> Tuple[np.ndarray, np.ndarray]:
    """Vectorized shape-preserving cubic (PCHIP) resample for DISPLAY ONLY.

    Unlike a natural cubic spline, PCHIP does not overshoot, so genuine steps
    and extrema are not exaggerated (important for step responses and
    criteria metrics). Returns the input unchanged for degenerate inputs.
    """
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    if x.size < 3:
        return x, y

    # Drop duplicate/non-increasing x samples (defensive; t is monotonic).
    keep = np.r_[True, np.diff(x) > 1e-12]
    x = x[keep]
    y = y[keep]
    n = x.size
    if n < 3:
        return x, y

    duration = x[-1] - x[0]
    if duration <= 0.0:
        return x, y

    n_out = min(max_output, max(n, int(duration * points_per_second) + 1))
    xd = np.linspace(x[0], x[-1], n_out)

    h = np.diff(x)
    delta = np.diff(y) / h
    m = np.zeros(n, dtype=float)

    dl = delta[:-1]
    dr = delta[1:]
    same_sign = (dl * dr) > 0.0
    h_prev = h[:-1]
    h_next = h[1:]
    w1 = 2.0 * h_next + h_prev
    w2 = h_next + 2.0 * h_prev
    interior = np.zeros(n - 2, dtype=float)
    valid = same_sign & (dl != 0.0) & (dr != 0.0)
    interior[valid] = (w1[valid] + w2[valid]) / (
        w1[valid] / dl[valid] + w2[valid] / dr[valid]
    )
    m[1:-1] = interior

    def endpoint(h0, h1, d0, d1):
        slope = ((2.0 * h0 + h1) * d0 - h0 * d1) / (h0 + h1)
        if np.sign(slope) != np.sign(d0):
            return 0.0
        if np.sign(d0) != np.sign(d1) and abs(slope) > abs(3.0 * d0):
            return 3.0 * d0
        return slope

    m[0] = endpoint(h[0], h[1], delta[0], delta[1])
    m[-1] = endpoint(h[-1], h[-2], delta[-1], delta[-2])

    idx = np.clip(np.searchsorted(x, xd, side="right") - 1, 0, n - 2)
    x0 = x[idx]
    x1 = x[idx + 1]
    y0 = y[idx]
    y1 = y[idx + 1]
    m0 = m[idx]
    m1 = m[idx + 1]

    hi = x1 - x0
    t = (xd - x0) / hi
    t2 = t * t
    t3 = t2 * t
    h00 = 2.0 * t3 - 3.0 * t2 + 1.0
    h10 = t3 - 2.0 * t2 + t
    h01 = -2.0 * t3 + 3.0 * t2
    h11 = t3 - t2

    yd = h00 * y0 + h10 * hi * m0 + h01 * y1 + h11 * hi * m1
    return xd, yd


class _SignalAxis:
    """One signal's independent Y ViewBox + AxisItem + curve.

    Derived (criteria) signals are drawn dashed so raw/input signals and
    computed metrics are visually distinct in the same graph.
    """

    def __init__(self, color: str, derived: bool = False):
        self.view_box = pg.ViewBox()
        self.axis = pg.AxisItem("right")
        self.axis.setPen(color)
        self.axis.setTextPen(color)
        style = Qt.DashLine if derived else Qt.SolidLine
        # Round joins/caps avoid the hard notches where segments meet, and
        # antialias=True smooths the edges (also set globally in main.py, but
        # set per-curve so the widget is smooth wherever it is used).
        pen = pg.mkPen(color, width=1.5, style=style)
        pen.setJoinStyle(Qt.RoundJoin)
        pen.setCapStyle(Qt.RoundCap)
        self.curve = pg.PlotCurveItem(pen=pen, antialias=True)
        self.view_box.addItem(self.curve)


class PlotWidget(pg.GraphicsLayoutWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setBackground("w")
        self._plot_item: pg.PlotItem = self.addPlot(row=0, col=0)
        self._plot_item.showGrid(x=True, y=True, alpha=0.3)
        self._plot_item.setLabel("bottom", "Time", units="s")
        self._legend = self._plot_item.addLegend(offset=(10, 10))

        self._axes: Dict[str, _SignalAxis] = {}
        self._applied: Dict[str, Tuple[float, float, float, bool]] = {}
        self._next_color_idx = 0
        self._window_seconds: float = 30.0  # auto-scrolling time window
        self._time_tick_step: float = 0.0  # configured X major tick step
        self._display_smooth: bool = SMOOTH_DISPLAY

        self._plot_item.vb.sigResized.connect(self._sync_views)
        self._plot_item.vb.sigRangeChangedManually.connect(
            self._on_base_manual_range
        )

    # -- axis configuration ---------------------------------------------------
    def signal_names(self) -> List[str]:
        return list(self._axes.keys())

    def sync_axis_config(self, name: str, y_min: float, y_max: float,
                         dy: float, derived: bool = False) -> None:
        """Apply signal configuration to an axis, but only when it changed.

        Recorded config == current config => no-op, so unrelated updates
        (e.g. enabling another signal, or real-time refreshes) never reset
        an axis that the user may have adjusted manually.
        """
        cfg = (float(y_min), float(y_max), float(dy), bool(derived))
        if name in self._axes and self._applied.get(name) == cfg:
            return

        if name not in self._axes:
            self._add_signal(name, y_min, y_max, derived)
        else:
            self._axes[name].view_box.setYRange(y_min, y_max, padding=0)
        self._apply_y_tick_override(name, dy)
        self._applied[name] = cfg

    def _add_signal(self, name: str, y_min: float, y_max: float,
                    derived: bool) -> None:
        color = _AXIS_COLORS[self._next_color_idx % len(_AXIS_COLORS)]
        self._next_color_idx += 1

        axis = _SignalAxis(color, derived=derived)
        self._axes[name] = axis

        axis.view_box.setYRange(y_min, y_max, padding=0)
        axis.view_box.setXLink(self._plot_item.vb)
        # First manual interaction on this axis -> release fixed tick override.
        axis.view_box.sigRangeChangedManually.connect(
            lambda _mask, n=name: self._on_signal_manual_range(n)
        )

        col = self.ci.layout.columnCount()
        self.addItem(axis.axis, row=0, col=col)
        self.scene().addItem(axis.view_box)
        axis.axis.linkToView(axis.view_box)

        self._legend.addItem(axis.curve, name)
        self._sync_views()

    def remove_signal(self, name: str) -> None:
        axis = self._axes.pop(name, None)
        self._applied.pop(name, None)
        if axis is None:
            return
        self._legend.removeItem(axis.curve)
        self.scene().removeItem(axis.view_box)
        self.removeItem(axis.axis)

    def reset_axes(self) -> None:
        """Force every signal axis back to its configured y_min/y_max and
        restore the fixed dY tick override. This deliberately overrides any
        manual zoom/pan the user applied, which is what a plot reset needs.
        Also restores the configured time (X) tick step and re-scrolls the
        window to the latest sample."""
        for name, cfg in list(self._applied.items()):
            axis = self._axes.get(name)
            if axis is None:
                continue
            y_min, y_max, dy, _derived = cfg
            axis.view_box.setYRange(float(y_min), float(y_max), padding=0)
            self._apply_y_tick_override(name, dy)
        self._reapply_time_ticks()
        # Re-scroll the time window to the latest sample if any data exists.
        # Guard the degenerate case (no data => X window is empty): calling
        # setXRange with min==max collapses the view to zero width and turns
        # the plot blank/white, and it may not recover on the next update.
        latest: float = 0.0
        has_any: bool = False
        for axis in self._axes.values():
            t, _y = axis.curve.getData()
            if t is not None and len(t):
                has_any = True
                cand = float(t[-1])
                if cand > latest:
                    latest = cand
        if has_any:
            # Match the live-update path exactly: a plain setXRange window.
            self._plot_item.setXRange(
                max(0.0, latest - self._window_seconds), latest, padding=0
            )
        else:
            # Empty plot after a reset: keep a sane default window instead of
            # collapsing to a zero-width [0,0] view (which renders blank).
            self._plot_item.setXRange(0.0, self._window_seconds, padding=0)

    def _reapply_time_ticks(self) -> None:
        """Re-apply the panel's configured time-tick step if one is stored,
        else leave the axis on adaptive ticks."""
        if self._time_tick_step and self._time_tick_step > 0:
            self._plot_item.getAxis("bottom").setTickSpacing(
                levels=[(float(self._time_tick_step), 0.0)]
            )

    def clear_signal(self, name: str) -> None:
        """Empty one signal's curve (e.g. when paused before that signal's
        earliest sample so it must not keep stale data on screen)."""
        axis = self._axes.get(name)
        if axis is not None:
            axis.curve.setData([], [])

    # -- manual interaction: release fixed tick overrides ---------------------
    def _on_signal_manual_range(self, name: str) -> None:
        """User wheel/pan on signal axis: keep the manual range but return
        that axis to adaptive ticks (no more forced spacing)."""
        axis = self._axes.get(name)
        if axis is not None:
            axis.axis.setTickSpacing()  # -> adaptive
        self._release_time_ticks()

    def _on_base_manual_range(self, _mask) -> None:
        self._release_time_ticks()

    def _release_time_ticks(self) -> None:
        self._plot_item.getAxis("bottom").setTickSpacing()  # adaptive

    # -- explicit tick application (config-driven only) -----------------------
    def _apply_y_tick_override(self, name: str, dy: float) -> None:
        axis = self._axes.get(name)
        if axis is None:
            return
        if dy and dy > 0:
            axis.axis.setTickSpacing(levels=[(float(dy), 0.0)])
        else:
            axis.axis.setTickSpacing()

    def set_time_tick_step(self, dt: float) -> None:
        """Set the major tick step on the shared time (X) axis (display only).

        Only called when the panel's dT configuration is explicitly applied.
        A manual X interaction releases it back to adaptive ticks.
        """
        self._time_tick_step = float(dt)
        bottom = self._plot_item.getAxis("bottom")
        if dt and dt > 0:
            bottom.setTickSpacing(levels=[(float(dt), 0.0)])
        else:
            bottom.setTickSpacing()

    def set_display_smoothing(self, enabled: bool) -> None:
        """Enable/disable the display-only PCHIP resampling of curve data.

        Disabling makes `curve.getData()` expose the raw samples (used by the
        plot-alignment tests, which assert on exact sample counts/values).
        """
        self._display_smooth = bool(enabled)

    # -- data updates (real-time; never touches axis config) -------------------
    def update_signal_data(self, name: str, t: np.ndarray, y: np.ndarray) -> None:
        axis = self._axes.get(name)
        if axis is None or t is None or t.size == 0:
            return
        if self._display_smooth and y.size >= 3:
            plot_t, plot_y = _pchip_display_resample(
                t, y, DISPLAY_POINTS_PER_SECOND, MAX_RENDER_POINTS
            )
        else:
            plot_t, plot_y = t, y
        axis.curve.setData(plot_t, plot_y)
        t_max = float(t[-1])
        self._plot_item.setXRange(
            max(0.0, t_max - self._window_seconds), t_max, padding=0
        )

    def clear_curves(self) -> None:
        # IMPORTANT: this must NOT be named ``clear``. pyqtgraph's
        # GraphicsLayoutWidget.__init__ does
        #   setattr(self, "clear", getattr(self.ci, "clear"))
        # which installs an instance attribute that shadows any class method
        # named ``clear``. Calling self.plot_widget.clear() would therefore
        # invoke GraphicsLayout.clear(), which *removes every graphics item
        # from the plot layout* - leaving a blank/white plot. Hence the
        # distinct name.
        for axis in self._axes.values():
            axis.curve.setData([], [])

    def set_window_seconds(self, seconds: float) -> None:
        self._window_seconds = max(1.0, seconds)

    def _sync_views(self) -> None:
        for axis in self._axes.values():
            axis.view_box.setGeometry(self._plot_item.vb.sceneBoundingRect())
            axis.view_box.linkedViewChanged(self._plot_item.vb, axis.view_box.XAxis)
