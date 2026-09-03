"""A graph panel presented as its own top-level child tool window.

Each `PanelWindow` is a real OS window parented to the `MainWindow`
(`Qt.Window`), so the user can freely move, resize, overlap, and stack
panels anywhere on screen while they stay associated with the main window
(they float above it and are closed automatically when it closes).

The window's *content* is a single `GraphPanel` (Plot / Signal
Configuration tabs). A `PanelWindow` has no signal/plot timers of its own -
plot refresh is driven by the shared timer in `MainWindow`, which only
iterates the currently registered windows.

Lifecycle contract (fixes the previous close/Cancel bug at the source):

- `MainWindow` is the registry owner: it creates windows via
  `new_panel()`, keeps the authoritative list, and rebuilds the Window
  menu on every open/close.
- `closeEvent` notifies `MainWindow._on_panel_closed(self)` *before*
  accepting, so the window is synchronously removed from the registry and
  every reference to it is dropped. `WA_DeleteOnClose` then destroys the
  Qt object. Nothing is merely hidden, so no ghost panel can remain.
- Closing one panel never touches other panels or the main window.
"""
from __future__ import annotations

from typing import List

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMainWindow

from models.packet import Packet
from models.signal_config import SignalConfig
from gui.graph_panel import GraphPanel

_DEFAULT_WIDTH = 820
_DEFAULT_HEIGHT = 560


class PanelWindow(QMainWindow):
    def __init__(self, manager, title: str,
                 signals: List[SignalConfig] | None = None):
        super().__init__(manager)
        self._manager = manager
        self.setWindowFlags(Qt.Window)
        self.setWindowTitle(title)
        self.resize(_DEFAULT_WIDTH, _DEFAULT_HEIGHT)
        self.setAttribute(Qt.WA_DeleteOnClose, True)

        self.panel = GraphPanel(self)
        self.setCentralWidget(self.panel)
        if signals:
            self.panel.set_signals(signals)

    # -- configuration -------------------------------------------------------
    def set_signals(self, configs: List[SignalConfig]) -> None:
        self.panel.set_signals(configs)

    def get_configs(self) -> List[SignalConfig]:
        return self.panel.get_configs()

    # -- runtime data --------------------------------------------------------
    def on_packet(self, packet: Packet) -> None:
        self.panel.on_packet(packet)

    def refresh_plot(self) -> None:
        self.panel.refresh_plot()

    def clear(self) -> None:
        self.panel.clear()

    # -- lifecycle ---------------------------------------------------------------
    def closeEvent(self, event) -> None:
        """Deregister from the main window before the window is destroyed."""
        self._manager._on_panel_closed(self)
        super().closeEvent(event)
