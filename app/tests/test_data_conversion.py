"""Data conversion tests.

Verifies:
  - every field uses the correct signed/unsigned type and scale factor
  - protocol scaling is applied exactly once (not twice)
  - gain/offset, when applied through a processor, produce the SAME value
    used for both the plot buffer and the numeric readout
  - negative int16 and high uint16 values

Run:  cd app && python3 -m unittest tests.test_data_conversion -v
"""
from __future__ import annotations

import unittest

import numpy as np

from models.packet import (
    PACKET_FIELDS, FIELD_SIGNED, FIELD_SCALE, DATA_FIELDS,
)
from models.signal_config import RawSignalConfig
from processing.raw_processor import RawProcessor
from processing.signal_manager import SignalManager
from serial_io.packet_parser import PacketParser, HEADER_SIZE, SYNC_HEADER, SYNC_FOOTER, PACKET_SIZE_BYTES
from models.packet import Packet


def build_frame(raw_by_field) -> bytes:
    """Build a 90-byte frame with specific raw ints per field.

    raw_by_field: dict {field_name: raw_int}. Others use seed 0.
    """
    chunks = []
    for i, name in enumerate(PACKET_FIELDS):
        raw = raw_by_field.get(name, 0)
        signed = FIELD_SIGNED[i]
        chunks.append(raw.to_bytes(2, "little", signed=signed))
    return SYNC_HEADER + b"".join(chunks) + SYNC_FOOTER


def decode(raw_by_field) -> dict:
    p = PacketParser()
    pkts = p.feed(build_frame(raw_by_field))
    assert len(pkts) == 1
    return pkts[0].values


def expected_value(name: str, raw: int) -> float:
    idx = PACKET_FIELDS.index(name)
    return raw / FIELD_SCALE[idx]


class ScalingTest(unittest.TestCase):
    def test_all_scales_positive(self):
        self.assertTrue(all(s > 0 for s in FIELD_SCALE))

    def test_all_signedness_consistent_with_scale_fields(self):
        self.assertEqual(len(FIELD_SIGNED), len(PACKET_FIELDS))
        self.assertEqual(len(FIELD_SCALE), len(PACKET_FIELDS))

    def test_signed_fields_decode_negative(self):
        v = decode({"Position1": -2500, "Feedback2": -777,
                    "Pot_Value3": -42, "Command4": -1,
                    "Current1": -9999, "Bus_Current": -5})
        self.assertAlmostEqual(v["Position1"], -2.5, places=6)
        self.assertAlmostEqual(v["Feedback2"], -0.777, places=6)
        self.assertAlmostEqual(v["Pot_Value3"], -0.042, places=6)
        self.assertAlmostEqual(v["Command4"], -0.001, places=6)
        self.assertAlmostEqual(v["Current1"], -9.999, places=6)
        self.assertAlmostEqual(v["Bus_Current"], -0.05, places=6)

    def test_unsigned_fields_reject_sign_bit(self):
        # Pwm (uint16) with raw 65535 must decode as +655.35, not -0.01.
        v = decode({"Pwm1": 65535})
        self.assertAlmostEqual(v["Pwm1"], 655.35, places=6)

        v = decode({"Bus_Voltage": 33000})
        self.assertAlmostEqual(v["Bus_Voltage"], 33.0, places=6)

    def test_scaling_applied_exactly_once(self):
        # Position1 raw 1234 -> /1000 = 1.234 (not doubly scaled).
        v = decode({"Position1": 1234})
        self.assertAlmostEqual(v["Position1"], 1.234, places=6)

        # OD_DATA uint16
        v = decode({"OD_DATA12": 4567})
        self.assertAlmostEqual(v["OD_DATA12"], 4.567, places=6)

    def test_scaling_matches_spec_per_field(self):
        # Spot-check one field from each scale group.
        checks = {
            "Position1": (1500, 1000),
            "Feedback1": (1500, 1000),
            "Pot_Value1": (1500, 1000),
            "Command1": (1500, 1000),
            "Current1": (1500, 1000),
            "Pwm1": (1500, 100),
            "Bus_Voltage": (1500, 1000),
            "Bus_Current": (1500, 100),
            "Board_Temp1": (1500, 100),
            "OD_DATA1": (1500, 1000),
            "OD_DATA12": (1500, 1000),
        }
        for name, (raw, divisor) in checks.items():
            v = decode({name: raw})
            self.assertAlmostEqual(v[name], raw / divisor, places=6,
                                   msg=name)


class GainOffsetConsistencyTest(unittest.TestCase):
    def test_plot_and_numeric_use_same_processed_value(self):
        """The value in the value-buffer (used by both plot and numeric
        readout) equals the processor output = scaled * gain + offset."""
        gain, offset = 2.0, -5.0

        mgr = SignalManager()
        cfg = RawSignalConfig(
            name="Pos", source_field="Position1", enabled=True,
            gain=gain, offset=offset,
        )
        mgr.set_signals([cfg])

        raw_scaled = 1.234  # already protocol-scaled value carried by packet
        expected = raw_scaled * gain + offset

        packet = Packet(values={"Position1": raw_scaled, **{f: 0.0 for f in DATA_FIELDS}}, seq=0)
        mgr.on_packet(packet, t=1.0)

        # Numeric readout
        outputs = mgr.get_latest_signal_outputs()
        self.assertAlmostEqual(outputs["Pos"], expected, places=6)

        # Plot buffer (identical value, from the same ring buffer)
        t, y = mgr.get_plot_data("Pos")
        self.assertAlmostEqual(float(y[-1]), expected, places=6)

    def test_gain_offset_consistent_across_many_samples(self):
        gain, offset = 3.0, 0.5
        mgr = SignalManager()
        mgr.set_signals([
            RawSignalConfig(name="Volt", source_field="Bus_Voltage",
                            enabled=True, gain=gain, offset=offset),
        ])
        for i in range(20):
            raw = 12.5 + i * 0.1
            expected = raw * gain + offset
            packet = Packet(values={"Bus_Voltage": raw, **{f: 0.0 for f in DATA_FIELDS}}, seq=i)
            mgr.on_packet(packet, t=float(i))
            o = mgr.get_latest_signal_outputs()["Volt"]
            self.assertAlmostEqual(o, expected, places=6)

    def test_processor_directly_matches_signal_manager(self):
        """RawProcessor.apply path equals SignalManager's buffered output
        for the same raw value (guards against double application)."""
        gain, offset = 1.5, -0.25
        cfg = RawSignalConfig(name="X", source_field="Position1",
                              enabled=True, gain=gain, offset=offset)
        proc = RawProcessor(cfg)
        mgr = SignalManager()
        mgr.set_signals([cfg])

        for raw_scaled in [0.0, 1.0, -2.5, 123.456]:
            direct = None
            for _t, val in proc.process(raw_scaled, 0.0):
                direct = val
            packet = Packet(values={"Position1": raw_scaled, **{f: 0.0 for f in DATA_FIELDS}}, seq=0)
            mgr.on_packet(packet, t=1.0)
            from_sm = mgr.get_latest_signal_outputs()["X"]
            self.assertAlmostEqual(direct, from_sm, places=6)


if __name__ == "__main__":
    unittest.main()
