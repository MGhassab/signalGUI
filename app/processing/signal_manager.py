"""Wires together: incoming `Packet` -> per-signal processors -> bounded
ring buffers ready for plotting / per-panel Name/Value readouts.

One `SignalManager` exists per graph panel. This is the one place that
knows how to go from a `Packet` to plottable signal data; the GUI never
touches processors or raw packet fields directly - it only calls
`SignalManager.on_packet()` and reads back `get_plot_data()` /
`get_latest_signal_outputs()`.

Two kinds of rows are handled:

1. Raw / Computational signals - single-input processors fed one raw
   packet value per tick (unchanged).
2. Criteria signals - DERIVED metrics that compare a SOURCE (a configured
   signal in this panel, or a raw channel) against a POSITION-4 reference
   channel via a `CriteriaEngine`. Criteria rows are updated in a second
   pass (after ordinary signals), so a criteria row whose source is another
   signal sees that signal's freshly-appended value for the same packet.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np

from models.packet import Packet, DATA_FIELDS
from models.signal_config import (
    SignalConfig, SignalType, SourceKind, CriteriaSignalConfig,
)
from processing.base_processor import SignalProcessor
from processing.raw_processor import RawProcessor
from processing.computational_processor import ComputationalProcessor
from processing.criteria import CriteriaEngine
from processing.ring_buffer import RingBuffer

# Bounded samples retained per signal for plotting - prevents unbounded
# memory growth during long-running acquisitions.
PLOT_HISTORY_CAPACITY = 5000

_PROCESSOR_CLASSES = {
    SignalType.RAW: RawProcessor,
    SignalType.COMPUTATIONAL: ComputationalProcessor,
}


def _criteria_params(a: CriteriaSignalConfig, b: CriteriaSignalConfig) -> bool:
    fields = (
        "source_kind", "source_signal", "source_field", "reference_field",
        "criterion", "ss_error_percent", "settling_tolerance_pct",
        "rise_low_pct", "rise_high_pct", "fall_low_pct", "fall_high_pct",
        "inverse_window_s", "inverse_min_amplitude", "inverse_min_duration_s",
        "step_threshold", "gain", "offset",
    )
    return all(getattr(a, f) == getattr(b, f) for f in fields)


@dataclass
class _SignalRuntime:
    config: SignalConfig
    processor: Optional[SignalProcessor] = None
    engine: Optional[CriteriaEngine] = None
    time_buffer: RingBuffer = None
    value_buffer: RingBuffer = None


class SignalManager:
    """Owns the list of configured signals and their runtime state
    (processors/engines + plot history buffers), keyed by signal name."""

    def __init__(self) -> None:
        self._runtimes: Dict[str, _SignalRuntime] = {}
        self._latest_data_values: Dict[str, int] = {f: 0 for f in DATA_FIELDS}
        self._t0: Optional[float] = None

    # -- configuration ---------------------------------------------------
    def set_signals(self, configs: List[SignalConfig]) -> None:
        """Replace the full signal set.

        Existing runtime state (processor/engine history, plot buffers) is
        preserved for a signal whose name and type are unchanged, so
        editing one signal doesn't reset the others. A criteria row whose
        computation-relevant parameters changed is rebuilt fresh (its old
        step analysis would otherwise be meaningless).
        """
        new_runtimes: Dict[str, _SignalRuntime] = {}
        for cfg in configs:
            existing = self._runtimes.get(cfg.name)
            if existing is not None and existing.config.signal_type == cfg.signal_type:
                if cfg.signal_type == SignalType.CRITERIA:
                    if _criteria_params(cfg, existing.config):
                        existing.config = cfg
                        if existing.engine is not None:
                            existing.engine.config = cfg
                        new_runtimes[cfg.name] = existing
                        continue
                    # params changed -> fall through and rebuild fresh
                else:
                    existing.config = cfg
                    new_runtimes[cfg.name] = existing
                    continue
            new_runtimes[cfg.name] = self._make_runtime(cfg)
        self._runtimes = new_runtimes

    def _make_runtime(self, cfg: SignalConfig) -> _SignalRuntime:
        if cfg.signal_type == SignalType.CRITERIA:
            return _SignalRuntime(
                config=cfg,
                engine=CriteriaEngine(cfg),
                time_buffer=RingBuffer(PLOT_HISTORY_CAPACITY),
                value_buffer=RingBuffer(PLOT_HISTORY_CAPACITY),
            )
        processor_cls = _PROCESSOR_CLASSES[SignalType(cfg.signal_type)]
        return _SignalRuntime(
            config=cfg,
            processor=processor_cls(cfg),
            time_buffer=RingBuffer(PLOT_HISTORY_CAPACITY),
            value_buffer=RingBuffer(PLOT_HISTORY_CAPACITY),
        )

    def get_configs(self) -> List[SignalConfig]:
        return [rt.config for rt in self._runtimes.values()]

    # -- runtime -----------------------------------------------------------
    def on_packet(self, packet: Packet) -> None:
        if self._t0 is None:
            self._t0 = packet.arrival_time
        t = packet.arrival_time - self._t0

        for field_name in DATA_FIELDS:
            if field_name in packet.values:
                self._latest_data_values[field_name] = packet.values[field_name]

        # Pass 1: ordinary single-input signals.
        for rt in self._runtimes.values():
            if rt.processor is None or not rt.config.enabled:
                continue
            try:
                raw_value = packet.get(rt.config.source_field)
            except KeyError:
                continue
            output = rt.processor.process(raw_value, t)
            rt.time_buffer.append(t)
            rt.value_buffer.append(output)

        # Pass 2: derived criteria signals (source signals already updated).
        for rt in self._runtimes.values():
            if rt.engine is None or not rt.config.enabled:
                continue
            self._update_criteria(rt, packet, t)

    def _update_criteria(self, rt: _SignalRuntime, packet: Packet, t: float) -> None:
        cfg: CriteriaSignalConfig = rt.config

        source = None
        if SourceKind(cfg.source_kind) == SourceKind.SIGNAL:
            src_rt = self._runtimes.get(cfg.source_signal)
            if (src_rt is not None and src_rt.processor is not None
                    and src_rt.config.enabled):
                vals = src_rt.value_buffer.as_array()
                if vals.size:
                    source = float(vals[-1])
        else:
            try:
                raw = packet.get(cfg.source_field)
            except KeyError:
                raw = None
            if raw is not None:
                source = raw * cfg.gain + cfg.offset

        try:
            reference = packet.get(cfg.reference_field)
        except KeyError:
            reference = None

        if source is None or reference is None:
            return  # skip this tick (e.g. missing source signal/channel)

        output = rt.engine.update(t, source, float(reference))
        rt.time_buffer.append(t)
        rt.value_buffer.append(output)

    def get_plot_data(self, name: str) -> Tuple[Optional[np.ndarray], Optional[np.ndarray]]:
        rt = self._runtimes.get(name)
        if rt is None:
            return None, None
        return rt.time_buffer.as_array(), rt.value_buffer.as_array()

    def get_latest_data_values(self) -> Dict[str, int]:
        return dict(self._latest_data_values)

    def get_latest_signal_outputs(self) -> Dict[str, float]:
        """Latest computed output sample per *enabled* signal. Used by the
        per-panel Name/Value readout. Disabled signals are omitted."""
        outputs: Dict[str, float] = {}
        for name, rt in self._runtimes.items():
            if not rt.config.enabled:
                continue
            vals = rt.value_buffer.as_array()
            if vals.size:
                outputs[name] = float(vals[-1])
        return outputs

    def clear_all(self) -> None:
        """Clears plotted history and resets processor/engine state for
        every signal, and resets the shared time origin."""
        self._t0 = None
        for rt in self._runtimes.values():
            if rt.processor is not None:
                rt.processor.reset()
            if rt.engine is not None:
                rt.engine.reset()
            rt.time_buffer.clear()
            rt.value_buffer.clear()
