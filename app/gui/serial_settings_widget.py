"""Inline serial-settings pane for the right side of the Main Window.

Holds the same port/baud controls as the standalone `SerialConfigDialog`
but as a persistent, non-modal widget docked into the main window (left =
window management, right = this serial pane). Changing the port/baud here
takes effect at the next Connect, exactly like the dialog.

This widget is UI-only: it never touches pyserial or the connection
directly. It emits `connectRequested` / `disconnectRequested` and lets the
`MainWindow` reflect connection state back via `set_connected`.
"""
from __future__ import annotations

from typing import Optional, Tuple

import serial.tools.list_ports
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QComboBox, QPushButton, QMessageBox,
)

from gui.serial_config_dialog import COMMON_BAUD_RATES

_DEFAULT_BAUD = 115200


class SerialSettingsWidget(QWidget):
    connectRequested = Signal(str, int)   # (port, baud)
    disconnectRequested = Signal()

    def __init__(self, port: str = "", baud: int = _DEFAULT_BAUD, parent=None):
        super().__init__(parent)
        self._port = port
        self._baud = baud

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        title = QLabel("Serial Settings")
        f = title.font()
        f.setBold(True)
        f.setPointSize(f.pointSize() + 1)
        title.setFont(f)
        layout.addWidget(title)

        form = QFormLayout()

        port_row = QHBoxLayout()
        self.port_combo = QComboBox()
        self.port_combo.setEditable(True)
        port_row.addWidget(self.port_combo, 1)

        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self.refresh_ports)
        port_row.addWidget(refresh_btn)
        form.addRow("Port:", port_row)

        self.baud_combo = QComboBox()
        self.baud_combo.setEditable(True)
        self.baud_combo.addItems([str(b) for b in COMMON_BAUD_RATES])
        form.addRow("Baud rate:", self.baud_combo)

        layout.addLayout(form)
        layout.addWidget(QLabel(
            "Settings apply the next time the device is connected."
        ))

        btn_row = QHBoxLayout()
        self.connect_btn = QPushButton("Connect")
        self.connect_btn.clicked.connect(self._emit_connect)
        self.disconnect_btn = QPushButton("Disconnect")
        self.disconnect_btn.clicked.connect(self.disconnectRequested)
        btn_row.addWidget(self.connect_btn)
        btn_row.addWidget(self.disconnect_btn)
        btn_row.addStretch(1)
        layout.addLayout(btn_row)

        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        layout.addStretch(1)

        self.set_connected(False, port=self._port, baud=self._baud)
        self.refresh_ports()
        if port:
            self.port_combo.setCurrentText(port)
        self.baud_combo.setCurrentText(str(self._baud))

    # -- configuration -------------------------------------------------------
    def refresh_ports(self) -> None:
        current = self.port_combo.currentText()
        self.port_combo.clear()
        ports = [p.device for p in serial.tools.list_ports.comports()]
        self.port_combo.addItems(ports)
        if current:
            self.port_combo.setCurrentText(current)

    def settings(self) -> Tuple[str, int]:
        return self._port, self._baud

    def current_settings(self) -> Optional[Tuple[str, int]]:
        """Live (port, baud) from the combos right now, or None if the
        port is empty / the baud rate is invalid (a warning is shown)."""
        port = self.port_combo.currentText().strip()
        if not port:
            return None
        try:
            baud = int(self.baud_combo.currentText().strip())
        except ValueError:
            QMessageBox.warning(
                self, "Invalid Baud Rate",
                f"'{self.baud_combo.currentText()}' is not a valid baud rate.",
            )
            return None
        return port, baud

    def set_settings(self, port: str, baud: int) -> None:
        self._port = port
        self._baud = int(baud)
        if port:
            self.port_combo.setCurrentText(port)
        self.baud_combo.setCurrentText(str(self._baud))

    # -- connection lifecycle ------------------------------------------------
    def _emit_connect(self) -> None:
        live = self.current_settings()
        if live is None:
            return
        self._port, self._baud = live
        self.connectRequested.emit(*live)

    def set_connected(self, connected: bool,
                      port: str = "", baud: int = 0) -> None:
        self.connect_btn.setEnabled(not connected)
        self.disconnect_btn.setEnabled(connected)
        self.port_combo.setEnabled(not connected)
        self.baud_combo.setEnabled(not connected)
        if connected and port:
            self.status_label.setText(
                f"\u25cf Connected \u00b7 {port} @ {baud}"
            )
            self.status_label.setStyleSheet(
                "color: #1b8a3d; font-weight: 600;"
            )
        else:
            self.status_label.setText("\u25cf Disconnected")
            self.status_label.setStyleSheet(
                "color: #b00020; font-family: monospace; font-weight: 600;"
            )

    def set_message(self, text: str, ok: bool = True) -> None:
        """Transient status/error line (e.g. connection-lost reason)."""
        self.status_label.setText(text)
        self.status_label.setStyleSheet(
            "color: #1b8a3d; font-weight: 600;" if ok
            else "color: #b00020; font-style: italic;"
        )