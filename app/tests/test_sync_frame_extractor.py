"""Tests for the 90-byte frame stream parser (header/footer synchronization).

Verifies the `SyncFrameExtractor` + `PacketDecoder` behavior:

  - valid 90-byte frame accepted
  - invalid header ignored until next valid header
  - invalid footer -> frame rejected
  - partial frame across multiple reads reconstructed
  - multiple frames in one read all decoded
  - noise before header resynchronizes
  - negative int16 values decoded correctly
  - uint16 values > 32767 decoded correctly
  - exactly 42 values decoded from 84 data bytes

Run:  cd app && python3 -m unittest tests.test_sync_frame_extractor -v
"""
from __future__ import annotations

import struct
import unittest

from models.packet import PACKET_FIELDS, FIELD_SIGNED, FIELD_SCALE
from serial_io.packet_parser import (
    PacketParser,
    SyncFrameExtractor,
    HEADER_SIZE,
    PACKET_SIZE_BYTES,
    FRAME_TOTAL_SIZE,
    SYNC_HEADER,
    SYNC_FOOTER,
)


def build_data(seed: int = 1000) -> bytes:
    """Build 84 bytes of data: one 16-bit value per configured field."""
    chunks = []
    for i, (_name, signed, _scale) in enumerate(
        zip(PACKET_FIELDS, FIELD_SIGNED, FIELD_SCALE)
    ):
        raw = (i + seed) % 32000
        chunks.append(raw.to_bytes(2, "little", signed=signed))
    return b"".join(chunks)


def build_frame(seed: int = 1000) -> bytes:
    return SYNC_HEADER + build_data(seed) + SYNC_FOOTER


def build_frame_with(field_values) -> bytes:
    """Build a frame replacing specific field raw values.

    `field_values` is a dict of {field_name: raw_int}. Raw ints are packed
    using the field's configured signedness; all other fields use seed 1000.
    """
    data = build_data(1000)
    buf = bytearray(data)
    for name, raw in field_values.items():
        idx = PACKET_FIELDS.index(name)
        signed = FIELD_SIGNED[idx]
        buf[idx * 2:idx * 2 + 2] = raw.to_bytes(2, "little", signed=signed)
    return SYNC_HEADER + bytes(buf) + SYNC_FOOTER


