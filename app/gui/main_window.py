"""Main application window: application controller / panel manager.

The main window is NOT a graph panel. It shows the panel manager list and
owns the app-level chrome (menus, toolbar, serial status). Graph panels
live in independent child tool windows (`PanelWindow`) registered here.

Responsibilities:

- the authoritative panel registry (`self._panels`),
- creating, hiding, reopening, renaming, deleting panels,
- menus: File / Window / Settings / Help + connection status,
- the single serial connection and packet fan-out to every registered panel,
- one shared, throttled plot-refresh timer.

Each `PanelWindow`/`GraphPanel` owns its own signal processing, playback
state, and data table, so panels are fully independent. The GUI never
touches serial bytes or packet parsing directly.
"""
from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import Qt, QEvent, QPoint, QTimer, Slot
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QInputDialog, QMessageBox,
    QFileDialog, QStatusBar, QLabel,
)

from gui.panel_manager import PanelManagerWidget
from gui.panel_window import PanelWindow
from gui.serial_config_dialog import prompt_serial_config

from models.packet import Packet
from models.app_config import AppConfig, PanelConfig
from serial_io.packet_parser import PacketParser, PacketFormat
from serial_io.serial_manager import SerialManager
from config.config_manager import ConfigManager

PLOT_REFRESH_MS = 50  # throttle GUI plot redraws independent of packet rate


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Embedded Device Monitor")
        self.resize(1000, 700)

        # Protocol interpretation is centralized here - change byte_order /
        # signed in one place if the wire format changes.
        self._packet_format = PacketFormat(byte_order="little", signed=False)
        self._parser = PacketParser(fmt=self._packet_format)
        self._serial = SerialManager(self._parser)

        self._serial_port: str = ""
        self._baud_rate: int = 115200

        # -- panel registry --------------------------------------------------
        self._panels: List[PanelWindow] = []
        self._panel_counter = 0
        self._last_active: Optional[PanelWindow] = None
        self._closing = False

        self._build_ui()
        self._wire_signals()
        self._build_menu()
        self._update_serial_actions()

        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)

        self._plot_timer = QTimer(self)
        self._plot_timer.setInterval(PLOT_REFRESH_MS)
        self._plot_timer.timeout.connect(self._refresh_all_plots)
        self._plot_timer.start()

        self._current_config_path: Optional[str] = None

    # -- UI construction ----------------------------------------------------
    def _build_ui(self) -> None:
        self.panel_manager = PanelManagerWidget()
        self.setCentralWidget(self.panel_manager)

        status_bar = QStatusBar()
        self.setStatusBar(status_bar)
        self._status_label = QLabel()
        status_bar.addPermanentWidget(self._status_label)
        self._render_status_label(False)

    def _build_menu(self) -> None:
        menu_bar = self.menuBar()

        # -- File ---------------------------------------------------------
        file_menu = menu_bar.addMenu("&File")
        file_menu.addAction("Save Configuration...", self._on_save_config)
        file_menu.addAction("Load Configuration...", self._on_load_config)
        file_menu.addAction("Reset Configuration", self._on_reset_config)
        file_menu.addSeparator()
        file_menu.addAction("Clear Active Panel Graph", self._on_clear_active_panel)
        file_menu.addSeparator()
        file_menu.addAction("E&xit", self.close)

        # -- Window ---------------------------------------------------------
        window_menu = menu_bar.addMenu("&Window")
        self._window_menu = window_menu
        self._new_panel_action = window_menu.addAction("&New Panel")
        self._new_panel_action.triggered.connect(lambda: self.new_panel())
        self._win_sep = window_menu.addSeparator()
        self._window_actions: List[object] = []  # dynamic per-panel entries
        self._win_sep2 = window_menu.addSeparator()
        self._hide_action = window_menu.addAction("&Hide Panel")
        self._hide_action.triggered.connect(self._hide_active_panel)
        self._delete_action = window_menu.addAction("&Delete Panel")
        self._delete_action.triggered.connect(self._delete_active_panel)
        self._refresh_panel_ui()

        # Toolbar: reuse the same "New Panel" action.
        self.addToolBar("Main").addAction(self._new_panel_action)

        # -- Settings ---------------------------------------------------------
        settings_menu = menu_bar.addMenu("&Settings")
        settings_menu.addAction("Serial Configuration...", self._on_serial_config)
        settings_menu.addSeparator()
        self._connect_action = settings_menu.addAction("&Connect")
        self._connect_action.triggered.connect(self._on_connect)
        self._disconnect_action = settings_menu.addAction("&Disconnect")
        self._disconnect_action.triggered.connect(self._serial.disconnect)

        # -- Help ---------------------------------------------------------------
        help_menu = menu_bar.addMenu("&Help")
        help_menu.addAction("About", self._on_about)

    def _wire_signals(self) -> None:
        self._serial.connected.connect(self._on_connected)
        self._serial.disconnected.connect(self._on_disconnected)
        self._serial.errorOccurred.connect(self._on_serial_error)
        self._serial.packetReceived.connect(self._on_packet)

        self.panel_manager.newRequested.connect(lambda: self.new_panel())
        self.panel_manager.showRequested.connect(self._manager_show)
        self.panel_manager.hideRequested.connect(self._manager_hide)
        self.panel_manager.renameRequested.connect(self._manager_rename)
        self.panel_manager.deleteRequested.connect(self._manager_delete)

    # -- panel registry --------------------------------------------------------
    def new_panel(self, signals: Optional[List] = None,
                  name: Optional[str] = None,
                  time_step: Optional[float] = None) -> PanelWindow:
        """Open a new independent panel window and register it."""
        if name:
            title = name
        else:
            self._panel_counter += 1
            title = f"Panel {self._panel_counter}"
            while any(p.panel_name() == title for p in self._panels):
                self._panel_counter += 1
                title = f"Panel {self._panel_counter}"

        window = PanelWindow(
            self, title,
            signals=signals,
            time_step=time_step if time_step is not None else 1.0,
        )
        self._panels.append(window)
        self._refresh_panel_ui()

        base = self.frameGeometry().topLeft()
        offset = (len(self._panels) - 1) % 8
        window.move(base + QPoint(40 + 26 * offset, 40 + 26 * offset))
        window.show_panel()
        self._last_active = window
        if not self._closing:
            self.statusBar().showMessage(f"{title} opened.", 3000)
        return window

    # -- manager actions --------------------------------------------------------
    def _manager_show(self, window: PanelWindow) -> None:
        self._last_active = window
        window.show_panel()

    def _manager_hide(self, window: PanelWindow) -> None:
        window.hide_panel()

    def _manager_rename(self, window: PanelWindow) -> None:
        current = window.panel_name()
        new_name, ok = QInputDialog.getText(
            self, "Rename Panel", "Panel name:", text=current
        )
        new_name = new_name.strip()
        if ok and new_name and new_name != current:
            window.rename(new_name)
            self._refresh_panel_ui()
            self.statusBar().showMessage(
                f"Panel renamed to '{new_name}'.", 3000
            )

    def _manager_delete(self, window: PanelWindow) -> None:
        window.destroy_panel()

    def _hide_active_panel(self) -> None:
        window = self._last_active or (self._panels[0] if self._panels else None)
        if window is not None:
            window.hide_panel()

    def _delete_active_panel(self) -> None:
        window = self._last_active or (self._panels[0] if self._panels else None)
        if window is not None:
            window.destroy_panel()

    def _on_clear_active_panel(self) -> None:
        window = self._last_active or (self._panels[0] if self._panels else None)
        if window is not None:
            window.clear()
            self.statusBar().showMessage(
                f"{window.panel_name()} cleared.", 3000
            )

    def _on_panel_hidden(self, window: PanelWindow) -> None:
        """Panel window X pressed / hidden: stays registered."""
        self._refresh_panel_ui()

    def _on_panel_closed(self, window: PanelWindow) -> None:
        """A panel was really destroyed - remove it from the registry."""
        if window in self._panels:
            self._panels.remove(window)
        if self._last_active is window:
            self._last_active = None
        self._refresh_panel_ui()

    # -- UI refresh -------------------------------------------------------------
    @staticmethod
    def _panel_label(window: PanelWindow) -> str:
        paused = window.panel.playback().is_paused()
        tag = "paused" if paused else "live"
        if not window.isVisible():
            tag += ", hidden"
        return f"{window.panel_name()}  [{tag}]"

    def _refresh_panel_ui(self) -> None:
        # Panel Manager list
        self.panel_manager.refresh(
            [(w, self._panel_label(w)) for w in self._panels]
        )

        # Window menu dynamic section
        menu = self._window_menu
        for action in self._window_actions:
            menu.removeAction(action)
            action.deleteLater()
        self._window_actions = []
        if not self._panels:
            placeholder = menu.addAction("(no panels open)")
            placeholder.setEnabled(False)
            self._window_actions.append(placeholder)
        else:
            for window in self._panels:
                action = menu.addAction(self._panel_label(window))
                action.triggered.connect(
                    lambda _checked=False, w=window: self._manager_show(w)
                )
                self._window_actions.append(action)

        any_open = bool(self._panels)
        self._hide_action.setEnabled(any_open)
        self._delete_action.setEnabled(any_open)

    # -- serial connection lifecycle -----------------------------------------
    def _on_serial_config(self) -> None:
        result = prompt_serial_config(
            port=self._serial_port, baud=self._baud_rate, parent=self
        )
        if result is None:
            return
        self._serial_port, self._baud_rate = result
        self._render_status_label(self._serial.is_connected)
        self.statusBar().showMessage(
            "Serial settings saved - they apply on the next connect.", 4000
        )

    def _on_connect(self) -> None:
        if not self._serial_port:
            self._on_serial_config()
            if not self._serial_port:
                return
        self._serial.connect_to(self._serial_port, self._baud_rate)

    @Slot()
    def _on_connected(self) -> None:
        self._update_serial_actions()
        self._render_status_label(True)

    @Slot(str)
    def _on_disconnected(self, reason: str) -> None:
        self._update_serial_actions()
        self._render_status_label(False)
        if reason:
            self.statusBar().showMessage(f"Disconnected: {reason}", 5000)

    @Slot(str)
    def _on_serial_error(self, message: str) -> None:
        self._update_serial_actions()
        self._render_status_label(False)
        QMessageBox.warning(self, "Serial Error", message)

    def _update_serial_actions(self) -> None:
        connected = self._serial.is_connected
        self._connect_action.setEnabled(not connected)
        self._disconnect_action.setEnabled(connected)

    def _render_status_label(self, connected: bool) -> None:
        if connected:
            self._status_label.setText(
                f"\u25cf Connected \u00b7 {self._serial_port} @ {self._baud_rate}"
            )
            self._status_label.setStyleSheet("color: #1b8a3d; font-weight: 600;")
        else:
            self._status_label.setText("\u25cf Disconnected")
            self._status_label.setStyleSheet("color: #b00020; font-weight: 600;")

    # -- packets + plotting ----------------------------------------------------
    @Slot(object)
    def _on_packet(self, packet: Packet) -> None:
        for window in list(self._panels):
            window.on_packet(packet)

    def _refresh_all_plots(self) -> None:
        for window in list(self._panels):
            window.refresh_plot()

    # -- configuration persistence -----------------------------------------------
    def _current_app_config(self) -> AppConfig:
        panels = [
            PanelConfig(
                name=window.panel_name(),
                dt=window.get_time_step(),
                signals=window.get_configs(),
            )
            for window in self._panels
        ]
        return AppConfig(
            serial_port=self._serial_port,
            baud_rate=self._baud_rate,
            panels=panels,
        )

    def _apply_app_config(self, config: AppConfig) -> None:
        self._serial_port = config.serial_port
        self._baud_rate = int(config.baud_rate or 115200)
        self._render_status_label(self._serial.is_connected)
        for window in list(self._panels):
            window.destroy_panel()
        for panel in config.panels:
            self.new_panel(
                signals=panel.signals,
                name=panel.name or None,
                time_step=panel.dt,
            )

    def _on_save_config(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Configuration", "config.json", "JSON Files (*.json)"
        )
        if not path:
            return
        try:
            ConfigManager.save(self._current_app_config(), path)
            self._current_config_path = path
            self.statusBar().showMessage(f"Configuration saved to {path}", 4000)
        except OSError as exc:
            QMessageBox.critical(self, "Save Failed", str(exc))

    def _on_load_config(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Load Configuration", "", "JSON Files (*.json)"
        )
        if not path:
            return
        try:
            config = ConfigManager.load(path)
            self._apply_app_config(config)
            self._current_config_path = path
            self.statusBar().showMessage(f"Configuration loaded from {path}", 4000)
        except (OSError, ValueError, KeyError) as exc:
            QMessageBox.critical(self, "Load Failed", str(exc))

    def _on_reset_config(self) -> None:
        reply = QMessageBox.question(
            self, "Reset Configuration",
            "Discard all configuration, delete all panels, "
            "and reset serial settings?",
        )
        if reply == QMessageBox.Yes:
            self._apply_app_config(ConfigManager.default())

    def _on_about(self) -> None:
        QMessageBox.about(
            self, "About Embedded Device Monitor",
            "Embedded Device Monitor\n\n"
            "Multi-panel monitor for a 42-field serial packet stream.\n"
            "Open independent graph panels via Window \u2192 New Panel.",
        )

    # -- global active-window tracking ------------------------------------------
    def eventFilter(self, obj, event) -> bool:
        if event.type() in (QEvent.FocusIn, QEvent.WindowActivate):
            node = obj if isinstance(obj, QWidget) else None
            while isinstance(node, QWidget):
                if isinstance(node, PanelWindow):
                    if self._last_active is not node:
                        self._last_active = node
                    break
                node = node.parentWidget()
        return super().eventFilter(obj, event)

    def closeEvent(self, event) -> None:
        self._closing = True
        self._plot_timer.stop()
        self._serial.disconnect()
        for window in list(self._panels):
            window.destroy_panel()
        super().closeEvent(event)
