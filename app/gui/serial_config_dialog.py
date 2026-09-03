"""Modal dialog for configuring serial-port settings.

Keeps all serial *configuration* (port choice, baud rate) out of the main
graph/data window. Saving validates the baud rate, stores the chosen
settings, and closes - it does not touch an active connection (port/baud
only take effect at the next Connect).
"""
from __future__ import annotations

from typing import Optional, Tuple

import serial.tools.list_ports
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QHBoxLayout, QVBoxLayout, QFormLayout,
    QLabel, QComboBox, QPushButton, QMessageBox,
)

COMMON_BAUD_RATES = [9600, 19200, 38400, 57600, 115200, 230400, 460800, 921600]

_DEFAULT_BAUD = 115200


class SerialConfigDialog(QDialog):
    """Returns the chosen (port, baud) via `settings()` after Save."""

    def __init__(self, port: str = "", baud: int = _DEFAULT_BAUD, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Serial Configuration")
        self.setMinimumWidth(360)

        self._port = port
        self._baud = baud

        outer = QVBoxLayout(self)

        form = QFormLayout()

        port_row = QHBoxLayout()
        self.port_combo = QComboBox()
        self.port_combo.setEditable(True)
        self.port_combo.setMinimumWidth(200)
        port_row.addWidget(self.port_combo, 1)

        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self.refresh_ports)
        port_row.addWidget(refresh_btn)
        form.addRow("Port:", port_row)

        self.baud_combo = QComboBox()
        self.baud_combo.setEditable(True)
        self.baud_combo.addItems([str(b) for b in COMMON_BAUD_RATES])
        form.addRow("Baud rate:", self.baud_combo)

        outer.addLayout(form)
        outer.addWidget(QLabel(
            "Settings are applied the next time the device is connected."
        ))

        buttons = QDialogButtonBox()
        self._save_btn = buttons.addButton("Save", QDialogButtonBox.AcceptRole)
        buttons.addButton("Cancel", QDialogButtonBox.RejectRole)
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

        self.refresh_ports()
        if port:
            idx = self.port_combo.findText(port)
            if idx >= 0:
                self.port_combo.setCurrentIndex(idx)
            else:
                self.port_combo.setCurrentText(port)
        self.baud_combo.setCurrentText(str(baud))

    def refresh_ports(self) -> None:
        current = self.port_combo.currentText()
        self.port_combo.clear()
        ports = [p.device for p in serial.tools.list_ports.comports()]
        self.port_combo.addItems(ports)
        if current:
            self.port_combo.setCurrentText(current)

    def _on_save(self) -> None:
        port = self.port_combo.currentText().strip()
        baud_text = self.baud_combo.currentText().strip()
        try:
            baud = int(baud_text)
        except ValueError:
            QMessageBox.warning(
                self, "Invalid Baud Rate",
                f"'{baud_text}' is not a valid baud rate.",
            )
            return
        self._port = port
        self._baud = baud
        self.accept()

    def settings(self) -> Tuple[str, int]:
        return self._port, self._baud


def prompt_serial_config(port: str = "", baud: int = _DEFAULT_BAUD,
                         parent=None) -> Optional[Tuple[str, int]]:
    """Open the dialog; returns the saved (port, baud) or None if cancelled."""
    dialog = SerialConfigDialog(port=port, baud=baud, parent=parent)
    if dialog.exec():
        return dialog.settings()
    return None
