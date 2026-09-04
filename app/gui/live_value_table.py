"""Narrow per-panel Name/Value readout.

Two kinds of rows, in fixed order:

1. DATA1..DATA8 - raw/auxiliary display-only values (integers straight
   from the packet). They are never signals and never reach the plot.
2. The panel's enabled signal outputs (live computed values).

Both cell types are read-only; names are owned by the signal
configuration / the packet field model, not by this widget.
"""
from __future__ import annotations

from typing import Dict, List

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QTableWidget, QTableWidgetItem, QHeaderView

from models.packet import DATA_FIELDS

_DATA_LABELS = [f"DATA{i}" for i in range(1, 9)]


class LiveValueTable(QTableWidget):
    def __init__(self, parent=None):
        super().__init__(0, 2, parent)
        self.setHorizontalHeaderLabels(["Name", "Value"])
        self.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.verticalHeader().setVisible(False)
        self.setVerticalScrollMode(QTableWidget.ScrollPerPixel)
        self.setEditTriggers(QTableWidget.NoEditTriggers)
        self.setSelectionMode(QTableWidget.NoSelection)
        self.setFocusPolicy(Qt.NoFocus)

        self._signal_names: List[str] = []
        self._data_values: Dict[str, int] = {f: 0 for f in DATA_FIELDS}
        self._signal_values: Dict[str, float] = {}
        self._rebuild_rows()

    # -- row structure ---------------------------------------------------------
    def set_signal_names(self, names: List[str]) -> None:
        """Rebuild the signal rows (call whenever the panel's enabled signal
        set changes). DATA rows are always present on top."""
        if names == self._signal_names:
            return
        self._signal_names = list(names)
        self._signal_values = {name: self._signal_values.get(name, 0.0)
                               for name in names}
        self._rebuild_rows()

    # -- value updates ----------------------------------------------------------
    def update_data(self, values: Dict[str, int]) -> None:
        for row in range(len(DATA_FIELDS)):
            key = DATA_FIELDS[row]
            if key in values:
                self._data_values[key] = values[key]
            item = self.item(row, 1)
            if item is not None:
                item.setText(str(self._data_values[key]))

    def update_signal_values(self, values: Dict[str, float]) -> None:
        offset = len(DATA_FIELDS)
        for row, name in enumerate(self._signal_names):
            if name in values:
                self._signal_values[name] = values[name]
            item = self.item(offset + row, 1)
            if item is not None:
                item.setText(f"{self._signal_values[name]:g}")

    def clear_signal_values(self) -> None:
        for name in self._signal_names:
            self._signal_values[name] = 0.0
        offset = len(DATA_FIELDS)
        for row in range(len(self._signal_names)):
            item = self.item(offset + row, 1)
            if item is not None:
                item.setText("0")

    def _rebuild_rows(self) -> None:
        total = len(DATA_FIELDS) + len(self._signal_names)
        self.setRowCount(max(1, total))
        for row, label in enumerate(_DATA_LABELS):
            self.setItem(row, 0, self._readonly_item(label))
            self.setItem(row, 1, self._readonly_item(str(self._data_values[DATA_FIELDS[row]])))

        offset = len(DATA_FIELDS)
        for row, name in enumerate(self._signal_names):
            self.setItem(offset + row, 0, self._readonly_item(name))
            value = f"{self._signal_values.get(name, 0.0):g}"
            self.setItem(offset + row, 1, self._readonly_item(value))

    @staticmethod
    def _readonly_item(text: str) -> QTableWidgetItem:
        item = QTableWidgetItem(text)
        return item
