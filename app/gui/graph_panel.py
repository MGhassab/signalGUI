"""One independent analysis panel.

A single `GraphPanel` owns everything that makes up one analysis view so
panels never share mutable state:

- its own `SignalManager` (processors + plot history buffers),
- a `SignalPanel` (signal configuration table),
- a `PlotWidget`, a `LiveValueTable`,
- a `PlaybackController` (per-panel Play/Pause + history navigation).

The widget is a tabbed view with a slim control row on top:

    [ ▶/⏸ ] [ ◀ ] [ ▶ ] [ ⏮ Latest ]  dT (s): [____] [Show Raw Data] [⟲]

    [Plot] [Signal Configuration]

Play/Pause only affects THIS panel's DISPLAY. Data acquisition (packet
ingestion into the buffers) always continues, so a paused panel keeps its
full history and the user can step backward/forward through it or jump
back to live. The left Name/Value table shows the OD_DATA rows (raw,
display-only, hideable via "Show Raw Data") followed by the panel's enabled
signal outputs. The ⟲ button resets the plot panel (clear + axes + show
all plots + resume live).
"""
from __future__ import annotations

from typing import List, Optional, Set

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QTabWidget,
    QToolButton, QLabel, QDoubleSpinBox, QCheckBox,
)

from models.signal_config import SignalConfig, SignalType
from gui.live_value_table import LiveValueTable
from gui.plot_widget import PlotWidget
from gui.playback_controller import PlaybackController
from gui.signal_panel import SignalPanel

_INITIAL_TABLE_FRACTION = 0.22
_DEFAULT_TIME_TICK = 1.0  # seconds per major X-axis tick


