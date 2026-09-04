"""Centralized acquisition-session manager: the single source of truth for
the global monitoring timeline.

Every decoded packet is assigned ONE timestamp here, before it is
distributed to any panel:

    Serial -> parse -> AcquisitionManager.feed(packet) -> (t, packet)
        -> Panel 1 / Panel 2 / Panel 3 ...

so all panels and all signals share exactly the same acquisition timeline.
Panels never compute their own time origin; creating a panel or configuring
a signal later simply continues on the global timeline.

A new acquisition session starts only when `begin()` is called (on every
successful serial Connect). `begin()` clears the anchor and the retained
history; the first packet of the session anchors global time at t = 0.
Nothing else (panel create/close, signal add/remove/enable/disable, config
change, GUI refresh) ever resets the timeline.

A bounded history of (t, packet) is retained so a panel created after
acquisition already started can be backfilled onto the same global timeline.
"""
from __future__ import annotations

from collections import deque
from typing import Deque, Iterable, List, Optional, Tuple

from models.packet import Packet

# Number of (t, packet) entries retained for late-created panels.
HISTORY_CAPACITY = 5000


class AcquisitionManager:
    def __init__(self) -> None:
        self._anchor: Optional[float] = None
        self._history: Deque[Tuple[float, Packet]] = deque(maxlen=HISTORY_CAPACITY)

    def begin(self) -> None:
        """Start a new acquisition session: reset time to 0 (first packet)
        and drop retained history."""
        self._anchor = None
        self._history.clear()

    def feed(self, packet: Packet) -> float:
        """Assign the global timestamp for one packet and record it.

        Returns the global time `t` (session-relative seconds). The first
        packet of a session anchors t = 0.
        """
        if self._anchor is None:
            self._anchor = packet.arrival_time
            t = 0.0
        else:
            t = packet.arrival_time - self._anchor
        self._history.append((t, packet))
        return t

    # -- history for late-created panels -------------------------------------
    def has_history(self) -> bool:
        return bool(self._history)

    def entries(self) -> List[Tuple[float, Packet]]:
        """Retained packets, oldest first, as (global_t, packet)."""
        return list(self._history)

    def iter_entries(self) -> Iterable[Tuple[float, Packet]]:
        yield from self._history
