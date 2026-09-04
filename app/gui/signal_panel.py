"""Signal configuration panel: table of configured signals/criteria plus
add/edit/delete/enable controls.

Raw and Computational signals are created/edited with `SignalDialog`;
Criteria rows (derived metrics) are created/edited with the dedicated
`CriteriaSignalDialog`. All rows share one table so a panel keeps a single,
ordered, per-panel configuration list.
"""
from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QHeaderView, QCheckBox
)

from models.signal_config import (
    SignalConfig, SignalType, CriteriaSignalConfig,
)
from gui.signal_dialog import SignalDialog
from gui.criteria_dialog import CriteriaSignalDialog, CRITERION_LABELS

COLUMNS = ["Enable", "Name", "Type", "Source", "Gain", "Offset",
           "Y-Min", "Y-Max", "dY", "Details"]

_TYPE_LABELS = {
    SignalType.RAW: "Raw",
    SignalType.COMPUTATIONAL: "Computational",
    SignalType.CRITERIA: "Criteria",
}

_PARAM_BLANK = "\u2014"


class SignalPanel(QWidget):
    signalsChanged = Signal()                     # any add/edit/delete
    signalEnabledChanged = Signal(str, bool)       # name, enabled

    def __init__(self, parent=None):
        super().__init__(parent)
        self._configs: List[SignalConfig] = []

        layout = QVBoxLayout(self)
        btn_row = QHBoxLayout()
        self.add_btn = QPushButton("Add Signal")
        self.add_criteria_btn = QPushButton("Add Criteria")
        self.edit_btn = QPushButton("Edit")
        self.delete_btn = QPushButton("Delete")
        btn_row.addWidget(self.add_btn)
        btn_row.addWidget(self.add_criteria_btn)
        btn_row.addWidget(self.edit_btn)
        btn_row.addWidget(self.delete_btn)
        btn_row.addStretch(1)
        layout.addLayout(btn_row)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setHorizontalScrollMode(QTableWidget.ScrollPerPixel)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        layout.addWidget(self.table)

        self.add_btn.clicked.connect(self._on_add)
        self.add_criteria_btn.clicked.connect(self._on_add_criteria)
        self.edit_btn.clicked.connect(self._on_edit)
        self.delete_btn.clicked.connect(self._on_delete)

    def set_configs(self, configs: List[SignalConfig]) -> None:
        self._configs = list(configs)
        self._refresh_table()

    def get_configs(self) -> List[SignalConfig]:
        return list(self._configs)

    # -- table rendering -----------------------------------------------------
    @staticmethod
    def _is_criteria(cfg: SignalConfig) -> bool:
        return SignalType(cfg.signal_type) == SignalType.CRITERIA

    @classmethod
    def _source_text(cls, cfg: SignalConfig) -> str:
        if cls._is_criteria(cfg):
            return CriteriaSignalConfig.source_label.fget(cfg)
        return cfg.source_field

    def _refresh_table(self) -> None:
        self.table.setRowCount(len(self._configs))
        for row, cfg in enumerate(self._configs):
            chk = QCheckBox()
            chk.setChecked(cfg.enabled)
            chk.stateChanged.connect(
                lambda state, name=cfg.name: self._on_enable_toggled(name, state)
            )
            self.table.setCellWidget(row, 0, chk)

            is_criteria = self._is_criteria(cfg)
            if is_criteria:
                cells = self._criteria_cells(cfg)
            else:
                cells = self._signal_cells(cfg)
            for col, val in enumerate(cells, start=1):
                item = QTableWidgetItem(str(val))
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                if val == _PARAM_BLANK:
                    item.setForeground(QColor("#9e9e9e"))
                self.table.setItem(row, col, item)

    def _signal_cells(self, cfg: SignalConfig) -> List[str]:
        return [
            cfg.name,
            _TYPE_LABELS[SignalType(cfg.signal_type)],
            cfg.source_field,
            f"{cfg.gain:g}", f"{cfg.offset:g}", f"{cfg.y_min:g}",
            f"{cfg.y_max:g}", f"{cfg.dy:g}",
            "",
        ]

    def _criteria_cells(self, cfg: CriteriaSignalConfig) -> List[str]:
        crit = cfg.criterion
        if crit.value == "settling_time":
            detail = f"settling tol {cfg.settling_tolerance_pct:g}%"
        elif crit.value in ("rise_time", "fall_time"):
            low = cfg.rise_low_pct if crit.value == "rise_time" else cfg.fall_low_pct
            high = cfg.rise_high_pct if crit.value == "rise_time" else cfg.fall_high_pct
            detail = f"{low:g}\u2192{high:g}%"
        elif crit.value == "overshoot":
            detail = ""
        elif crit.value == "inverse_response":
            detail = (f"win {cfg.inverse_window_s:g}s "
                      f"amp {cfg.inverse_min_amplitude:g} "
                      f"dur {cfg.inverse_min_duration_s:g}s")
        else:  # steady_state_error
            detail = "%" if cfg.ss_error_percent else "abs"
        name = cfg.name
        crit_label = CRITERION_LABELS.get(cfg.criterion, cfg.criterion.value)
        summary = f"{crit_label} {detail}".strip()
        return [
            name,
            _TYPE_LABELS[SignalType.CRITERIA],
            cfg.source_label,
            _PARAM_BLANK, _PARAM_BLANK,
            f"{cfg.y_min:g}", f"{cfg.y_max:g}", _PARAM_BLANK,
            summary,
        ]

    # -- interactions --------------------------------------------------------
    def _on_enable_toggled(self, name: str, state: int) -> None:
        for cfg in self._configs:
            if cfg.name == name:
                cfg.enabled = bool(state)
                break
        self.signalEnabledChanged.emit(name, bool(state))

    def _selected_index(self) -> Optional[int]:
        rows = self.table.selectionModel().selectedRows()
        return rows[0].row() if rows else None

    def _source_signal_candidates(self) -> List[SignalConfig]:
        return [c for c in self._configs
                if SignalType(c.signal_type) != SignalType.CRITERIA]

    def _on_add(self) -> None:
        dlg = SignalDialog(existing_names=[c.name for c in self._configs], parent=self)
        if dlg.exec():
            cfg = dlg.result_config()
            if cfg:
                self._configs.append(cfg)
                self._refresh_table()
                self.signalsChanged.emit()

    def _on_add_criteria(self) -> None:
        dlg = CriteriaSignalDialog(
            signals=self._source_signal_candidates(),
            existing_names=[c.name for c in self._configs],
            parent=self,
        )
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
        names = [c.name for c in self._configs]

        if self._is_criteria(old_cfg):
            dlg = CriteriaSignalDialog(
                signals=self._source_signal_candidates(),
                existing=old_cfg,
                existing_names=names,
                parent=self,
            )
            new_cfg = dlg.result_config() if dlg.exec() else None
        else:
            dlg = SignalDialog(existing=old_cfg, existing_names=names, parent=self)
            new_cfg = dlg.result_config() if dlg.exec() else None

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
