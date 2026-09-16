"""Packet data model.

A `Packet` is the parsed representation of one fixed-size frame received
from the embedded device. It carries the decoded (protocol-scaled) values,
keyed by field name, plus metadata about when it arrived.

Protocol: 90-byte frame
  Header (3 bytes): 0xAA 0x55 0xA5
  Data   (84 bytes): 42 × uint16 little-endian fields
  Footer (3 bytes): 0x5A 0xAA 0x55

Per-field signedness and scaling are defined here as the single source
of truth for the wire format. The decoder applies them automatically.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List
import time

# Centralized, ordered definition of the packet's 42 two-byte fields.
# Position in this list == position in the wire packet.
PACKET_FIELDS: List[str] = [
    # Position (bytes 0–7, 4 × int16 LE, /1000)
    "Position1", "Position2", "Position3", "Position4",
    # Feedback (bytes 8–15, 4 × int16 LE, /1000)
    "Feedback1", "Feedback2", "Feedback3", "Feedback4",
    # Pot_Value (bytes 16–23, 4 × int16 LE, /1000)
    "Pot_Value1", "Pot_Value2", "Pot_Value3", "Pot_Value4",
    # Command (bytes 24–31, 4 × int16 LE, /1000)
    "Command1", "Command2", "Command3", "Command4",
    # Current (bytes 32–39, 4 × int16 LE, /1000)
    "Current1", "Current2", "Current3", "Current4",
    # Pwm (bytes 40–47, 4 × uint16 LE, /100)
    "Pwm1", "Pwm2", "Pwm3", "Pwm4",
    # Bus_Voltage (bytes 48–49, 1 × uint16 LE, /1000)
    "Bus_Voltage",
    # Bus_Current (bytes 50–51, 1 × int16 LE, /100)
    "Bus_Current",
    # Board_Temp (bytes 52–59, 4 × uint16 LE, /100)
    "Board_Temp1", "Board_Temp2", "Board_Temp3", "Board_Temp4",
    # OD_DATA (bytes 60–83, 12 × uint16 LE, /1000)
    "OD_DATA1", "OD_DATA2", "OD_DATA3", "OD_DATA4",
    "OD_DATA5", "OD_DATA6", "OD_DATA7", "OD_DATA8",
    "OD_DATA9", "OD_DATA10", "OD_DATA11", "OD_DATA12",
]

# Per-field signedness: True = int16 (signed), False = uint16 (unsigned).
# Parallel to PACKET_FIELDS.
FIELD_SIGNED: List[bool] = [
    True, True, True, True,           # Position
    True, True, True, True,           # Feedback
    True, True, True, True,           # Pot_Value
    True, True, True, True,           # Command
    True, True, True, True,           # Current
    False, False, False, False,       # Pwm
    False,                            # Bus_Voltage
    True,                             # Bus_Current
    False, False, False, False,       # Board_Temp
    False, False, False, False, False, False,
    False, False, False, False, False, False,  # OD_DATA
]

# Per-field scale divisor: raw_wire_value / divisor = engineering_value.
# Parallel to PACKET_FIELDS.
FIELD_SCALE: List[float] = [
    1000.0, 1000.0, 1000.0, 1000.0,  # Position
    1000.0, 1000.0, 1000.0, 1000.0,  # Feedback
    1000.0, 1000.0, 1000.0, 1000.0,  # Pot_Value
    1000.0, 1000.0, 1000.0, 1000.0,  # Command
    1000.0, 1000.0, 1000.0, 1000.0,  # Current
    100.0, 100.0, 100.0, 100.0,      # Pwm
    1000.0,                            # Bus_Voltage
    100.0,                             # Bus_Current
    100.0, 100.0, 100.0, 100.0,      # Board_Temp
    1000.0, 1000.0, 1000.0, 1000.0,
    1000.0, 1000.0, 1000.0, 1000.0,
    1000.0, 1000.0, 1000.0, 1000.0,  # OD_DATA
]

BYTES_PER_FIELD = 2
PACKET_SIZE_BYTES = len(PACKET_FIELDS) * BYTES_PER_FIELD  # 84 bytes

# OD_DATA fields: raw/auxiliary display values shown in the left table.
DATA_FIELDS: List[str] = [f"OD_DATA{i}" for i in range(1, 13)]

# The Command group: channels that may be used as a criteria signal's
# REFERENCE (see models/signal_config.py).
REFERENCE_FIELDS: List[str] = ["Command1", "Command2", "Command3", "Command4"]

# Fields that MAY be used as a normal signal's source / a criteria SOURCE.
# OD_DATA fields are deliberately excluded: they are raw/auxiliary
# display-only values (left data table), never user-selectable signals.
SIGNAL_FIELDS: List[str] = [f for f in PACKET_FIELDS if f not in DATA_FIELDS]

assert len(PACKET_FIELDS) == 42, "Packet layout must have exactly 42 fields"
assert len(FIELD_SIGNED) == 42
assert len(FIELD_SCALE) == 42
assert all(f in PACKET_FIELDS for f in REFERENCE_FIELDS)


@dataclass
class Packet:
    """One decoded packet from the device.

    values: field name -> decoded float value (post protocol scaling,
            PRE gain/offset — that transform happens later in the
            processing layer, not here).
    seq: monotonically increasing packet counter assigned by the parser.
    arrival_time: time.monotonic() timestamp of when the packet was fully
            assembled by the parser. Used as the shared plot time axis.
    """
    values: Dict[str, float]
    seq: int
    arrival_time: float = field(default_factory=time.monotonic)

    def get(self, source_field: str) -> float:
        try:
            return self.values[source_field]
        except KeyError as exc:
            raise KeyError(f"Unknown packet field '{source_field}'") from exc
