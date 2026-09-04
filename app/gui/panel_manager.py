"""Main-Window Panel Manager list.

Shows every created panel (name + status), lets the user show/hide/rename/
delete panels, and create new ones. It is deliberately UI-only: all
operations are forwarded through signals to the `MainWindow`, which owns
the authoritative panel registry. No signal/serial/plot logic lives here.
"""
from __future__ import annotations

from typing import List, Optional, Tuple

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QLabel,
)


class PanelManagerWidget(QWidget):
    newRequested = Signal()
    showRequested = Signal(object)     # PanelWindow
    hideRequested = Signal(object)     # PanelWindow
    renameRequested = Signal(object)   # PanelWindow
    deleteRequested = Signal(object)   # PanelWindow

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)

        title = QLabel("Panels")
        f = title.font()
        f.setBold(True)
        f.setPointSize(f.pointSize() + 1)
        title.setFont(f)
        layout.addWidget(title)

        self.list_widget = QListWidget()
        self.list_widget.setSelectionMode(QListWidget.SingleSelection)
        self.list_widget.itemDoubleClicked.connect(self._on_activate)
        layout.addWidget(self.list_widget, 1)

        btn_row = QHBoxLayout()
        self.new_btn = QPushButton("+ New Panel")
        self.show_btn = QPushButton("Show")
        self.hide_btn = QPushButton("Hide")
        self.rename_btn = QPushButton("Rename...")
        self.delete_btn = QPushButton("Delete")
        for btn in (self.new_btn, self.show_btn, self.hide_btn,
                    self.rename_btn, self.delete_btn):
            btn_row.addWidget(btn)
        btn_row.addStretch(1)
        layout.addLayout(btn_row)

        self.new_btn.clicked.connect(self.newRequested)
        self.show_btn.clicked.connect(lambda: self._selected(self.showRequested))
        self.hide_btn.clicked.connect(lambda: self._selected(self.hideRequested))
        self.rename_btn.clicked.connect(lambda: self._selected(self.renameRequested))
        self.delete_btn.clicked.connect(lambda: self._selected(self.deleteRequested))
        self.list_widget.itemSelectionChanged.connect(self._update_buttons)

        self._items: List[Tuple[QListWidgetItem, object]] = []
        self._selected_panel: Optional[object] = None
        self._update_buttons()

    def _update_buttons(self) -> None:
        has = self.selected_panel() is not None
        for btn in (self.show_btn, self.hide_btn, self.rename_btn, self.delete_btn):
            btn.setEnabled(has)

    def selected_panel(self) -> Optional[object]:
        item = self.list_widget.currentItem()
        if item is None:
            return None
        return item.data(Qt.UserRole)

    def _selected(self, signal) -> None:
        panel = self.selected_panel()
        if panel is not None:
            signal.emit(panel)

    def _on_activate(self, item: QListWidgetItem) -> None:
        panel = item.data(Qt.UserRole)
        if panel is not None:
            self.showRequested.emit(panel)

    def refresh(self, entries: List[Tuple[object, str]]) -> None:
        """Rebuild the list. Each entry is (panel, display label)."""
        previously = self._selected_panel if self._selected_panel is not None \
            else self.selected_panel()
        self.list_widget.clear()
        self._items = []
        for panel, label in entries:
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, panel)
            self.list_widget.addItem(item)
            self._items.append((item, panel))

        # Restore selection if the previously selected panel still exists.
        if previously is not None:
            for item, panel in self._items:
                if panel is previously:
                    self.list_widget.setCurrentItem(item)
                    break
        self._update_buttons()
