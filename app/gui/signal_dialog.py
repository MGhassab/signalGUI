"""Add/Edit dialog for a single signal configuration.

The form adapts to the selected signal type via a QStackedWidget: common
fields (name, source, gain, offset, y-range, dY, dT) are always shown;
type-specific fields (operation/x-degree, or ESS/Delay criteria) appear
on a second, type-dependent panel below.
"""
from __future__ import annotations

from typing import List, Optional

from PySide6.QtWidgets import (
    QDialog, QFormLayout, QVBoxLayout, QLineEdit, QComboBox,
    QDoubleSpinBox, QSpinBox, QCheckBox, QDialogButtonBox, QStackedWidget,
    QWidget, QGroupBox
)

from models.packet import PACKET_FIELDS
from models.signal_config import (
    SignalConfig, SignalType, Operation,
    RawSignalConfig, ComputationalSignalConfig, CriteriaSignalConfig,
)


def _double_spin(minimum=-1e9, maximum=1e9, decimals=6, value=0.0) -> QDoubleSpinBox:
    sb = QDoubleSpinBox()
    sb.setRange(minimum, maximum)
    sb.setDecimals(decimals)
    sb.setValue(value)
    return sb


class SignalDialog(QDialog):
    def __init__(self, existing: Optional[SignalConfig] = None,
                 existing_names: Optional[List[str]] = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Signal Configuration")
        self.setMinimumWidth(420)
        self._existing_names = set(existing_names or [])
        if existing is not None:
            self._existing_names.discard(existing.name)

        outer = QVBoxLayout(self)

        # --- common fields ---
        common_group = QGroupBox("Signal")
        common_form = QFormLayout(common_group)

        self.name_edit = QLineEdit()
        common_form.addRow("Name:", self.name_edit)

        self.type_combo = QComboBox()
        self.type_combo.addItem("Raw Data", SignalType.RAW)
        self.type_combo.addItem("Computational Data", SignalType.COMPUTATIONAL)
        self.type_combo.addItem("Criteria-Based Data", SignalType.CRITERIA)
        common_form.addRow("Type:", self.type_combo)

        self.source_combo = QComboBox()
        self.source_combo.addItems(PACKET_FIELDS)
        common_form.addRow("Source field:", self.source_combo)

        self.enabled_check = QCheckBox("Enabled")
        self.enabled_check.setChecked(True)
        common_form.addRow("", self.enabled_check)

        self.gain_spin = _double_spin(value=1.0)
        common_form.addRow("Gain:", self.gain_spin)
        self.offset_spin = _double_spin(value=0.0)
        common_form.addRow("Offset:", self.offset_spin)
        self.y_min_spin = _double_spin(value=-1.0)
        common_form.addRow("Y-min:", self.y_min_spin)
        self.y_max_spin = _double_spin(value=1.0)
        common_form.addRow("Y-max:", self.y_max_spin)
        self.dy_spin = _double_spin(minimum=1e-9, value=0.1)
        common_form.addRow("dY:", self.dy_spin)
        self.dt_spin = _double_spin(minimum=1e-9, value=0.01)
        common_form.addRow("dT:", self.dt_spin)

        outer.addWidget(common_group)

        # --- type-specific stacked pages ---
        self.stack = QStackedWidget()

        self._raw_page = QWidget()
        self.stack.addWidget(self._raw_page)  # no extra fields

        self._comp_page = QWidget()
        comp_form = QFormLayout(self._comp_page)
        self.operation_combo = QComboBox()
        self.operation_combo.addItem("Integral", Operation.INTEGRAL)
        self.operation_combo.addItem("Derivative", Operation.DERIVATIVE)
        comp_form.addRow("Operation:", self.operation_combo)
        self.x_degree_spin = QSpinBox()
        self.x_degree_spin.setRange(1, 10)
        self.x_degree_spin.setValue(1)
        comp_form.addRow("X degree:", self.x_degree_spin)
        self.stack.addWidget(self._comp_page)

        self._criteria_page = QWidget()
        crit_form = QFormLayout(self._criteria_page)
        self.ess_spin = _double_spin(minimum=0.0, maximum=100.0, decimals=3, value=2.0)
        crit_form.addRow("ESS Criteria (%):", self.ess_spin)
        self.delay_spin = _double_spin(minimum=0.0, maximum=100.0, decimals=3, value=5.0)
        crit_form.addRow("Delay Criteria (%):", self.delay_spin)
        self.stack.addWidget(self._criteria_page)

        outer.addWidget(self.stack)

        self.type_combo.currentIndexChanged.connect(self._on_type_changed)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

        self._result_config: Optional[SignalConfig] = None

        if existing is not None:
            self._populate_from(existing)
        else:
            self._on_type_changed(self.type_combo.currentIndex())

    def _on_type_changed(self, index: int) -> None:
        stype = self.type_combo.currentData()
        page = {
            SignalType.RAW: self._raw_page,
            SignalType.COMPUTATIONAL: self._comp_page,
            SignalType.CRITERIA: self._criteria_page,
        }[stype]
        self.stack.setCurrentWidget(page)

    def _populate_from(self, cfg: SignalConfig) -> None:
        self.name_edit.setText(cfg.name)
        idx = self.type_combo.findData(SignalType(cfg.signal_type))
        self.type_combo.setCurrentIndex(idx)
        src_idx = self.source_combo.findText(cfg.source_field)
        if src_idx >= 0:
            self.source_combo.setCurrentIndex(src_idx)
        self.enabled_check.setChecked(cfg.enabled)
        self.gain_spin.setValue(cfg.gain)
        self.offset_spin.setValue(cfg.offset)
        self.y_min_spin.setValue(cfg.y_min)
        self.y_max_spin.setValue(cfg.y_max)
        self.dy_spin.setValue(cfg.dy)
        self.dt_spin.setValue(cfg.dt)

        if isinstance(cfg, ComputationalSignalConfig):
            op_idx = self.operation_combo.findData(Operation(cfg.operation))
            self.operation_combo.setCurrentIndex(op_idx)
            self.x_degree_spin.setValue(cfg.x_degree)
        elif isinstance(cfg, CriteriaSignalConfig):
            self.ess_spin.setValue(cfg.ess_criteria_pct)
            self.delay_spin.setValue(cfg.delay_criteria_pct)

        self._on_type_changed(idx)

    def _on_accept(self) -> None:
        name = self.name_edit.text().strip()
        if not name:
            self.name_edit.setFocus()
            return
        if name in self._existing_names:
            self.name_edit.setFocus()
            self.name_edit.selectAll()
            return

        common = dict(
            name=name,
            source_field=self.source_combo.currentText(),
            enabled=self.enabled_check.isChecked(),
            gain=self.gain_spin.value(),
            offset=self.offset_spin.value(),
            y_min=self.y_min_spin.value(),
            y_max=self.y_max_spin.value(),
            dy=self.dy_spin.value(),
            dt=self.dt_spin.value(),
        )
        stype = self.type_combo.currentData()
        if stype == SignalType.RAW:
            self._result_config = RawSignalConfig(**common)
        elif stype == SignalType.COMPUTATIONAL:
            self._result_config = ComputationalSignalConfig(
                **common,
                operation=self.operation_combo.currentData(),
                x_degree=self.x_degree_spin.value(),
            )
        else:
            self._result_config = CriteriaSignalConfig(
                **common,
                ess_criteria_pct=self.ess_spin.value(),
                delay_criteria_pct=self.delay_spin.value(),
            )
        self.accept()

    def result_config(self) -> Optional[SignalConfig]:
        return self._result_config
