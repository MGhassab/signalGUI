"""Right-side Data1..Data8 live-value table with user-renameable labels.

Renaming only changes the DISPLAY name shown here (and anywhere else the
GUI shows a friendly name) - the underlying packet field keys
(Data1..Data8) never change, per spec.
"""
from __future__ import annotations

from typing import Dict

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QTableWidget, QTableWidgetItem, QHeaderView

from models.packet import DATA_FIELDS


class DataTable(QTableWidget):
    nameChanged = Signal(str, str)  # field_key, new_display_name

    def __init__(self, parent=None):
        super().__init__(len(DATA_FIELDS), 3, parent)
        self.setHorizontalHeaderLabels(["Field", "Value", "Display Name"])
        self.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.verticalHeader().setVisible(False)

        for row, field_key in enumerate(DATA_FIELDS):
            field_item = QTableWidgetItem(field_key)
            field_item.setFlags(field_item.flags() & ~Qt.ItemIsEditable)
            self.setItem(row, 0, field_item)

            value_item = QTableWidgetItem("0")
            value_item.setFlags(value_item.flags() & ~Qt.ItemIsEditable)
            self.setItem(row, 1, value_item)

            name_item = QTableWidgetItem(field_key)
            self.setItem(row, 2, name_item)

        self.itemChanged.connect(self._on_item_changed)

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if item.column() != 2:
            return
        field_key = self.item(item.row(), 0).text()
        self.nameChanged.emit(field_key, item.text())

    def set_display_names(self, names: Dict[str, str]) -> None:
        self.itemChanged.disconnect(self._on_item_changed)
        try:
            for row, field_key in enumerate(DATA_FIELDS):
                if field_key in names:
                    self.item(row, 2).setText(names[field_key])
        finally:
            self.itemChanged.connect(self._on_item_changed)

    def update_values(self, values: Dict[str, int]) -> None:
        for row, field_key in enumerate(DATA_FIELDS):
            if field_key in values:
                self.item(row, 1).setText(str(values[field_key]))
