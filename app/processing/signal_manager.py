"""Wires together: incoming `Packet` -> per-signal processors -> bounded
ring buffers ready for plotting / the Data1-8 table.

This is the one place that knows how to go from a `Packet` to plottable
signal data; the GUI never touches processors or raw packet fields
directly - it only calls `SignalManager.on_packet()` and reads back
`get_plot_data()` / `get_latest_data_values()`.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np

from models.packet import Packet, DATA_FIELDS
from models.signal_config import SignalConfig, SignalType
from processing.base_processor import SignalProcessor
from processing.raw_processor import RawProcessor
from processing.computational_processor import ComputationalProcessor
from processing.criteria_processor import CriteriaProcessor
from processing.ring_buffer import RingBuffer

# Bounded samples retained per signal for plotting - prevents unbounded
# memory growth during long-running acquisitions.
PLOT_HISTORY_CAPACITY = 5000

_PROCESSOR_CLASSES = {
    SignalType.RAW: RawProcessor,
    SignalType.COMPUTATIONAL: ComputationalProcessor,
    SignalType.CRITERIA: CriteriaProcessor,
}


@dataclass
class _SignalRuntime:
    config: SignalConfig
    processor: SignalProcessor
    time_buffer: RingBuffer
    value_buffer: RingBuffer


class SignalManager:
    """Owns the list of configured signals and their runtime state
    (processor instances + plot history buffers), keyed by signal name."""

    def __init__(self) -> None:
        self._runtimes: Dict[str, _SignalRuntime] = {}
        self._latest_data_values: Dict[str, int] = {f: 0 for f in DATA_FIELDS}
        self._t0: Optional[float] = None

    # -- configuration ---------------------------------------------------
    def set_signals(self, configs: List[SignalConfig]) -> None:
        """Replace the full signal set. Existing runtime state (processor
        history, plot buffers) is preserved for signals whose name and
        type are unchanged, so editing one signal doesn't reset others
        or itself unnecessarily... except a signal is always rebuilt if
        its config object identity/type changed, to avoid stale state
        (e.g. switching operation type mid-run)."""
        new_runtimes: Dict[str, _SignalRuntime] = {}
        for cfg in configs:
            existing = self._runtimes.get(cfg.name)
            if existing is not None and existing.config.signal_type == cfg.signal_type:
                existing.config = cfg
                new_runtimes[cfg.name] = existing
            else:
                new_runtimes[cfg.name] = self._make_runtime(cfg)
        self._runtimes = new_runtimes

    def _make_runtime(self, cfg: SignalConfig) -> _SignalRuntime:
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

        for rt in self._runtimes.values():
            if not rt.config.enabled:
                continue
            try:
                raw_value = packet.get(rt.config.source_field)
            except KeyError:
                continue
            output = rt.processor.process(raw_value, t)
            rt.time_buffer.append(t)
            rt.value_buffer.append(output)

    def get_plot_data(self, name: str) -> Tuple[Optional[np.ndarray], Optional[np.ndarray]]:
        rt = self._runtimes.get(name)
        if rt is None:
            return None, None
        return rt.time_buffer.as_array(), rt.value_buffer.as_array()

    def get_latest_data_values(self) -> Dict[str, int]:
        return dict(self._latest_data_values)

    def clear_all(self) -> None:
        """Clears plotted history and resets processor state (e.g. the
        Integral running sum) for every signal, and resets the shared
        time origin."""
        self._t0 = None
        for rt in self._runtimes.values():
            rt.processor.reset()
            rt.time_buffer.clear()
            rt.value_buffer.clear()
