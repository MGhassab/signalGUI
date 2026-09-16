"""End-to-end (non-GUI) test: raw bytes -> frame parser -> decode -> scaling
-> gain/offset -> signal output history, and verify numeric == plot value.

This validates the complete pipeline except the Qt widgets:

  bytes -> PacketParser -> Packet(raw_scaled)
        -> SignalManager -> ring buffers
        -> get_latest_signal_outputs() (numeric)
        -> get_plot_data() (plot, same buffer)

Run:  cd app && python3 -m unittest tests.test_pipeline -v
"""
from __future__ import annotations

import unittest

from models.packet import PACKET_FIELDS, FIELD_SIGNED, DATA_FIELDS, Packet
from models.signal_config import (
    RawSignalConfig, ComputationalSignalConfig, Operation,
)
from processing.signal_manager import SignalManager
from serial_io.packet_parser import (
    PacketParser,
    SyncFrameExtractor,
    HEADER_SIZE,
    PACKET_SIZE_BYTES,
    SYNC_HEADER,
    SYNC_FOOTER,
)


def build_frame(raw_by_field) -> bytes:
    chunks = []
    for i, name in enumerate(PACKET_FIELDS):
        raw = raw_by_field.get(name, 0)
        chunks.append(raw.to_bytes(2, "little", signed=FIELD_SIGNED[i]))
    return SYNC_HEADER + b"".join(chunks) + SYNC_FOOTER


class PipelineTest(unittest.TestCase):
    def test_full_pipeline_numeric_matches_plot(self):
        parser = PacketParser()
        mgr = SignalManager()
        cfg = RawSignalConfig(
            name="Pos", source_field="Position1", enabled=True,
            gain=5.0, offset=-2.0,
        )
        mgr.set_signals([cfg])

        t = 0.0
        for i in range(10):
            # Position1 raw = 1000 + i -> /1000 -> (1.0 + i/1000)
            raw_position = 1000 + i
            pkts = parser.feed(build_frame({"Position1": raw_position}))
            self.assertEqual(len(pkts), 1)
            pkt = pkts[0]
            mgr.on_packet(pkt, t=t)
            t += 0.05

            scaled = raw_position / 1000.0
            expected = scaled * 5.0 + (-2.0)

            # numeric readout
            numeric = mgr.get_latest_signal_outputs()["Pos"]
            self.assertAlmostEqual(numeric, expected, places=6)

            # plot buffer (same engine value)
            _, y = mgr.get_plot_data("Pos")
            self.assertAlmostEqual(float(y[-1]), expected, places=6)

        # Confirm the data rows (OD_DATA) were tracked too.
        latest = mgr.get_latest_data_values()
        self.assertIn("OD_DATA1", latest)
        self.assertIn("OD_DATA12", latest)

    def test_bad_frames_do_not_corrupt_data(self):
        parser = PacketParser()
        mgr = SignalManager()
        mgr.set_signals([
            RawSignalConfig(name="V", source_field="Bus_Voltage", enabled=True),
        ])

        good = build_frame({"Bus_Voltage": 12000})  # -> 12.0
        bad = bytearray(build_frame({"Bus_Voltage": 40000}))
        bad[-1] = 0  # corrupt footer -> rejected

        pkts = parser.feed(bytes(bad))
        self.assertEqual(len(pkts), 0)  # rejected

        pkts = parser.feed(good)
        self.assertEqual(len(pkts), 1)
        self.assertAlmostEqual(pkts[0].values["Bus_Voltage"], 12.0, places=6)

        # After the bad frame, data is unaffected: feeding good works.
        mgr.on_packet(pkts[0], t=0.0)
        self.assertAlmostEqual(mgr.get_latest_signal_outputs()["V"], 12.0, places=6)


