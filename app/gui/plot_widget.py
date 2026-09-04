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
        self.curve = pg.PlotCurveItem(
            pen=pg.mkPen(color, width=1.5, style=style)
        )
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
        bottom = self._plot_item.getAxis("bottom")
        if dt and dt > 0:
            bottom.setTickSpacing(levels=[(float(dt), 0.0)])
        else:
            bottom.setTickSpacing()

    # -- data updates (real-time; never touches axis config) -------------------
    def update_signal_data(self, name: str, t: np.ndarray, y: np.ndarray) -> None:
        axis = self._axes.get(name)
        if axis is None or t is None or t.size == 0:
            return
        axis.curve.setData(t, y)
        t_max = float(t[-1])
        self._plot_item.setXRange(
            max(0.0, t_max - self._window_seconds), t_max, padding=0
        )

    def clear(self) -> None:
        for axis in self._axes.values():
            axis.curve.setData([], [])

    def set_window_seconds(self, seconds: float) -> None:
        self._window_seconds = max(1.0, seconds)

    def _sync_views(self) -> None:
        for axis in self._axes.values():
            axis.view_box.setGeometry(self._plot_item.vb.sceneBoundingRect())
            axis.view_box.linkedViewChanged(self._plot_item.vb, axis.view_box.XAxis)
