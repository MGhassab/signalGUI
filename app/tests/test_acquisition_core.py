"""Headless tests for the decoupled acquisition path.

Covers the failure modes that matter at high baud rates:

- no packet loss / no reordering regardless of how the byte stream is
  chunked across reads (1-byte reads, split frames, large bursts),
- one shared global timeline with correct ordering/timestamps,
- backfill of a late-created panel onto that same timeline,
- baud-based per-frame timestamp reconstruction (monotonic, correctly
  spaced), which fixes the compressed time axis at high rates.

Run:  cd app && python3 -m unittest tests.test_acquisition_core -v
"""
from __future__ import annotations

import unittest

from models.packet import Packet, PACKET_FIELDS, FIELD_SIGNED
from models.signal_config import RawSignalConfig
from serial_io.packet_parser import (
    PacketParser, SYNC_HEADER, SYNC_FOOTER,
)
from acquisition.core import AcquisitionCore
from serial_io.serial_manager import _SerialWorker, BITS_PER_BYTE
from serial_io.packet_parser import FRAME_TOTAL_SIZE

import struct


def build_frame(raw_by_field) -> bytes:
    chunks = []
    for i, name in enumerate(PACKET_FIELDS):
        raw = raw_by_field.get(name, 0)
        chunks.append(raw.to_bytes(2, "little", signed=FIELD_SIGNED[i]))
    return SYNC_HEADER + b"".join(chunks) + SYNC_FOOTER


def frame_for_position(i: int) -> bytes:
    # Position1 raw = i -> decoded = i/1000 exactly (int16-safe for i < 32768).
    return build_frame({"Position1": i})


def feed_stream(core: AcquisitionCore, panel_id: int, data: bytes,
                chunk: int, parser: PacketParser) -> None:
    for start in range(0, len(data), chunk):
        for pkt in parser.feed(data[start:start + chunk]):
            core.on_packets([pkt])


class AcquisitionCoreTest(unittest.TestCase):
    def _make(self):
        core = AcquisitionCore()
        pid = core.register_panel()
        core.set_panel_signals(pid, [
            RawSignalConfig(name="S", source_field="Position1",
                            gain=1.0, offset=0.0),
        ])
        return core, pid

    def test_no_loss_or_reorder_across_chunk_sizes(self):
        n = 500
        data = b"".join(frame_for_position(i) for i in range(n))
        for chunk in (1, 3, 7, 89, 90, 91, 1000, len(data)):
            parser = PacketParser()
            core, pid = self._make()
            feed_stream(core, pid, data, chunk, parser)
            t, y = core.plot_data(pid, "S")
            self.assertEqual(t.size, n, f"chunk={chunk}: lost samples")
            self.assertEqual(y.size, n, f"chunk={chunk}: lost samples")
            # Values are the exact frames, in order (raw / 1000).
            self.assertEqual([float(v) for v in y],
                             [i / 1000.0 for i in range(n)])
            # Timestamps strictly increasing (global order preserved).
            self.assertTrue((t[1:] > t[:-1]).all(),
                            f"chunk={chunk}: timestamps not increasing")

    def test_split_frames_reassembled(self):
        parser = PacketParser()
        core, pid = self._make()
        data = b"".join(frame_for_position(i) for i in range(50))
        # Feed one byte at a time: every frame is split across reads.
        feed_stream(core, pid, data, 1, parser)
        _, y = core.plot_data(pid, "S")
        self.assertEqual(y.size, 50)
        self.assertEqual(float(y[0]), 0.0)
        self.assertAlmostEqual(float(y[-1]), 49.0 / 1000.0, places=9)

    def test_global_timeline_anchored_at_zero(self):
        core, pid = self._make()
        base = 1000.0
        dt = 0.05
        for i in range(10):
            pkt = Packet(values={f: 0.0 for f in PACKET_FIELDS}, seq=i,
                         arrival_time=base + i * dt)
            core.on_packet(pkt)
        t, _ = core.plot_data(pid, "S")
        self.assertAlmostEqual(float(t[0]), 0.0, places=9)
        self.assertAlmostEqual(float(t[-1]), 9 * dt, places=9)

    def test_backfill_late_panel_shares_timeline(self):
        core, pid_a = self._make()
        base = 5000.0
        for i in range(30):
            pkt = Packet(values={f: 0.0 for f in PACKET_FIELDS}, seq=i,
                         arrival_time=base + i * 0.05)
            core.on_packet(pkt)

        # New panel created after acquisition started.
        pid_b = core.register_panel()
        core.set_panel_signals(pid_b, [
            RawSignalConfig(name="S", source_field="Position1"),
        ])
        core.backfill_panel(pid_b)

        ta, ya = core.plot_data(pid_a, "S")
        tb, yb = core.plot_data(pid_b, "S")
        self.assertEqual(ta.size, 30)
        self.assertEqual(tb.size, 30)
        self.assertTrue((ta == tb).all())
        self.assertTrue((ya == yb).all())

    def test_begin_session_resets_timeline_and_buffers(self):
        core, pid = self._make()
        for i in range(5):
            core.on_packet(Packet(values={f: 0.0 for f in PACKET_FIELDS},
                                  seq=i, arrival_time=100.0 + i))
        core.begin_session()
        t, y = core.plot_data(pid, "S")
        self.assertEqual(t.size, 0)
        self.assertEqual(y.size, 0)
        # First packet of the new session anchors at 0 again.
        core.on_packet(Packet(values={f: 0.0 for f in PACKET_FIELDS},
                              seq=0, arrival_time=9000.0))
        t, _ = core.plot_data(pid, "S")
        self.assertAlmostEqual(float(t[0]), 0.0, places=9)


class TimestampReconstructionTest(unittest.TestCase):
    def _worker(self, baud: int):
        return _SerialWorker("loop://", baud, PacketParser(), core=None)

    def test_frame_times_spaced_by_baud(self):
        baud = 921600
        worker = self._worker(baud)
        frame_seconds = BITS_PER_BYTE * FRAME_TOTAL_SIZE / baud
        packets = [Packet(values={}, seq=i, arrival_time=0.0) for i in range(10)]
        worker._stamp_packets(packets, now=100.0, frame_seconds=frame_seconds)
        times = [p.arrival_time for p in packets]
        # Last frame arrives at `now`; earlier frames are one frame-time apart.
        self.assertAlmostEqual(times[-1], 100.0, places=9)
        self.assertAlmostEqual(times[0], 100.0 - 9 * frame_seconds, places=9)
        self.assertTrue(all(b > a for a, b in zip(times, times[1:])))

    def test_times_monotonic_across_reads(self):
        baud = 115200
        worker = self._worker(baud)
        frame_seconds = BITS_PER_BYTE * FRAME_TOTAL_SIZE / baud
        first = [Packet(values={}, seq=i, arrival_time=0.0) for i in range(5)]
        worker._stamp_packets(first, now=10.0, frame_seconds=frame_seconds)
        # Second read happens only slightly later than the first frame would
        # imply -> the clamp must still keep times strictly increasing.
        second = [Packet(values={}, seq=i, arrival_time=0.0) for i in range(5)]
        worker._stamp_packets(second, now=10.0, frame_seconds=frame_seconds)
        all_times = [p.arrival_time for p in first + second]
        self.assertTrue(all(b > a for a, b in zip(all_times, all_times[1:])))


if __name__ == "__main__":
    unittest.main()
