"""Serial port / baud-rate configuration and connect/disconnect controls.

Pure GUI - never touches pyserial directly. Emits high-level signals that
main_window wires to the SerialManager.
"""
from __future__ import annotations

import serial.tools.list_ports
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget, QHBoxLayout, QLabel, QComboBox, QPushButton

COMMON_BAUD_RATES = [9600, 19200, 38400, 57600, 115200, 230400, 460800, 921600]


class SerialPanel(QWidget):
    connectClicked = Signal(str, int)   # port, baud
    disconnectClicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)

        layout.addWidget(QLabel("Port:"))
        self.port_combo = QComboBox()
        self.port_combo.setMinimumWidth(150)
        self.port_combo.setEditable(True)
        layout.addWidget(self.port_combo)

        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.clicked.connect(self.refresh_ports)
        layout.addWidget(self.refresh_btn)

        layout.addWidget(QLabel("Baud:"))
        self.baud_combo = QComboBox()
        self.baud_combo.setEditable(True)
        self.baud_combo.addItems([str(b) for b in COMMON_BAUD_RATES])
        self.baud_combo.setCurrentText("115200")
        layout.addWidget(self.baud_combo)

        self.connect_btn = QPushButton("Connect")
        self.disconnect_btn = QPushButton("Disconnect")
        self.disconnect_btn.setEnabled(False)
        layout.addWidget(self.connect_btn)
        layout.addWidget(self.disconnect_btn)

        self.status_label = QLabel("\u25cf Disconnected")
        self.status_label.setStyleSheet("color: #b00020; font-weight: 600;")
        layout.addWidget(self.status_label)
        layout.addStretch(1)

        self.connect_btn.clicked.connect(self._on_connect_clicked)
        self.disconnect_btn.clicked.connect(self.disconnectClicked)

        self.refresh_ports()

    def refresh_ports(self) -> None:
        current = self.port_combo.currentText()
        self.port_combo.clear()
        ports = [p.device for p in serial.tools.list_ports.comports()]
        self.port_combo.addItems(ports)
        if current:
            self.port_combo.setCurrentText(current)

    def _on_connect_clicked(self) -> None:
        port = self.port_combo.currentText().strip()
        try:
            baud = int(self.baud_combo.currentText())
        except ValueError:
            baud = 115200
        if port:
            self.connectClicked.emit(port, baud)

    def set_connected(self, connected: bool) -> None:
        self.connect_btn.setEnabled(not connected)
        self.disconnect_btn.setEnabled(connected)
        self.port_combo.setEnabled(not connected)
        self.baud_combo.setEnabled(not connected)
        self.refresh_btn.setEnabled(not connected)
        if connected:
            self.status_label.setText("\u25cf Connected")
            self.status_label.setStyleSheet("color: #1b8a3d; font-weight: 600;")
        else:
            self.status_label.setText("\u25cf Disconnected")
            self.status_label.setStyleSheet("color: #b00020; font-weight: 600;")

    def set_connection_lost(self, reason: str) -> None:
        self.set_connected(False)
        self.status_label.setText(f"\u25cf Connection lost: {reason}")
        self.status_label.setStyleSheet("color: #b00020; font-weight: 600;")
