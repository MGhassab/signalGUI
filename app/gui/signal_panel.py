"""Signal configuration panel: table of configured signals plus
add/edit/delete/enable controls."""
from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QHeaderView, QCheckBox
)

from models.signal_config import SignalConfig, SignalType
from gui.signal_dialog import SignalDialog

COLUMNS = ["Enable", "Name", "Type", "Source", "Gain", "Offset", "Y-Min", "Y-Max", "dY", "dT"]


class SignalPanel(QWidget):
    signalsChanged = Signal()                     # any add/edit/delete
    signalEnabledChanged = Signal(str, bool)       # name, enabled

    def __init__(self, parent=None):
        super().__init__(parent)
        self._configs: List[SignalConfig] = []

        layout = QVBoxLayout(self)
        btn_row = QHBoxLayout()
        self.add_btn = QPushButton("Add")
        self.edit_btn = QPushButton("Edit")
        self.delete_btn = QPushButton("Delete")
        btn_row.addWidget(self.add_btn)
        btn_row.addWidget(self.edit_btn)
        btn_row.addWidget(self.delete_btn)
        btn_row.addStretch(1)
        layout.addLayout(btn_row)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        layout.addWidget(self.table)

        self.add_btn.clicked.connect(self._on_add)
        self.edit_btn.clicked.connect(self._on_edit)
        self.delete_btn.clicked.connect(self._on_delete)

    def set_configs(self, configs: List[SignalConfig]) -> None:
        self._configs = list(configs)
        self._refresh_table()

    def get_configs(self) -> List[SignalConfig]:
        return list(self._configs)

    @staticmethod
    def _type_label(cfg: SignalConfig) -> str:
        return {
            SignalType.RAW: "Raw",
            SignalType.COMPUTATIONAL: "Computational",
            SignalType.CRITERIA: "Criteria",
        }[SignalType(cfg.signal_type)]

    def _refresh_table(self) -> None:
        self.table.setRowCount(len(self._configs))
        for row, cfg in enumerate(self._configs):
            chk = QCheckBox()
            chk.setChecked(cfg.enabled)
            chk.stateChanged.connect(
                lambda state, name=cfg.name: self._on_enable_toggled(name, state)
            )
            self.table.setCellWidget(row, 0, chk)

            values = [
                cfg.name, self._type_label(cfg), cfg.source_field,
                f"{cfg.gain:g}", f"{cfg.offset:g}", f"{cfg.y_min:g}",
                f"{cfg.y_max:g}", f"{cfg.dy:g}", f"{cfg.dt:g}",
            ]
            for col, val in enumerate(values, start=1):
                item = QTableWidgetItem(str(val))
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self.table.setItem(row, col, item)

    def _on_enable_toggled(self, name: str, state: int) -> None:
        for cfg in self._configs:
            if cfg.name == name:
                cfg.enabled = bool(state)
                break
        self.signalEnabledChanged.emit(name, bool(state))

    def _selected_index(self) -> Optional[int]:
        rows = self.table.selectionModel().selectedRows()
        return rows[0].row() if rows else None

    def _on_add(self) -> None:
        dlg = SignalDialog(existing_names=[c.name for c in self._configs], parent=self)
        if dlg.exec():
            cfg = dlg.result_config()
            if cfg:
                self._configs.append(cfg)
                self._refresh_table()
                self.signalsChanged.emit()

    def _on_edit(self) -> None:
        idx = self._selected_index()
        if idx is None:
            return
        old_cfg = self._configs[idx]
        dlg = SignalDialog(
            existing=old_cfg,
            existing_names=[c.name for c in self._configs],
            parent=self,
        )
        if dlg.exec():
            new_cfg = dlg.result_config()
            if new_cfg:
                self._configs[idx] = new_cfg
                self._refresh_table()
                self.signalsChanged.emit()

    def _on_delete(self) -> None:
        idx = self._selected_index()
        if idx is None:
            return
        del self._configs[idx]
        self._refresh_table()
        self.signalsChanged.emit()
