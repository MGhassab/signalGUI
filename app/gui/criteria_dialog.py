"""Editor for one Criteria signal configuration.

A criteria signal compares a SOURCE (a configured signal or a raw packet
channel) against a REFERENCE (always one of the Position-4 channels) and
reports one control-performance metric. The parameter area is dynamic: it
only shows the fields relevant to the currently selected criterion.
"""
from __future__ import annotations

from typing import List, Optional, Tuple

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QComboBox, QDoubleSpinBox, QCheckBox, QStackedWidget,
    QWidget, QGroupBox, QMessageBox,
)

from models.packet import PACKET_FIELDS, POSITION4_FIELDS
from models.signal_config import (
    SignalConfig, SignalType, SourceKind, Criterion, CriteriaSignalConfig,
)

_CRITERION_LABELS = {
    Criterion.STEADY_STATE_ERROR: "Steady-State Error",
    Criterion.SETTLING_TIME: "Settling Time",
    Criterion.RISE_TIME: "Rise Time",
    Criterion.FALL_TIME: "Fall Time",
    Criterion.OVERSHOOT: "Overshoot",
    Criterion.INVERSE_RESPONSE: "Inverse Response",
}

CRITERION_LABELS = _CRITERION_LABELS


def _spin(minimum=-1e9, maximum=1e9, decimals=6, value=0.0) -> QDoubleSpinBox:
    sb = QDoubleSpinBox()
    sb.setRange(minimum, maximum)
    sb.setDecimals(decimals)
    sb.setValue(value)
    return sb


