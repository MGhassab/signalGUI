"""Packet parsing: turns a raw byte stream into `Packet` objects.

Two concerns are deliberately kept separate:

1. Framing — deciding where one packet ends and the next begins inside a
   continuous byte stream.  See `SyncFrameExtractor`.
2. Decoding — turning 84 bytes into 42 named float values, with per-field
   signedness and protocol scaling.  See `PacketDecoder`.

Wire format (90 bytes per frame):
  Header (3 bytes): 0xAA 0x55 0xA5
  Data   (84 bytes): 42 × 16-bit LE fields
  Footer (3 bytes): 0x5A 0xAA 0x55
"""
from __future__ import annotations

import struct
from abc import ABC, abstractmethod
from typing import Dict, List, Optional

from models.packet import (
    Packet, PACKET_FIELDS, PACKET_SIZE_BYTES, FIELD_SIGNED, FIELD_SCALE,
)

BYTES_PER_FIELD = 2

# -- Frame extractor (framing / sync) -----------------------------------------

SYNC_HEADER = bytes([0xAA, 0x55, 0xA5])
SYNC_FOOTER = bytes([0x5A, 0xAA, 0x55])
HEADER_SIZE = 3
FOOTER_SIZE = 3
FRAME_TOTAL_SIZE = HEADER_SIZE + PACKET_SIZE_BYTES + FOOTER_SIZE  # 90


class FrameExtractor(ABC):
    """Strategy for slicing a raw byte stream into individual packet
    frames.  Isolated so the framing protocol can be changed without
    touching decoding or the rest of the app.
    """

    @abstractmethod
    def feed(self, data: bytes) -> List[bytes]:
        """Feed newly-received bytes in.  Returns zero or more complete
        data frames (each exactly PACKET_SIZE_BYTES long).  Any
        leftover/partial bytes are buffered internally for the next call.
        """

    @abstractmethod
    def reset(self) -> None:
        """Discard any buffered partial-frame bytes."""


class SyncFrameExtractor(FrameExtractor):
    """Robust stream parser with header/footer synchronization.

    Strategy: keep the incoming stream in a buffer and repeatedly try to
    align the buffer so that a valid 90-byte frame sits at its head.
    One byte is discarded at a time until either a full valid frame is
    found (emitted) or there are not enough bytes to complete a frame yet
    (in which case we wait for more bytes).

    Handles:
      - partial reads (buffered between feed() calls)
      - multiple frames in a single read
      - noise / random bytes before the header
      - header split across multiple reads
      - incomplete frames (not enough data yet)
      - invalid footer (frame rejected, resync)
      - back-to-back frames
    """

    def __init__(self) -> None:
        self._buffer = bytearray()
        self.reset()

    def reset(self) -> None:
        self._buffer.clear()

    def feed(self, data: bytes) -> List[bytes]:
        self._buffer.extend(data)
        frames: List[bytes] = []
        while True:
            frame = self._try_extract_one()
            if frame is None:
                break  # buffer too short to complete another frame
            frames.append(frame)
        return frames

    def _try_extract_one(self) -> Optional[bytes]:
        """Align the buffer to a valid frame and return its 84 data bytes,
        or None if the buffer is too short to complete a frame right now.
        Bytes that cannot begin a valid frame are discarded."""
        while True:
            if len(self._buffer) < FRAME_TOTAL_SIZE:
                return None  # not enough bytes for even one full frame

            if (self._buffer[0], self._buffer[1], self._buffer[2]) \
                    != (0xAA, 0x55, 0xA5):
                # Not a header at the buffer head: drop one byte and rescan.
                del self._buffer[:1]
                continue

            # Header matches at head.  Check the footer.
            footer = bytes(
                self._buffer[HEADER_SIZE + PACKET_SIZE_BYTES:FRAME_TOTAL_SIZE]
            )
            if footer == SYNC_FOOTER:
                data = bytes(self._buffer[HEADER_SIZE:HEADER_SIZE + PACKET_SIZE_BYTES])
                del self._buffer[:FRAME_TOTAL_SIZE]
                return data

            # Header matched but footer invalid: this is not a valid frame.
            # Drop just the first header byte and rescan — the frame is
            # rejected, and the remaining bytes might contain another header.
            del self._buffer[:1]


# -- Packet decoder (endianness / signedness / scaling) -----------------------

class PacketDecoder:
    """Decodes one raw 84-byte data frame into a dict of named float
    values, applying per-field signedness interpretation and protocol
    scaling (raw / divisor)."""

    def __init__(self) -> None:
        self._structs = [
            struct.Struct("<" + ("h" if signed else "H"))
            for signed in FIELD_SIGNED
        ]
        self._scales = list(FIELD_SCALE)

    def decode(self, frame: bytes) -> Dict[str, float]:
        if len(frame) != PACKET_SIZE_BYTES:
            raise ValueError(
                f"Frame is {len(frame)} bytes, expected {PACKET_SIZE_BYTES}"
            )
        values: Dict[str, float] = {}
        for i, name in enumerate(PACKET_FIELDS):
            raw = self._structs[i].unpack_from(frame, i * BYTES_PER_FIELD)[0]
            values[name] = raw / self._scales[i]
        return values


# -- Top-level parser ---------------------------------------------------------

class PacketParser:
    """Top-level parser: raw bytes in, `Packet` objects out.  Combines a
    `FrameExtractor` (framing/sync) with a `PacketDecoder` (decode +
    scaling)."""

    def __init__(
        self,
        frame_extractor: Optional[FrameExtractor] = None,
    ) -> None:
        self._decoder = PacketDecoder()
        self._framer = frame_extractor or SyncFrameExtractor()
        self._seq = 0
        self._malformed_count = 0

    @property
    def malformed_count(self) -> int:
        return self._malformed_count

    def feed(self, data: bytes) -> List[Packet]:
        """Feed newly-received bytes; returns any complete `Packet`s."""
        packets: List[Packet] = []
        for frame in self._framer.feed(data):
            try:
                values = self._decoder.decode(frame)
            except ValueError:
                self._malformed_count += 1
                continue
            packets.append(Packet(values=values, seq=self._seq))
            self._seq += 1
        return packets

    def reset(self) -> None:
        self._framer.reset()
