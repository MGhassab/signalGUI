"""Thread-safe acquisition core: the single source of truth for the global
timeline and every panel's processed signal data.

This is the object the GUI and the serial acquisition thread SHARE. All
access is serialized by one re-entrant lock, so:

    serial worker thread:  core.on_packets(packets)   # heavy processing
    GUI thread:            core.plot_data(...) etc.    # cheap snapshots

The GUI never processes packets. It only reads detached snapshots at its
own refresh cadence, which decouples a high incoming packet rate from
visualization: the acquisition thread keeps ingesting/processing, and the
GUI can take as long as it needs to redraw without causing missed or
corrupted samples.

TIME IS GLOBAL: the first packet of a session anchors t = 0; every panel
and signal share that one timeline. Panels created later are backfilled
from the retained history onto the same timeline.

Every mutation and every read acquires the lock. Reads return COPIES
(never views into the ring buffers), so a concurrent append cannot change
data while the GUI is drawing it.
"""
from __future__ import annotations

import threading
from collections import deque
from itertools import count
from typing import Dict, List, Optional, Tuple

import numpy as np

from models.packet import Packet
from processing.signal_manager import SignalManager

# Number of (t, packet) entries retained for late-created panels.
HISTORY_CAPACITY = 5000


class AcquisitionCore:
    def __init__(self, history_capacity: int = HISTORY_CAPACITY) -> None:
        self._lock = threading.RLock()
        self._anchor: Optional[float] = None
        self._history: deque = deque(maxlen=history_capacity)
        self._panels: Dict[int, SignalManager] = {}
        self._ids = count(1)

    # -- panel lifecycle (called from the GUI thread) -------------------------
    def register_panel(self) -> int:
        """Create a fresh processing runtime for a panel; returns its id."""
        with self._lock:
            pid = next(self._ids)
            self._panels[pid] = SignalManager()
            return pid

    def unregister_panel(self, panel_id: int) -> None:
        with self._lock:
            self._panels.pop(panel_id, None)

    def set_panel_signals(self, panel_id: int, configs) -> None:
        with self._lock:
            sm = self._panels.get(panel_id)
            if sm is not None:
                sm.set_signals(configs)

    def clear_panel(self, panel_id: int) -> None:
        """Clear a panel's history/processors (plot clear / reset)."""
        with self._lock:
            sm = self._panels.get(panel_id)
            if sm is not None:
                sm.clear_all()

    def begin_session(self) -> None:
        """New acquisition session: reset the global anchor and drop the
        retained history, and clear every panel's buffers and raw readout."""
        with self._lock:
            self._anchor = None
            self._history.clear()
            for sm in self._panels.values():
                sm.reset_session()

    def backfill_panel(self, panel_id: int) -> None:
        """Replay retained history into a freshly created panel so it lands
        on the SAME global timeline as everyone else."""
        with self._lock:
            sm = self._panels.get(panel_id)
            if sm is None:
                return
            for t, packet in self._history:
                sm.on_packet(packet, t)

    def has_history(self) -> bool:
        with self._lock:
            return bool(self._history)

    # -- ingestion (called from the serial worker thread) ---------------------
    def on_packets(self, packets: List[Packet]) -> None:
        with self._lock:
            for packet in packets:
                t = self._stamp(packet)
                self._history.append((t, packet))
                for sm in self._panels.values():
                    sm.on_packet(packet, t)

    def on_packet(self, packet: Packet,
                  t: Optional[float] = None) -> float:
        """Process a single packet. Used by tests / synchronous callers;
        `t` is assigned from the global anchor when omitted."""
        with self._lock:
            if t is None:
                t = self._stamp(packet)
            elif self._anchor is None:
                self._anchor = packet.arrival_time
            self._history.append((t, packet))
            for sm in self._panels.values():
                sm.on_packet(packet, t)
            return t

    def _stamp(self, packet: Packet) -> float:
        if self._anchor is None:
            self._anchor = packet.arrival_time
            return 0.0
        return packet.arrival_time - self._anchor

    # -- snapshots for the GUI (copies, never views) --------------------------
    def plot_data(self, panel_id: int, name: str
                  ) -> Tuple[Optional[np.ndarray], Optional[np.ndarray]]:
        with self._lock:
            sm = self._panels.get(panel_id)
            if sm is None:
                return None, None
            t, y = sm.get_plot_data(name)
            if t is None or y is None:
                return None, None
            return t.copy(), y.copy()

    def latest_data_values(self, panel_id: int) -> Dict[str, float]:
        with self._lock:
            sm = self._panels.get(panel_id)
            return sm.get_latest_data_values() if sm is not None else {}

    def latest_signal_outputs(self, panel_id: int) -> Dict[str, float]:
        with self._lock:
            sm = self._panels.get(panel_id)
            return sm.get_latest_signal_outputs() if sm is not None else {}

    def latest_time(self, panel_id: int) -> Optional[float]:
        with self._lock:
            sm = self._panels.get(panel_id)
            if sm is None:
                return None
            latest: Optional[float] = None
            for cfg in sm.get_configs():
                if not cfg.enabled:
                    continue
                t, _ = sm.get_plot_data(cfg.name)
                if t is not None and t.size:
                    cand = float(t[-1])
                    if latest is None or cand > latest:
                        latest = cand
            return latest

    def sample_times(self, panel_id: int) -> np.ndarray:
        with self._lock:
            sm = self._panels.get(panel_id)
            if sm is None:
                return np.empty(0)
            arrays = []
            for cfg in sm.get_configs():
                if not cfg.enabled:
                    continue
                t, _ = sm.get_plot_data(cfg.name)
                if t is not None and t.size:
                    arrays.append(t)
            if not arrays:
                return np.empty(0)
            return np.unique(np.concatenate(arrays))