class GraphPanel(QWidget):
    def __init__(self, core, parent=None):
        super().__init__(parent)
        # This panel's processed data lives in the shared, thread-safe
        # acquisition core (fed by the serial thread). The GUI only reads
        # snapshots from it - it never processes packets itself.
        self._core = core
        self._panel_id = core.register_panel()
        self._sized = False
        self._dt = _DEFAULT_TIME_TICK
        self._playback = PlaybackController()
        self._last_paused_end: float | None = None
        self._plot_hidden: Set[str] = set()

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
        controls.addSpacing(12)

        self.show_data_check = QCheckBox("Show Raw Data", self)
        self.show_data_check.setChecked(True)
        self.show_data_check.setToolTip(
            "Show/hide the fixed OD_DATA rows in the left readout"
        )
        self.show_data_check.toggled.connect(self._on_show_data_toggled)
        controls.addWidget(self.show_data_check)

        self.reset_plot_btn = QToolButton(self)
        self.reset_plot_btn.setText("\u21ba")  # ⟲
        self.reset_plot_btn.setToolTip(
            "Reset plot panel: clear data, restore axes, show all plots"
        )
        self.reset_plot_btn.clicked.connect(self.reset_plot)
        controls.addWidget(self.reset_plot_btn)

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
        self.signal_panel.plotVisibilityChanged.connect(self._on_plot_visibility)
        self.signal_panel.plotVisibilityReset.connect(self._on_plot_visibility_reset)

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
        self._core.set_panel_signals(self._panel_id, configs)
        valid = {c.name for c in configs}
        self._plot_hidden &= valid
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

    def _on_show_data_toggled(self, visible: bool) -> None:
        """Show/hide the fixed OD_DATA rows. Does not affect the plot or
        the underlying data, only their presentation in the left column."""
        self.value_table.set_data_visible(visible)

    def _on_plot_visibility(self, name: str, visible: bool) -> None:
        """Independent plot visibility: hides/unhides a signal's plot curve
        without affecting its numeric display or processing. The signal's
        data is still maintained; only the curve is shown/hidden."""
        if visible:
            self._plot_hidden.discard(name)
        else:
            self._plot_hidden.add(name)
        # Refresh so the curve appears/disappears immediately.
        self.refresh_plot()

    def _on_plot_visibility_reset(self) -> None:
        self._plot_hidden.clear()
        self._resync_plot_axes()

    # -- playback -------------------------------------------------------------
    def playback(self) -> PlaybackController:
        return self._playback

    def _toggle_playback(self) -> None:
        self._playback.toggle(self._latest_time())
        self._last_paused_end = None
        self._update_play_button()

    def _step_back(self) -> None:
        if not self._playback.is_paused():
            self._playback.pause_at(self._latest_time())
        self._step_time(-1)
        self._last_paused_end = None

    def _step_forward(self) -> None:
        if not self._playback.is_paused():
            self._playback.pause_at(self._latest_time())
        self._step_time(+1)
        self._last_paused_end = None

    def _go_latest(self) -> None:
        self._playback.resume()
        self._last_paused_end = None
        self._update_play_button()

    def _update_play_button(self) -> None:
        self.play_btn.setText("\u25b6" if self._playback.is_paused() else "\u23f8")

    # -- playback time helpers ------------------------------------------------
    def _latest_time(self) -> Optional[float]:
        """Latest sample time present on this panel (max over enabled
        signals). Signals are fed from the same packet stream, so in steady
        state this is the current global acquisition time."""
        return self._core.latest_time(self._panel_id)

    def _sample_times(self) -> np.ndarray:
        """Sorted unique sample times present on this panel (the global time
        axis). Signals enabled mid-session expose only their own later
        window, so the union across signals is the panel's viewable timeline.
        """
        return self._core.sample_times(self._panel_id)

    def _step_time(self, delta: int) -> None:
        """Move the paused playhead by one real sample on the shared time
        axis, snapped to the actual sample times present in the buffers."""
        times = self._sample_times()
        if times.size == 0:
            return
        earliest = float(times[0])
        latest = float(times[-1])
        cut = self._playback.cut_time()
        if cut is None:
            cut = latest
        tol = 1e-9
        if delta < 0:
            before = times[times < cut - tol]
            self._playback.seek(float(before[-1]) if before.size else earliest)
        elif delta > 0:
            after = times[times > cut + tol]
            self._playback.seek(float(after[0]) if after.size else latest)

    # -- runtime data --------------------------------------------------------
    @property
    def panel_id(self) -> int:
        return self._panel_id

    def _update_readout(self) -> None:
        """Refresh the Name/Value readout from the latest computed values.

        Called on the refresh cadence (NOT per packet), so a high incoming
        rate never turns into thousands of QTableWidget item updates per
        second on the GUI thread.
        """
        self.value_table.update_data(self._core.latest_data_values(self._panel_id))
        self.value_table.update_signal_values(
            self._core.latest_signal_outputs(self._panel_id)
        )

    def begin_new_session(self) -> None:
        """Reset this panel's DISPLAY for a new acquisition session.

        The shared acquisition core (`begin_session`) has already cleared
        the global timeline and every panel's buffers, so this only resets
        the local plot/readout presentation to the session's t = 0.
        """
        self.plot_widget.clear_curves()
        self.value_table.update_data(self._core.latest_data_values(self._panel_id))
        self.value_table.clear_signal_values()
        self._last_paused_end = None
        self._playback.resume()

    def refresh_plot(self) -> None:
        """Redraw every enabled signal aligned on the GLOBAL time axis.

        Live: each signal draws its full buffer. A signal enabled later has
        fewer samples and simply starts further right on the same axis - it
        never truncates the older signals to its own shorter length.

        Paused: every signal is sliced to the same wall-clock cut time, so
        stepping backward/forward stays time-aligned even when signals have
        different start times.
        """
        # Readout is throttled to this refresh cadence (decoupled from the
        # packet rate), and reflects the latest values even while paused.
        self._update_readout()

        if self._playback.is_paused():
            cut = self._playback.cut_time()
            if cut is None:
                cut = self._latest_time()
            if cut is None:
                return  # paused but nothing sampled yet
            if cut == self._last_paused_end:
                return  # view frozen; nothing new to draw for this panel
            self._last_paused_end = float(cut)
        else:
            self._last_paused_end = None
            cut = None

        for cfg in self.signal_panel.get_configs():
            if not cfg.enabled:
                continue
            if cfg.name in self._plot_hidden:
                # Plot is hidden: keep the curve empty but do not short-circuit
                # the readout (updated independently in _update_readout).
                self.plot_widget.clear_signal(cfg.name)
                continue
            t, y = self._core.plot_data(self._panel_id, cfg.name)
            if t is None or t.size == 0:
                continue
            if cut is not None:
                idx = int(np.searchsorted(t, cut, side="right"))
                if idx <= 0:
                    # This signal had no samples at/before the cut (its
                    # buffer starts later). Clear it so it does not keep
                    # stale data from the previous frame on screen.
                    self.plot_widget.clear_signal(cfg.name)
                    continue
                t = t[:idx]
                y = y[:idx]
            if t.size:
                self.plot_widget.update_signal_data(cfg.name, t, y)

    def clear(self) -> None:
        self._core.clear_panel(self._panel_id)
        self.plot_widget.clear_curves()
        self.value_table.clear_signal_values()

    def reset_plot(self) -> None:
        """Reset the plot panel to its default state.

        Restores: cleared data/history, default axis ranges (configured
        y_min/y_max), all signals' plots visible, live (un-paused) playback.
        Does NOT touch unrelated application state (signal configuration,
        serial, other panels).
        """
        # Clear data/history (both buffers and on-screen curves).
        self._core.clear_panel(self._panel_id)
        self.plot_widget.clear_curves()

        # Restore playback to live / latest.
        self._playback.resume()
        self._last_paused_end = None
        self._update_play_button()

        # Restore all plots to visible.
        self.signal_panel.reset_plot_visibility()
        self._plot_hidden.clear()

        # Reset axis ranges/ticks to the configured defaults.
        self._resync_plot_axes()
        self.plot_widget.reset_axes()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._sized:
            self._sized = True
            width = max(self.plot_split.width(), 320)
            table_w = max(150, int(width * _INITIAL_TABLE_FRACTION))
            self.plot_split.setSizes(
                [table_w, max(table_w, width - table_w)]
            )