class CriteriaSignalDialog(QDialog):
    def __init__(self, signals: List[SignalConfig],
                 existing: Optional[CriteriaSignalConfig] = None,
                 existing_names: Optional[List[str]] = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Criteria Configuration")
        self.setMinimumWidth(460)
        self._existing = existing
        self._taken_names = set(existing_names or [])
        if existing is not None:
            self._taken_names.discard(existing.name)
        self._result: Optional[CriteriaSignalConfig] = None

        # Candidate SOURCE signals (never other criteria rows).
        self._source_signals = [s for s in signals
                                if SignalType(s.signal_type) != SignalType.CRITERIA]

        outer = QVBoxLayout(self)

        # -- source ---------------------------------------------------------
        src_group = QGroupBox("Inputs")
        src_form = QFormLayout(src_group)

        self.source_combo = QComboBox()
        self._populate_source_combo()
        src_form.addRow("Source Signal:", self.source_combo)

        self.reference_combo = QComboBox()
        self.reference_combo.addItems(POSITION4_FIELDS)
        src_form.addRow("Reference Signal (Position 4):", self.reference_combo)

        outer.addWidget(src_group)

        # -- criterion + dynamic parameters -----------------------------------
        crit_group = QGroupBox("Criterion")
        crit_form = QFormLayout(crit_group)
        self.criterion_combo = QComboBox()
        for crit, label in _CRITERION_LABELS.items():
            self.criterion_combo.addItem(label, crit)
        crit_form.addRow("Criterion:", self.criterion_combo)

        self.param_stack = QStackedWidget()
        self._pages = {
            Criterion.STEADY_STATE_ERROR: self._make_ss_page(),
            Criterion.SETTLING_TIME: self._make_settling_page(),
            Criterion.RISE_TIME: self._make_rise_page(),
            Criterion.FALL_TIME: self._make_fall_page(),
            Criterion.OVERSHOOT: self._make_empty_page("No parameters required."),
            Criterion.INVERSE_RESPONSE: self._make_inverse_page(),
        }
        for crit in _CRITERION_LABELS:
            self.param_stack.addWidget(self._pages[crit])
        crit_form.addRow("Parameters:", self.param_stack)
        outer.addWidget(crit_group)

        # -- plot range -------------------------------------------------------
        range_group = QGroupBox("Derived signal plot range")
        range_form = QFormLayout(range_group)
        self.y_min_spin = _spin(value=0.0)
        self.y_max_spin = _spin(value=100.0)
        range_form.addRow("Y-min:", self.y_min_spin)
        range_form.addRow("Y-max:", self.y_max_spin)
        outer.addWidget(range_group)

        self.criterion_combo.currentIndexChanged.connect(self._on_criterion_changed)

        buttons = QDialogButtonBox()
        apply_btn = buttons.addButton("Apply", QDialogButtonBox.AcceptRole)
        apply_btn.setDefault(True)
        buttons.addButton("Cancel", QDialogButtonBox.RejectRole)
        buttons.accepted.connect(self._on_apply)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

        if existing is not None:
            self._populate_from(existing)
        else:
            self._on_criterion_changed(self.criterion_combo.currentIndex())

    # -- parameter page builders ---------------------------------------------
    def _make_ss_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        self.ss_percent_check = QCheckBox(
            "Report percentage error relative to the reference"
        )
        layout.addWidget(self.ss_percent_check)
        layout.addStretch(1)
        return page

    def _make_settling_page(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        self.settling_tol_spin = _spin(minimum=0.0001, maximum=100.0,
                                       decimals=4, value=2.0)
        form.addRow("Tolerance:", self.settling_tol_spin)
        return page

    def _make_rise_page(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        self.rise_low_spin = _spin(minimum=0.0, maximum=100.0, decimals=2, value=10.0)
        self.rise_high_spin = _spin(minimum=0.0, maximum=100.0, decimals=2, value=90.0)
        form.addRow("Lower level (%):", self.rise_low_spin)
        form.addRow("Upper level (%):", self.rise_high_spin)
        return page

    def _make_fall_page(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        self.fall_high_spin = _spin(minimum=0.0, maximum=100.0, decimals=2, value=90.0)
        self.fall_low_spin = _spin(minimum=0.0, maximum=100.0, decimals=2, value=10.0)
        form.addRow("Upper level (%):", self.fall_high_spin)
        form.addRow("Lower level (%):", self.fall_low_spin)
        return page

    def _make_inverse_page(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        self.inv_window_spin = _spin(minimum=0.001, maximum=3600.0, decimals=3, value=0.5)
        self.inv_amp_spin = _spin(minimum=0.0, maximum=1e9, decimals=4, value=1.0)
        self.inv_duration_spin = _spin(minimum=0.0, maximum=60.0, decimals=4, value=0.05)
        form.addRow("Detection window (s):", self.inv_window_spin)
        form.addRow("Minimum amplitude:", self.inv_amp_spin)
        form.addRow("Minimum duration (s):", self.inv_duration_spin)
        return page

    @staticmethod
    def _make_empty_page(text: str) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        label = QLabel(text)
        label.setStyleSheet("color: #888;")
        layout.addWidget(label)
        layout.addStretch(1)
        return page

    # -- combo population / selection helpers ---------------------------------
    def _populate_source_combo(self) -> None:
        signals = self._source_signals
        channels = PACKET_FIELDS

        if not signals:
            header = self.source_combo
            header.addItem("\u2014 No signals configured \u2014")
            header.setItemData(0, None, Qt.UserRole)
            header.model().item(0).setEnabled(False)

        first_signal: Optional[str] = None
        for s in signals:
            if first_signal is None:
                first_signal = s.name
            self.source_combo.addItem(f"Signal: {s.name}", (SourceKind.SIGNAL, s.name))

        if signals:
            sep = self.source_combo
            sep.addItem("Raw channels:")
            sep.model().item(sep.count() - 1).setEnabled(False)

        for field in channels:
            self.source_combo.addItem(f"Channel: {field}", (SourceKind.FIELD, field))

    def _source_value(self) -> Tuple[SourceKind, str]:
        data = self.source_combo.currentData()
        if data is None:
            return SourceKind.FIELD, ""
        return data

    def _select_source(self, kind: SourceKind, value: str) -> None:
        for i in range(self.source_combo.count()):
            data = self.source_combo.itemData(i)
            if data == (kind, value):
                self.source_combo.setCurrentIndex(i)
                return

    # -- criterion switching ---------------------------------------------------
    def _on_criterion_changed(self, index: int) -> None:
        crit = self.criterion_combo.itemData(index)
        self.param_stack.setCurrentWidget(self._pages[crit])

    def _current_criterion(self) -> Criterion:
        return self.criterion_combo.currentData()

    # -- populate / build -------------------------------------------------------
    def _populate_from(self, cfg: CriteriaSignalConfig) -> None:
        self._select_source(SourceKind(cfg.source_kind), cfg.source_label)
        ref_idx = self.reference_combo.findText(cfg.reference_field)
        if ref_idx >= 0:
            self.reference_combo.setCurrentIndex(ref_idx)
        crit_idx = self.criterion_combo.findData(Criterion(cfg.criterion))
        if crit_idx >= 0:
            self.criterion_combo.setCurrentIndex(crit_idx)

        self.ss_percent_check.setChecked(bool(cfg.ss_error_percent))
        self.settling_tol_spin.setValue(cfg.settling_tolerance_pct)
        self.rise_low_spin.setValue(cfg.rise_low_pct)
        self.rise_high_spin.setValue(cfg.rise_high_pct)
        self.fall_high_spin.setValue(cfg.fall_high_pct)
        self.fall_low_spin.setValue(cfg.fall_low_pct)
        self.inv_window_spin.setValue(cfg.inverse_window_s)
        self.inv_amp_spin.setValue(cfg.inverse_min_amplitude)
        self.inv_duration_spin.setValue(cfg.inverse_min_duration_s)
        self.y_min_spin.setValue(cfg.y_min)
        self.y_max_spin.setValue(cfg.y_max)
        self._on_criterion_changed(crit_idx)

    def _build_config(self, name: str) -> CriteriaSignalConfig:
        kind, value = self._source_value()
        common = dict(
            name=name,
            source_field=value if kind == SourceKind.FIELD else "",
            enabled=True,
            gain=1.0,
            offset=0.0,
            y_min=self.y_min_spin.value(),
            y_max=self.y_max_spin.value(),
            dy=0.1,
            dt=0.01,
        )
        return CriteriaSignalConfig(
            **common,
            source_kind=kind,
            source_signal=value if kind == SourceKind.SIGNAL else "",
            reference_field=self.reference_combo.currentText(),
            criterion=self._current_criterion(),
            ss_error_percent=self.ss_percent_check.isChecked(),
            settling_tolerance_pct=self.settling_tol_spin.value(),
            rise_low_pct=self.rise_low_spin.value(),
            rise_high_pct=self.rise_high_spin.value(),
            fall_low_pct=self.fall_low_spin.value(),
            fall_high_pct=self.fall_high_spin.value(),
            inverse_window_s=self.inv_window_spin.value(),
            inverse_min_amplitude=self.inv_amp_spin.value(),
            inverse_min_duration_s=self.inv_duration_spin.value(),
        )

    def _suggest_name(self) -> str:
        crit = _CRITERION_LABELS.get(self._current_criterion(), "").replace(" ", "")
        kind, value = self._source_value()
        return f"{crit}_{value}"

    # -- validation + accept ----------------------------------------------------
    def _on_apply(self) -> None:
        crit = self._current_criterion()
        kind, value = self._source_value()
        reference = self.reference_combo.currentText()

        errors: List[str] = []
        if value in ("", None):
            errors.append("Source signal cannot be empty.")
        if not reference:
            errors.append("Reference signal cannot be empty.")
        if reference not in POSITION4_FIELDS:
            errors.append("Reference signal must be a Position-4 channel.")
        if crit is None:
            errors.append("Select at least one criterion.")

        if crit in (Criterion.RISE_TIME, Criterion.FALL_TIME):
            low = (self.rise_low_spin if crit == Criterion.RISE_TIME
                   else self.fall_low_spin).value()
            high = (self.rise_high_spin if crit == Criterion.RISE_TIME
                    else self.fall_high_spin).value()
            if not (0.0 <= low < high <= 100.0):
                errors.append("Lower threshold must be smaller than the upper "
                              "threshold (both within 0-100%).")
        if crit == Criterion.SETTLING_TIME and self.settling_tol_spin.value() <= 0:
            errors.append("Tolerance must be greater than zero.")

        if errors:
            QMessageBox.warning(
                self, "Invalid Criteria Configuration", "\n".join(errors)
            )
            return

        if (self._existing is not None
                and self._existing.name not in self._taken_names):
            name = self._existing.name
        else:
            name = self._suggest_name()
            if name in self._taken_names:
                base, i = name, 1
                while name in self._taken_names:
                    name = f"{base}_{i}"
                    i += 1
        self._result = self._build_config(name)
        self.accept()

    def result_config(self) -> Optional[CriteriaSignalConfig]:
        return self._result
