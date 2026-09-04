"""Packet data model.

A `Packet` is the parsed representation of one fixed-size frame received
from the embedded device. It carries the raw (gain/offset-less) values,
keyed by field name, plus metadata about when it arrived.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List
import time

# Centralized, ordered definition of the packet's 42 two-byte fields.
# Position in this list == position in the wire packet. This is the ONLY
# place the packet layout should be defined - do not duplicate elsewhere.
PACKET_FIELDS: List[str] = [
    # Position (16)
    "position11", "position12", "position13", "position14",
    "position21", "position22", "position23", "position24",
    "position31", "position32", "position33", "position34",
    "position41", "position42", "position43", "position44",
    # Current (4)
    "current11", "current12", "current13", "current14",
    # PWM (4)
    "PWM11", "PWM12", "PWM13", "PWM14",
    # Temperature (4)
    "temperature11", "temperature12", "temperature13", "temperature14",
    # IVP (2)
    "IVP11", "IVP12",
    # Voltage (4)
    "AVoltage11", "AVoltage12", "AVoltage13", "AVoltage14",
    # Generic data (8)
    "Data1", "Data2", "Data3", "Data4", "Data5", "Data6", "Data7", "Data8",
]

BYTES_PER_FIELD = 2
PACKET_SIZE_BYTES = len(PACKET_FIELDS) * BYTES_PER_FIELD  # 84 bytes

DATA_FIELDS: List[str] = [f"Data{i}" for i in range(1, 9)]

# The Position-4 group: the only channels that may be used as a criteria
# signal's REFERENCE (see models/signal_config.py).
POSITION4_FIELDS: List[str] = [f"position4{i}" for i in range(1, 5)]

assert len(PACKET_FIELDS) == 42, "Packet layout must have exactly 42 fields"
assert all(f in PACKET_FIELDS for f in POSITION4_FIELDS)


@dataclass
class Packet:
    """One decoded packet from the device.

    values: field name -> decoded integer value (post endianness/sign
            interpretation, PRE gain/offset - that transform happens later
            in the processing layer, not here).
    seq: monotonically increasing packet counter assigned by the parser.
    arrival_time: time.monotonic() timestamp of when the packet was fully
            assembled by the parser. NOTE: this is used as the shared plot
            time axis, but it is NOT the same thing as any signal's
            configured `dT` (see models/signal_config.py).
    """
    values: Dict[str, int]
    seq: int
    arrival_time: float = field(default_factory=time.monotonic)

    def get(self, source_field: str) -> int:
        try:
            return self.values[source_field]
        except KeyError as exc:
            raise KeyError(f"Unknown packet field '{source_field}'") from exc
