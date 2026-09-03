"""Main application window: wires the serial layer, packet parser, signal
processing, and all GUI panels together.

The GUI never touches serial bytes or packet parsing directly - it only
receives fully-formed `Packet` objects via `SerialManager.packetReceived`
and hands them to `SignalManager`. This keeps low-level serial/parsing
logic completely out of the GUI layer, per the architecture requirement.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, QTimer, Slot
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QSplitter, QMessageBox,
    QFileDialog, QStatusBar
)

from gui.serial_panel import SerialPanel
from gui.data_table import DataTable
from gui.signal_panel import SignalPanel
from gui.plot_widget import PlotWidget

from models.packet import Packet
from models.app_config import AppConfig
from serial_io.packet_parser import PacketParser, PacketFormat
from serial_io.serial_manager import SerialManager
from processing.signal_manager import SignalManager
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
        self._signal_manager = SignalManager()

        self._build_ui()
        self._wire_signals()

        self._plot_timer = QTimer(self)
        self._plot_timer.setInterval(PLOT_REFRESH_MS)
        self._plot_timer.timeout.connect(self._refresh_plot)
        self._plot_timer.start()

        self._current_config_path: Optional[str] = None

    # -- UI construction ----------------------------------------------------
    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        self.serial_panel = SerialPanel()
        root.addWidget(self.serial_panel)

        self.plot_widget = PlotWidget()
        root.addWidget(self.plot_widget, stretch=1)

        bottom_splitter = QSplitter(Qt.Horizontal)
        self.signal_panel = SignalPanel()
        self.data_table = DataTable()
        bottom_splitter.addWidget(self.signal_panel)
        bottom_splitter.addWidget(self.data_table)
        bottom_splitter.setStretchFactor(0, 2)
        bottom_splitter.setStretchFactor(1, 1)
        root.addWidget(bottom_splitter, stretch=1)

        self._build_menu()
        self.setStatusBar(QStatusBar())

    def _build_menu(self) -> None:
        menu_bar = self.menuBar()
        file_menu = menu_bar.addMenu("&File")

        save_action = file_menu.addAction("Save Configuration...")
        save_action.triggered.connect(self._on_save_config)

        load_action = file_menu.addAction("Load Configuration...")
        load_action.triggered.connect(self._on_load_config)

        reset_action = file_menu.addAction("Reset Configuration")
        reset_action.triggered.connect(self._on_reset_config)

        file_menu.addSeparator()
        clear_action = file_menu.addAction("Clear Graph")
        clear_action.triggered.connect(self._on_clear_graph)

    def _wire_signals(self) -> None:
        self.serial_panel.connectClicked.connect(self._on_connect)
        self.serial_panel.disconnectClicked.connect(self._serial.disconnect)

        self._serial.connected.connect(lambda: self.serial_panel.set_connected(True))
        self._serial.disconnected.connect(self._on_disconnected)
        self._serial.errorOccurred.connect(self._on_serial_error)
        self._serial.packetReceived.connect(self._on_packet)

        self.data_table.nameChanged.connect(self._on_data_name_changed)
        self.signal_panel.signalsChanged.connect(self._on_signals_changed)
        self.signal_panel.signalEnabledChanged.connect(self._on_signal_enabled_changed)

    # -- serial connection lifecycle -----------------------------------------
    @Slot(str, int)
    def _on_connect(self, port: str, baud: int) -> None:
        self._serial.connect_to(port, baud)

    @Slot(str)
    def _on_disconnected(self, reason: str) -> None:
        if reason:
            self.serial_panel.set_connection_lost(reason)
            self.statusBar().showMessage(f"Disconnected: {reason}", 5000)
        else:
            self.serial_panel.set_connected(False)

    @Slot(str)
    def _on_serial_error(self, message: str) -> None:
        self.serial_panel.set_connected(False)
        QMessageBox.warning(self, "Serial Error", message)

    @Slot(object)
    def _on_packet(self, packet: Packet) -> None:
        self._signal_manager.on_packet(packet)
        self.data_table.update_values(self._signal_manager.get_latest_data_values())

    # -- signal configuration --------------------------------------------------
    def _on_signals_changed(self) -> None:
        configs = self.signal_panel.get_configs()
        self._signal_manager.set_signals(configs)
        self._resync_plot_axes()

    def _on_signal_enabled_changed(self, name: str, enabled: bool) -> None:
        self._on_signals_changed()

    def _resync_plot_axes(self) -> None:
        enabled_names = set()
        for cfg in self.signal_panel.get_configs():
            if cfg.enabled:
                enabled_names.add(cfg.name)
                self.plot_widget.add_or_update_signal(cfg.name, cfg.y_min, cfg.y_max)
        for existing_name in self.plot_widget.signal_names():
            if existing_name not in enabled_names:
                self.plot_widget.remove_signal(existing_name)

    def _on_data_name_changed(self, field_key: str, new_name: str) -> None:
        # Display-name-only remap; underlying Data1..Data8 packet keys are
        # never touched. Extend here if display names should propagate
        # elsewhere in the GUI (e.g. into signal source pickers).
        pass

    # -- plotting -------------------------------------------------------------
    def _refresh_plot(self) -> None:
        for cfg in self.signal_panel.get_configs():
            if not cfg.enabled:
                continue
            t, y = self._signal_manager.get_plot_data(cfg.name)
            if t is not None:
                self.plot_widget.update_signal_data(cfg.name, t, y)

    def _on_clear_graph(self) -> None:
        self._signal_manager.clear_all()
        self.plot_widget.clear()

    # -- configuration persistence -----------------------------------------------
    def _current_app_config(self) -> AppConfig:
        return AppConfig(
            serial_port=self.serial_panel.port_combo.currentText(),
            baud_rate=int(self.serial_panel.baud_combo.currentText() or 115200),
            signals=self.signal_panel.get_configs(),
            data_field_names={
                self.data_table.item(row, 0).text(): self.data_table.item(row, 2).text()
                for row in range(self.data_table.rowCount())
            },
        )

    def _apply_app_config(self, config: AppConfig) -> None:
        idx = self.serial_panel.port_combo.findText(config.serial_port)
        if idx >= 0:
            self.serial_panel.port_combo.setCurrentIndex(idx)
        elif config.serial_port:
            self.serial_panel.port_combo.setCurrentText(config.serial_port)
        self.serial_panel.baud_combo.setCurrentText(str(config.baud_rate))
        self.signal_panel.set_configs(config.signals)
        self.data_table.set_display_names(config.data_field_names)
        self._on_signals_changed()

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
            "Discard all signals and reset serial settings?",
        )
        if reply == QMessageBox.Yes:
            self._apply_app_config(ConfigManager.default())

    def closeEvent(self, event) -> None:
        self._serial.disconnect()
        super().closeEvent(event)