class SyncFrameExtractorTest(unittest.TestCase):
    def test_valid_single_frame_accepted(self):
        p = PacketParser()
        pkts = p.feed(build_frame())
        self.assertEqual(len(pkts), 1)

    def test_exactly_42_values(self):
        p = PacketParser()
        pkts = p.feed(build_frame())
        self.assertEqual(len(pkts[-1].values), 42)

    def test_multiple_frames_in_one_read(self):
        p = PacketParser()
        pkts = p.feed(build_frame(1000) + build_frame(2000) + build_frame(3000))
        self.assertEqual(len(pkts), 3)

    def test_partial_frame_across_reads(self):
        p = PacketParser()
        frame = build_frame()
        got = []
        # Feed one byte at a time (maximum fragmentation).
        for b in frame:
            got += p.feed(bytes([b]))
        self.assertEqual(len(got), 1)

    def test_header_split_across_reads(self):
        p = PacketParser()
        frame = build_frame()
        # Split inside the header: 20 bytes, then a chunk that ends mid-header.
        pkts = p.feed(frame[:20])
        self.assertEqual(len(pkts), 0)
        pkts += p.feed(frame[20:24])
        pkts += p.feed(frame[24:])
        self.assertEqual(len(pkts), 1)

    def test_noise_before_header_ignored(self):
        p = PacketParser()
        noise = bytes([0x00, 0xFF, 0xAA, 0x12, 0x77, 0xAA, 0x11])
        pkts = p.feed(noise + build_frame())
        self.assertEqual(len(pkts), 1)

    def test_false_header_start_resyncs(self):
        # AA 55 but third byte isn't A5 -> discarded.
        p = PacketParser()
        noise = bytes([0xAA, 0x55, 0x00, 0xAA, 0x55, 0xA5])
        # The last three bytes ARE a valid header start; append a full
        # data+footer to form a complete frame.
        frame = bytearray(build_frame())
        data = bytes(frame[HEADER_SIZE:HEADER_SIZE + PACKET_SIZE_BYTES])
        footer = bytes(frame[HEADER_SIZE + PACKET_SIZE_BYTES:])
        pkts = p.feed(noise + data + footer)
        self.assertEqual(len(pkts), 1)

    def test_invalid_footer_frame_rejected(self):
        p = PacketParser()
        raw = bytearray(build_frame())
        raw[-1] = 0x00  # corrupt footer last byte
        pkts = p.feed(bytes(raw))
        self.assertEqual(len(pkts), 0)

    def test_invalid_footer_then_resync_to_next_frame(self):
        p = PacketParser()
        bad = bytearray(build_frame(1000))
        bad[-1] = 0x00
        good = build_frame(2000)
        pkts = p.feed(bytes(bad) + good)
        # The bad frame rejected; the following good frame is recovered.
        self.assertEqual(len(pkts), 1)
        self.assertAlmostEqual(pkts[0].values["Position1"], 2000.0 / 1000.0)

    def test_negative_int16_decoded_correctly(self):
        p = PacketParser()
        # Position1 is int16. Set to -1234 -> -1.234 after /1000.
        pkts = p.feed(build_frame_with({"Position1": -1234}))
        self.assertAlmostEqual(pkts[0].values["Position1"], -1.234, places=6)

    def test_uint16_above_32767_decoded_correctly(self):
        p = PacketParser()
        # Pwm1 is uint16. 60000 is > 32767, must NOT be interpreted as signed.
        pkts = p.feed(build_frame_with({"Pwm1": 60000}))
        self.assertAlmostEqual(pkts[0].values["Pwm1"], 60000.0 / 100.0, places=6)

    def test_int16_field_correctly_signed(self):
        p = PacketParser()
        # Bus_Current is int16; a raw value with the sign bit set (e.g. 0xFFFF)
        # must decode as -1 -> -0.01 after /100.
        pkts = p.feed(build_frame_with({"Bus_Current": -1}))
        self.assertAlmostEqual(pkts[0].values["Bus_Current"], -0.01, places=6)

    def test_scaling_factors_applied(self):
        p = PacketParser()
        pkts = p.feed(build_frame(1000))
        v = pkts[0].values
        # Position1 raw = (0+1000) = 1000 -> /1000 = 1.0
        self.assertAlmostEqual(v["Position1"], 1.0, places=6)
        # Pwm1 raw = (20+1000) = 1020 -> /100 = 10.2
        self.assertAlmostEqual(v["Pwm1"], 10.2, places=6)
        # OD_DATA1 raw = (30+1000) = 1030 -> /1000 = 1.03
        self.assertAlmostEqual(v["OD_DATA1"], 1.03, places=6)
        # Board_Temp1 raw = (26+1000) = 1026 -> /100 = 10.26
        self.assertAlmostEqual(v["Board_Temp1"], 10.26, places=6)

    def test_all_fields_present(self):
        p = PacketParser()
        pkts = p.feed(build_frame())
        self.assertEqual(set(pkts[0].values.keys()), set(PACKET_FIELDS))

    def test_bad_length_data_rejected_as_malformed(self):
        # A frame extractor that returns a wrong-length frame should not be
        # decoded. Simulate via a subclass.
        class BadExtractor(SyncFrameExtractor):
            def feed(self, data):
                self._buffer.extend(data)
                if len(self._buffer) >= PACKET_SIZE_BYTES + 1:
                    out = bytes(self._buffer[:PACKET_SIZE_BYTES + 1])
                    del self._buffer[:PACKET_SIZE_BYTES + 1]
                    return [out]
                return []

        p = PacketParser(frame_extractor=BadExtractor())
        p.feed(bytes(1) * (PACKET_SIZE_BYTES + 1))
        self.assertEqual(p.malformed_count, 1)

    def test_reset_clears_buffered_state(self):
        p = PacketParser()
        # Feed half a frame, then reset.
        half = build_frame()[:40]
        p.feed(half)
        p.reset()
        # After reset, feeding a full frame should yield exactly one packet.
        pkts = p.feed(build_frame())
        self.assertEqual(len(pkts), 1)


if __name__ == "__main__":
    unittest.main()