class SignalEditTest(unittest.TestCase):
    """An edited signal must apply its new Gain/Offset WITHOUT requiring the
    user to also change the name. Regression for the stale-processor-config
    bug in SignalManager.set_signals."""

    @staticmethod
    def _latest(mgr, name) -> float:
        _, y = mgr.get_plot_data(name)
        return float(y[-1])

    def _seed(self, cfg, values):
        mgr = SignalManager()
        mgr.set_signals([cfg])
        t = 0.0
        for i, v in enumerate(values):
            mgr.on_packet(Packet(values={"DATA1": float(v)}, seq=i), t=t)
            t += 0.05
        return mgr

    def test_gain_only_edit_applies(self):
        mgr = self._seed(
            RawSignalConfig(name="S", source_field="DATA1", gain=1.0, offset=0.0),
            [10.0],
        )
        mgr.set_signals([
            RawSignalConfig(name="S", source_field="DATA1", gain=5.0, offset=0.0),
        ])
        mgr.on_packet(Packet(values={"DATA1": 10.0}, seq=1), t=1.0)
        self.assertAlmostEqual(self._latest(mgr, "S"), 50.0, places=6)

    def test_offset_only_edit_applies(self):
        mgr = self._seed(
            RawSignalConfig(name="S", source_field="DATA1", gain=1.0, offset=0.0),
            [10.0],
        )
        mgr.set_signals([
            RawSignalConfig(name="S", source_field="DATA1", gain=1.0, offset=2.0),
        ])
        mgr.on_packet(Packet(values={"DATA1": 10.0}, seq=1), t=1.0)
        self.assertAlmostEqual(self._latest(mgr, "S"), 12.0, places=6)

    def test_gain_and_offset_together_apply(self):
        mgr = self._seed(
            RawSignalConfig(name="S", source_field="DATA1", gain=1.0, offset=0.0),
            [10.0],
        )
        mgr.set_signals([
            RawSignalConfig(name="S", source_field="DATA1", gain=5.0, offset=2.0),
        ])
        mgr.on_packet(Packet(values={"DATA1": 10.0}, seq=1), t=1.0)
        self.assertAlmostEqual(self._latest(mgr, "S"), 52.0, places=6)

    def test_name_change_alone_still_works(self):
        mgr = self._seed(
            RawSignalConfig(name="S", source_field="DATA1", gain=5.0, offset=2.0),
            [10.0],
        )
        mgr.set_signals([
            RawSignalConfig(name="Renamed", source_field="DATA1", gain=5.0, offset=2.0),
        ])
        mgr.on_packet(Packet(values={"DATA1": 10.0}, seq=1), t=1.0)
        self.assertAlmostEqual(self._latest(mgr, "Renamed"), 52.0, places=6)

    def test_name_and_gain_offset_together_apply(self):
        mgr = self._seed(
            RawSignalConfig(name="S", source_field="DATA1", gain=1.0, offset=0.0),
            [10.0],
        )
        mgr.set_signals([
            RawSignalConfig(name="Renamed", source_field="DATA1", gain=5.0, offset=2.0),
        ])
        mgr.on_packet(Packet(values={"DATA1": 10.0}, seq=1), t=1.0)
        self.assertAlmostEqual(self._latest(mgr, "Renamed"), 52.0, places=6)

    def test_gain_offset_edit_preserves_existing_history(self):
        mgr = self._seed(
            RawSignalConfig(name="S", source_field="DATA1", gain=1.0, offset=0.0),
            [1.0, 2.0, 3.0],
        )
        _, before = mgr.get_plot_data("S")
        n_before = before.size
        mgr.set_signals([
            RawSignalConfig(name="S", source_field="DATA1", gain=10.0, offset=0.0),
        ])
        mgr.on_packet(Packet(values={"DATA1": 4.0}, seq=3), t=1.0)
        _, after = mgr.get_plot_data("S")
        # History kept, new sample appended using the new gain.
        self.assertEqual(after.size, n_before + 1)
        self.assertAlmostEqual(float(after[-1]), 40.0, places=6)

    def test_operation_change_rebuilds_processor(self):
        mgr = self._seed(
            ComputationalSignalConfig(
                name="C", source_field="DATA1", gain=1.0, offset=0.0,
                operation=Operation.INTEGRAL, x_degree=1,
            ),
            list(range(12)),
        )
        # Switch to derivative under the SAME name: must rebuild, not reuse
        # integral state.
        mgr.set_signals([
            ComputationalSignalConfig(
                name="C", source_field="DATA1", gain=1.0, offset=0.0,
                operation=Operation.DERIVATIVE, x_degree=1,
            ),
        ])
        before = mgr.get_plot_data("C")[0].size
        t = 1.0
        for v in range(12, 24):
            mgr.on_packet(Packet(values={"DATA1": float(v)}, seq=v), t=t)
            t += 0.05
        after = mgr.get_plot_data("C")[0].size
        self.assertGreater(after, before)


if __name__ == "__main__":
    unittest.main()
