"""A graph panel presented as its own top-level child tool window.

Each `PanelWindow` is a real OS window parented to the `MainWindow`
(`Qt.Window`), so the user can freely move, resize, overlap, and stack
panels anywhere on screen while they stay associated with the main window.

The window's *content* is a single `GraphPanel` (Plot / Signal
Configuration tabs + per-panel playback controls). A `PanelWindow` has no
timers of its own - plot refresh is driven by the shared timer in
`MainWindow`, which only iterates the currently registered windows.

Lifecycle:

- Closing the window (X / menu Hide) only HIDES it: the panel stays
  registered in the `MainWindow` with all its configuration and data, and
  can be reopened at any time. Closing a panel never closes the Main
  Window.
- Deleting a panel (`destroy_panel`, used by the Panel Manager / Delete
  action) truly removes it: it is deregistered from the Main Window and
  the widget is destroyed, releasing its resources.
"""
from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMainWindow

from models.packet import Packet
from models.signal_config import SignalConfig
from gui.graph_panel import GraphPanel

_DEFAULT_WIDTH = 820
_DEFAULT_HEIGHT = 560


class PanelWindow(QMainWindow):
    def __init__(self, manager, title: str,
                 signals: List[SignalConfig] | None = None,
                 time_step: float = 1.0):
        super().__init__(manager)
        self._manager = manager
        self._destroying = False
        self.setWindowFlags(Qt.Window)
        self.setWindowTitle(title)
        self.resize(_DEFAULT_WIDTH, _DEFAULT_HEIGHT)

        self.panel = GraphPanel(self)
        self.panel.set_time_step(time_step)
        self.setCentralWidget(self.panel)
        if signals:
            self.panel.set_signals(signals)

    # -- panel identity -------------------------------------------------------
    def rename(self, title: str) -> None:
        self.setWindowTitle(title)

    def panel_name(self) -> str:
        return self.windowTitle()

    # -- configuration -------------------------------------------------------
    def set_signals(self, configs: List[SignalConfig]) -> None:
        self.panel.set_signals(configs)

    def get_configs(self) -> List[SignalConfig]:
        return self.panel.get_configs()

    def get_time_step(self) -> float:
        return self.panel.get_time_step()

    # -- runtime data --------------------------------------------------------
    def on_packet(self, packet: Packet, t: Optional[float] = None) -> None:
        self.panel.on_packet(packet, t)

    def begin_new_session(self) -> None:
        self.panel.begin_new_session()

    def refresh_plot(self) -> None:
        self.panel.refresh_plot()

    def clear(self) -> None:
        self.panel.clear()

    # -- show/hide ---------------------------------------------------------------
    def hide_panel(self) -> None:
        self.hide()

    def show_panel(self) -> None:
        self.show()
        self.raise_()
        self.activateWindow()

    # -- lifecycle ---------------------------------------------------------------
    def destroy_panel(self) -> None:
        """Really remove this panel (deregister + destroy)."""
        if self._destroying:
            return
        self._destroying = True
        self.close()
        self.deleteLater()

    def closeEvent(self, event) -> None:
        if self._destroying or self._manager._closing:
            self._manager._on_panel_closed(self)
            super().closeEvent(event)
        else:
            # User pressed X: hide, keep registered with config/data intact.
            event.ignore()
            self.hide()
            self._manager._on_panel_hidden(self)
