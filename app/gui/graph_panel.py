"""One independent analysis panel (a "workspace leaf").

A single `GraphPanel` owns everything that makes up one analysis view so
panels never share mutable state:

- its own `SignalManager` (processors + plot history buffers),
- a `SignalPanel` (signal configuration table),
- a `PlotWidget` and a `LiveValueTable`.

The widget is a tabbed view:
    [Plot] [Signal Configuration]

The Plot tab is itself a horizontal splitter with the narrow Name/Value
readout on the left and the graph on the right (draggable divider). The
Signal Configuration tab edits *this* panel's signals only - changing one
panel never affects another.

All packets are delivered to every panel (see MainWindow.on_packet); each
panel computes only its own enabled signals. Plot redraws are throttled
by a shared timer in MainWindow calling `refresh_plot()`.
"""
from __future__ import annotations

from typing import List

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QTabWidget,
    QToolButton, QMenu,
)

from models.packet import Packet
from models.signal_config import SignalConfig
from processing.signal_manager import SignalManager
from gui.live_value_table import LiveValueTable
from gui.plot_widget import PlotWidget
from gui.signal_panel import SignalPanel

_INITIAL_TABLE_FRACTION = 0.22


class GraphPanel(QWidget):
    activated = Signal()                  # user interacted with this panel
    splitRequested = Signal(object)       # Qt.Orientation
    closeRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._signal_manager = SignalManager()
        self._sized = False

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # -- slim header: panel options menu --------------------------------
        header = QHBoxLayout()
        header.setContentsMargins(4, 2, 4, 2)
        header.addStretch(1)

        self._menu_btn = QToolButton(self)
        self._menu_btn.setText("\u22ee")  # vertical ellipsis
        self._menu_btn.setToolTip("Panel options")
        self._menu_btn.setPopupMode(QToolButton.InstantPopup)
        self._menu_btn.setAutoRaise(True)

        menu = QMenu(self._menu_btn)
        split_right = menu.addAction("Split Panel \u2192 Right")
        split_down = menu.addAction("Split Panel \u2193 Below")
        menu.addSeparator()
        self._close_action = menu.addAction("Close Panel")
        menu.aboutToShow.connect(self.activated)

        split_right.triggered.connect(
            lambda: self.splitRequested.emit(Qt.Horizontal)
        )
        split_down.triggered.connect(
            lambda: self.splitRequested.emit(Qt.Vertical)
        )
        self._close_action.triggered.connect(self.closeRequested)
        self._menu_btn.setMenu(menu)

        header.addWidget(self._menu_btn)
        root.addLayout(header)

        # -- tabbed body ------------------------------------------------------
        self.tabs = QTabWidget(self)
        root.addWidget(self.tabs, 1)

        plot_page = QWidget()
        plot_layout = QVBoxLayout(plot_page)
        plot_layout.setContentsMargins(0, 0, 0, 0)

        self.plot_split = QSplitter(Qt.Horizontal, plot_page)
        self.value_table = LiveValueTable(self.plot_split)
        self.plot_widget = PlotWidget(self.plot_split)
        self.plot_split.addWidget(self.value_table)
        self.plot_split.addWidget(self.plot_widget)
        self.plot_split.setStretchFactor(0, 0)
        self.plot_split.setStretchFactor(1, 1)
        self.plot_split.setCollapsible(0, True)
        self.plot_split.setCollapsible(1, False)
        plot_layout.addWidget(self.plot_split)
        self.tabs.addTab(plot_page, "Plot")

        self.signal_panel = SignalPanel()
        self.tabs.addTab(self.signal_panel, "Signal Configuration")

        # -- internal wiring: this panel's config -> this panel's data -------
        self.signal_panel.signalsChanged.connect(self._on_signals_changed)
        self.signal_panel.signalEnabledChanged.connect(self._on_signals_changed)

    # -- configuration -------------------------------------------------------
    def set_signals(self, configs: List[SignalConfig]) -> None:
        self.signal_panel.set_configs(configs)
        self._on_signals_changed()

    def get_configs(self) -> List[SignalConfig]:
        return self.signal_panel.get_configs()

    def _on_signals_changed(self) -> None:
        configs = self.signal_panel.get_configs()
        self._signal_manager.set_signals(configs)
        self._resync_plot_axes()
        self.value_table.set_names([c.name for c in configs if c.enabled])

    def _resync_plot_axes(self) -> None:
        enabled = [c for c in self.signal_panel.get_configs() if c.enabled]
        enabled_names = {c.name for c in enabled}
        for cfg in enabled:
            self.plot_widget.add_or_update_signal(cfg.name, cfg.y_min, cfg.y_max)
        for existing in self.plot_widget.signal_names():
            if existing not in enabled_names:
                self.plot_widget.remove_signal(existing)

    # -- runtime data --------------------------------------------------------
    def on_packet(self, packet: Packet) -> None:
        self._signal_manager.on_packet(packet)
        self.value_table.update_values(
            self._signal_manager.get_latest_signal_outputs()
        )

    def refresh_plot(self) -> None:
        for cfg in self.signal_panel.get_configs():
            if not cfg.enabled:
                continue
            t, y = self._signal_manager.get_plot_data(cfg.name)
            if t is not None and t.size:
                self.plot_widget.update_signal_data(cfg.name, t, y)

    def clear(self) -> None:
        self._signal_manager.clear_all()
        self.plot_widget.clear()
        self.value_table.clear_values()

    # -- workspace integration ----------------------------------------------
    def set_can_close(self, can_close: bool) -> None:
        self._close_action.setEnabled(can_close)
        if not can_close:
            self._close_action.setToolTip("At least one panel is required")

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._sized:
            self._sized = True
            width = max(self.plot_split.width(), 320)
            table_w = max(150, int(width * _INITIAL_TABLE_FRACTION))
            self.plot_split.setSizes(
                [table_w, max(table_w, width - table_w)]
            )
