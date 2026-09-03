"""Narrow per-panel Name/Value readout showing the live computed output of
each signal enabled in that panel.

Unlike the old Data1-8 table this is *panel-scoped*: the rows mirror the
panel's own signal configuration, and values are the latest processed
output samples (post gain/offset/operation). Both cells are read-only -
names are owned by the signal configuration, not this widget.
"""
from __future__ import annotations

from typing import Dict, List

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import QTableWidget, QTableWidgetItem, QHeaderView

_PLACEHOLDER = "\u2014 no enabled signals \u2014"


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

        self._names: List[str] = []
        self._rebuild_rows()

    def set_names(self, names: List[str]) -> None:
        """Rebuild the row set (call whenever the panel's enabled signal
        set changes). Order follows the signal configuration order."""
        if names == self._names:
            return
        self._names = list(names)
        self._rebuild_rows()

    def update_values(self, values: Dict[str, float]) -> None:
        for row, name in enumerate(self._names):
            if name in values:
                item = self.item(row, 1)
                if item is not None:
                    item.setText(f"{values[name]:g}")

    def clear_values(self) -> None:
        for row in range(self.rowCount()):
            item = self.item(row, 1)
            if item is not None:
                item.setText("")

    def _rebuild_rows(self) -> None:
        names = self._names
        if not names:
            self.setRowCount(1)
            self.setItem(0, 0, self._readonly_item(_PLACEHOLDER, dimmed=True))
            self.setItem(0, 1, self._readonly_item("", dimmed=True))
            return

        self.setRowCount(len(names))
        for row, name in enumerate(names):
            self.setItem(row, 0, self._readonly_item(name, dimmed=False))
            self.setItem(row, 1, self._readonly_item("", dimmed=False))

    @staticmethod
    def _readonly_item(text: str, dimmed: bool) -> QTableWidgetItem:
        item = QTableWidgetItem(text)
        if dimmed:
            item.setForeground(QBrush(QColor("#9e9e9e")))
        return item
