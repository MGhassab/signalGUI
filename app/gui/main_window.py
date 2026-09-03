"""Main application window: hub that owns the single serial connection and
the multi-panel workspace.

Responsibilities here are deliberately thin:

- serial lifecycle (one `SerialManager` for the whole app),
- menus (File/Serial/Panel) + connection status in the status bar,
- fanning every decoded packet out to all open `GraphPanel`s,
- one shared, throttled plot-refresh timer.

Each `GraphPanel` owns its own `SignalManager`/plot/signal-config, so all
signal processing stays per-panel. The GUI never touches serial bytes or
packet parsing directly - it only receives fully-formed `Packet` objects.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, QEvent, QTimer, Slot
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QMessageBox,
    QFileDialog, QStatusBar, QLabel,
)

from gui.graph_panel import GraphPanel
from gui.workspace import Workspace
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
        self.resize(1400, 900)

        # Protocol interpretation is centralized here - change byte_order /
        # signed in one place if the wire format changes.
        self._packet_format = PacketFormat(byte_order="little", signed=False)
        self._parser = PacketParser(fmt=self._packet_format)
        self._serial = SerialManager(self._parser)

        self._serial_port: str = ""
        self._baud_rate: int = 115200

        self._build_ui()
        self._wire_signals()
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
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)

        self._workspace = Workspace()
        root.addWidget(self._workspace)

        self._build_menu()

        status_bar = QStatusBar()
        self.setStatusBar(status_bar)
        self._status_label = QLabel()
        status_bar.addPermanentWidget(self._status_label)
        self._render_status_label(False)

    def _build_menu(self) -> None:
        menu_bar = self.menuBar()

        # -- File ---------------------------------------------------------
        file_menu = menu_bar.addMenu("&File")

        save_action = file_menu.addAction("Save Configuration...")
        save_action.triggered.connect(self._on_save_config)

        load_action = file_menu.addAction("Load Configuration...")
        load_action.triggered.connect(self._on_load_config)

        reset_action = file_menu.addAction("Reset Configuration")
        reset_action.triggered.connect(self._on_reset_config)

        file_menu.addSeparator()
        clear_action = file_menu.addAction("Clear Active Panel")
        clear_action.triggered.connect(self._on_clear_active_panel)

        # -- Serial ----------------------------------------------------------
        serial_menu = menu_bar.addMenu("&Serial")

        self._connect_action = serial_menu.addAction("Connect")
        self._connect_action.triggered.connect(self._on_connect)

        self._disconnect_action = serial_menu.addAction("Disconnect")
        self._disconnect_action.triggered.connect(self._serial.disconnect)

        serial_menu.addSeparator()
        config_action = serial_menu.addAction("Configuration...")
        config_action.triggered.connect(self._on_serial_config)

        # -- Panel ------------------------------------------------------------
        panel_menu = menu_bar.addMenu("&Panel")

        add_action = panel_menu.addAction("Add Panel")
        add_action.triggered.connect(lambda: self._workspace.add_panel())

        panel_menu.addSeparator()
        split_h = panel_menu.addAction("Split Panel \u2192 Right")
        split_h.triggered.connect(
            lambda: self._split_active(Qt.Horizontal)
        )
        split_v = panel_menu.addAction("Split Panel \u2193 Below")
        split_v.triggered.connect(
            lambda: self._split_active(Qt.Vertical)
        )

        panel_menu.addSeparator()
        close_action = panel_menu.addAction("Close Panel")
        close_action.triggered.connect(self._close_active_panel)

    def _wire_signals(self) -> None:
        self._serial.connected.connect(self._on_connected)
        self._serial.disconnected.connect(self._on_disconnected)
        self._serial.errorOccurred.connect(self._on_serial_error)
        self._serial.packetReceived.connect(self._on_packet)

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
        for panel in self._workspace.panels():
            panel.on_packet(packet)

    def _refresh_all_plots(self) -> None:
        for panel in self._workspace.panels():
            panel.refresh_plot()

    # -- panel menu operations ------------------------------------------------
    def _split_active(self, orientation: Qt.Orientation) -> None:
        active = self._workspace.active_panel()
        if active is not None:
            self._workspace.split_panel(active, orientation)

    def _close_active_panel(self) -> None:
        active = self._workspace.active_panel()
        if active is not None:
            self._workspace.close_panel(active)

    def _on_clear_active_panel(self) -> None:
        active = self._workspace.active_panel()
        if active is not None:
            active.clear()
            self.statusBar().showMessage("Active panel cleared.", 3000)

    # -- configuration persistence -----------------------------------------------
    def _current_app_config(self) -> AppConfig:
        panels = [
            PanelConfig(signals=panel.get_configs())
            for panel in self._workspace.panels()
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
        self._workspace.rebuild([panel.signals for panel in config.panels])

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
            "Discard all signal configuration and serial settings?",
        )
        if reply == QMessageBox.Yes:
            self._apply_app_config(ConfigManager.default())

    # -- global "active panel" tracking -------------------------------------------
    def eventFilter(self, obj, event) -> bool:
        if event.type() in (QEvent.MouseButtonPress, QEvent.FocusIn):
            node = obj if isinstance(obj, QWidget) else None
            while isinstance(node, QWidget):
                if isinstance(node, GraphPanel):
                    self._workspace.set_active_panel(node)
                    break
                node = node.parentWidget()
        return super().eventFilter(obj, event)

    def closeEvent(self, event) -> None:
        self._serial.disconnect()
        super().closeEvent(event)
