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

Redraws only update the curve data for the signal(s) that changed
(`setData` on an existing PlotCurveItem) - the whole scene is never
rebuilt on every packet, and a bounded ring buffer (see
processing/ring_buffer.py) keeps the plotted history from growing without
limit.
"""
from __future__ import annotations

from typing import Dict, List

import numpy as np
import pyqtgraph as pg

_AXIS_COLORS = [
    "#1f77b4", "#d62728", "#2ca02c", "#9467bd",
    "#ff7f0e", "#17becf", "#e377c2", "#8c564b",
]


class _SignalAxis:
    """One signal's independent Y ViewBox + AxisItem + curve."""

    def __init__(self, color: str):
        self.view_box = pg.ViewBox()
        self.axis = pg.AxisItem("right")
        self.axis.setPen(color)
        self.axis.setTextPen(color)
        self.curve = pg.PlotCurveItem(pen=pg.mkPen(color, width=1.5))
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
        self._next_color_idx = 0
        self._window_seconds: float = 30.0  # auto-scrolling time window

        self._plot_item.vb.sigResized.connect(self._sync_views)

    # -- signal lifecycle -------------------------------------------------
    def signal_names(self) -> List[str]:
        return list(self._axes.keys())

    def add_or_update_signal(self, name: str, y_min: float, y_max: float) -> None:
        if name in self._axes:
            self._axes[name].view_box.setYRange(y_min, y_max, padding=0)
            return

        color = _AXIS_COLORS[self._next_color_idx % len(_AXIS_COLORS)]
        self._next_color_idx += 1

        axis = _SignalAxis(color)
        self._axes[name] = axis

        axis.view_box.setYRange(y_min, y_max, padding=0)
        axis.view_box.setXLink(self._plot_item.vb)

        col = self.ci.layout.columnCount()
        self.addItem(axis.axis, row=0, col=col)
        self.scene().addItem(axis.view_box)
        axis.axis.linkToView(axis.view_box)

        self._legend.addItem(axis.curve, name)
        self._sync_views()

    def remove_signal(self, name: str) -> None:
        axis = self._axes.pop(name, None)
        if axis is None:
            return
        self._legend.removeItem(axis.curve)
        self.scene().removeItem(axis.view_box)
        self.removeItem(axis.axis)

    def set_signal_range(self, name: str, y_min: float, y_max: float) -> None:
        axis = self._axes.get(name)
        if axis:
            axis.view_box.setYRange(y_min, y_max, padding=0)

    # -- data updates -------------------------------------------------------
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
