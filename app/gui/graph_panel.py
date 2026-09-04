"""One independent analysis panel.

A single `GraphPanel` owns everything that makes up one analysis view so
panels never share mutable state:

- its own `SignalManager` (processors + plot history buffers),
- a `SignalPanel` (signal configuration table),
- a `PlotWidget`, a `LiveValueTable`,
- a `PlaybackController` (per-panel Play/Pause + history navigation).

The widget is a tabbed view with a slim control row on top:

    [ ▶/⏸ ] [ ◀ ] [ ▶ ] [ ⏮ Latest ]        dT (s): [____]

    [Plot] [Signal Configuration]

Play/Pause only affects THIS panel's DISPLAY. Data acquisition (packet
ingestion into the buffers) always continues, so a paused panel keeps its
full history and the user can step backward/forward through it or jump
back to live. The left Name/Value table shows DATA1-8 (raw, display-only)
followed by the panel's enabled signal outputs.
"""
from __future__ import annotations

from typing import List

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QTabWidget,
    QToolButton, QLabel, QDoubleSpinBox,
)

from models.packet import Packet
from models.signal_config import SignalConfig, SignalType
from processing.signal_manager import SignalManager
from gui.live_value_table import LiveValueTable
from gui.plot_widget import PlotWidget
from gui.playback_controller import PlaybackController
from gui.signal_panel import SignalPanel

_INITIAL_TABLE_FRACTION = 0.22
_DEFAULT_TIME_TICK = 1.0  # seconds per major X-axis tick


class GraphPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._signal_manager = SignalManager()
        self._sized = False
        self._dt = _DEFAULT_TIME_TICK
        self._playback = PlaybackController()
        self._last_paused_end: int | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # -- control row: playback + display dT ------------------------------
        controls = QHBoxLayout()
        controls.setContentsMargins(4, 2, 4, 2)

        self.play_btn = QToolButton(self)
        self.play_btn.setText("\u23f8")  # ⏸ (pressing pauses)
        self.play_btn.setToolTip("Pause / Resume live display")
        self.play_btn.clicked.connect(self._toggle_playback)

        self.back_btn = QToolButton(self)
        self.back_btn.setText("\u25c0")  # ◀
        self.back_btn.setToolTip("Step backward through history (paused)")
        self.back_btn.clicked.connect(self._step_back)

        self.forward_btn = QToolButton(self)
        self.forward_btn.setText("\u25b6")  # ▶
        self.forward_btn.setToolTip("Step forward through history (paused)")
        self.forward_btn.clicked.connect(self._step_forward)

        self.latest_btn = QToolButton(self)
        self.latest_btn.setText("\u23ee")  # ⏮
        self.latest_btn.setToolTip("Return to the latest/live sample")
        self.latest_btn.clicked.connect(self._go_latest)

        controls.addWidget(self.play_btn)
        controls.addWidget(self.back_btn)
        controls.addWidget(self.forward_btn)
        controls.addWidget(self.latest_btn)
        controls.addSpacing(12)
        controls.addWidget(QLabel("dT (s):"))
        self.dt_spin = QDoubleSpinBox(self)
        self.dt_spin.setRange(0.001, 100000.0)
        self.dt_spin.setDecimals(4)
        self.dt_spin.setValue(_DEFAULT_TIME_TICK)
        self.dt_spin.setToolTip(
            "Time-axis (X) major tick step - display only, no effect on "
            "signal values or acquisition"
        )
        self.dt_spin.valueChanged.connect(self._on_dt_changed)
        controls.addWidget(self.dt_spin)
        controls.addStretch(1)

        root.addLayout(controls)
        self._update_play_button()

        # -- tabbed body ------------------------------------------------------
        self.tabs = QTabWidget(self)
        root.addWidget(self.tabs, 1)

        plot_page = QWidget()
        plot_layout = QVBoxLayout(plot_page)
        plot_layout.setContentsMargins(0, 0, 0, 0)

        self.plot_split = QSplitter(Qt.Horizontal, plot_page)
        self.value_table = LiveValueTable(self.plot_split)
        self.plot_widget = PlotWidget(self.plot_split)
        self.plot_split.addWidget(self.value_table)
        self.plot_split.addWidget(self.plot_widget)
        self.plot_split.setStretchFactor(0, 0)
        self.plot_split.setStretchFactor(1, 1)
        self.plot_split.setCollapsible(0, True)
        self.plot_split.setCollapsible(1, False)
        plot_layout.addWidget(self.plot_split)
        self.tabs.addTab(plot_page, "Plot")

        self.signal_panel = SignalPanel()
        self.tabs.addTab(self.signal_panel, "Signal Configuration")

        # -- internal wiring: this panel's config -> this panel's data -------
        self.signal_panel.signalsChanged.connect(self._on_signals_changed)
        self.signal_panel.signalEnabledChanged.connect(self._on_signals_changed)

        self.plot_widget.set_time_tick_step(self._dt)

    # -- configuration -------------------------------------------------------
    def set_signals(self, configs: List[SignalConfig]) -> None:
        self.signal_panel.set_configs(configs)
        self._on_signals_changed()

    def get_configs(self) -> List[SignalConfig]:
        return self.signal_panel.get_configs()

    def set_time_step(self, dt: float) -> None:
        self._dt = max(0.001, float(dt))
        self.dt_spin.setValue(self._dt)
        self.plot_widget.set_time_tick_step(self._dt)

    def get_time_step(self) -> float:
        return self._dt

    def _on_dt_changed(self, value: float) -> None:
        self._dt = max(0.001, value)
        self.plot_widget.set_time_tick_step(self._dt)

    def _on_signals_changed(self) -> None:
        configs = self.signal_panel.get_configs()
        self._signal_manager.set_signals(configs)
        self._resync_plot_axes()
        self.value_table.set_signal_names([c.name for c in configs if c.enabled])

    def _resync_plot_axes(self) -> None:
        enabled = [c for c in self.signal_panel.get_configs() if c.enabled]
        enabled_names = {c.name for c in enabled}
        for cfg in enabled:
            derived = SignalType(cfg.signal_type) == SignalType.CRITERIA
            # Applies configured y_min/y_max/dY only when this signal's own
            # axis config actually changed; never resets manually-adjusted
            # axes on unrelated updates or real-time refreshes.
            self.plot_widget.sync_axis_config(
                cfg.name, cfg.y_min, cfg.y_max, cfg.dy, derived=derived
            )
        for existing in self.plot_widget.signal_names():
            if existing not in enabled_names:
                self.plot_widget.remove_signal(existing)

    # -- playback -------------------------------------------------------------
    def playback(self) -> PlaybackController:
        return self._playback

    def _toggle_playback(self) -> None:
        self._playback.toggle(self._latest_sample_count())
        self._last_paused_end = None
        self._update_play_button()

    def _step_back(self) -> None:
        if not self._playback.is_paused():
            self._playback.pause_at(self._latest_sample_count())
        self._playback.back(self._latest_sample_count())
        self._last_paused_end = None

    def _step_forward(self) -> None:
        if not self._playback.is_paused():
            self._playback.pause_at(self._latest_sample_count())
        self._playback.forward(self._latest_sample_count())
        self._last_paused_end = None

    def _go_latest(self) -> None:
        self._playback.resume()
        self._last_paused_end = None
        self._update_play_button()

    def _update_play_button(self) -> None:
        self.play_btn.setText("\u25b6" if self._playback.is_paused() else "\u23f8")

    # -- runtime data --------------------------------------------------------
    def on_packet(self, packet: Packet) -> None:
        self._signal_manager.on_packet(packet)
        self.value_table.update_data(
            self._signal_manager.get_latest_data_values()
        )
        self.value_table.update_signal_values(
            self._signal_manager.get_latest_signal_outputs()
        )

    def _latest_sample_count(self) -> int:
        counts = []
        for cfg in self.signal_panel.get_configs():
            if not cfg.enabled:
                continue
            t, _ = self._signal_manager.get_plot_data(cfg.name)
            if t is not None:
                counts.append(int(t.size))
        return min(counts) if counts else 0

    def refresh_plot(self) -> None:
        count = self._latest_sample_count()
        end = self._playback.display_end_index(count)

        if self._playback.is_paused():
            if end == self._last_paused_end:
                return  # view frozen; nothing new to draw for this panel
            self._last_paused_end = end
        else:
            self._last_paused_end = None

        for cfg in self.signal_panel.get_configs():
            if not cfg.enabled:
                continue
            t, y = self._signal_manager.get_plot_data(cfg.name)
            if t is None or t.size == 0:
                continue
            if end < t.size:
                t = t[:end]
                y = y[:end]
            if t.size:
                self.plot_widget.update_signal_data(cfg.name, t, y)

    def clear(self) -> None:
        self._signal_manager.clear_all()
        self.plot_widget.clear()
        self.value_table.clear_signal_values()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._sized:
            self._sized = True
            width = max(self.plot_split.width(), 320)
            table_w = max(150, int(width * _INITIAL_TABLE_FRACTION))
            self.plot_split.setSizes(
                [table_w, max(table_w, width - table_w)]
            )
