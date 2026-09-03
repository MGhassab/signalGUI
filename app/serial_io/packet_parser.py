"""Packet parsing: turns a raw byte stream into `Packet` objects.

Two concerns are deliberately kept separate:

1. Framing - deciding where one packet ends and the next begins inside a
   continuous byte stream that may deliver partial packets, multiple
   packets per read, or garbage bytes. See `FrameExtractor`.
2. Decoding - turning 84 bytes into 42 named integer values, according to
   configurable endianness/signedness. See `PacketDecoder`.

No packet header, footer, sync word or checksum has been specified for
this protocol yet. Until that's specified, `NullFrameExtractor` assumes
the stream is a back-to-back sequence of fixed-size 84-byte packets with
NO framing markers at all - it just slices the buffer into
PACKET_SIZE_BYTES chunks as they become available. This is intentionally
the simplest possible strategy, so it is obviously a placeholder and not
a guess at a real protocol.

When the real framing protocol is defined (e.g. a sync word and/or a
trailing checksum), implement a new `FrameExtractor` subclass and pass it
into `PacketParser(frame_extractor=...)` - nothing else in the app needs
to change.
"""
from __future__ import annotations

import struct
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict, List, Literal, Optional

from models.packet import Packet, PACKET_FIELDS, PACKET_SIZE_BYTES

ByteOrder = Literal["little", "big"]


@dataclass
class PacketFormat:
    """Centralized, editable interpretation settings for the wire format.

    Change these here - nothing else in the app hard-codes endianness or
    signedness. Currently applies uniformly to all 42 fields; if a future
    protocol needs per-field overrides, extend this class rather than
    scattering struct format strings elsewhere.
    """
    byte_order: ByteOrder = "little"
    signed: bool = False

    @property
    def struct_prefix(self) -> str:
        return "<" if self.byte_order == "little" else ">"

    @property
    def struct_code(self) -> str:
        return "h" if self.signed else "H"


class FrameExtractor(ABC):
    """Strategy for slicing a raw byte stream into individual packet
    frames. Isolated so the real framing protocol (sync bytes / checksum /
    length field) can be dropped in later without touching decoding or
    the rest of the app.
    """

    @abstractmethod
    def feed(self, data: bytes) -> List[bytes]:
        """Feed newly-received bytes in. Returns zero or more complete
        frames (each exactly PACKET_SIZE_BYTES long). Any leftover/partial
        bytes are buffered internally for the next call - callers must
        handle partial packets and multiple packets per read correctly,
        which this buffering guarantees.
        """

    @abstractmethod
    def reset(self) -> None:
        """Discard any buffered partial-frame bytes (e.g. after a
        reconnect, to avoid stitching bytes from two different sessions
        into one bogus frame)."""


class NullFrameExtractor(FrameExtractor):
    """TODO: placeholder framing strategy.

    Assumes packets arrive back-to-back with no sync word, length field or
    checksum, so it simply groups the accumulated byte stream into
    PACKET_SIZE_BYTES chunks. If the serial link ever loses byte
    synchronization (e.g. a byte is dropped or corrupted), this strategy
    CANNOT detect or recover from it - all fields will appear shifted
    until the connection is reset. Replace this with a real
    `FrameExtractor` as soon as a sync word / checksum is defined.
    """

    def __init__(self) -> None:
        self._buffer = bytearray()

    def feed(self, data: bytes) -> List[bytes]:
        self._buffer.extend(data)
        frames: List[bytes] = []
        while len(self._buffer) >= PACKET_SIZE_BYTES:
            frames.append(bytes(self._buffer[:PACKET_SIZE_BYTES]))
            del self._buffer[:PACKET_SIZE_BYTES]
        return frames

    def reset(self) -> None:
        self._buffer.clear()


class PacketDecoder:
    """Decodes one raw 84-byte frame into a dict of named field values,
    according to a `PacketFormat`."""

    def __init__(self, fmt: PacketFormat):
        self.fmt = fmt
        self._struct = struct.Struct(
            f"{fmt.struct_prefix}{len(PACKET_FIELDS)}{fmt.struct_code}"
        )
        assert self._struct.size == PACKET_SIZE_BYTES

    def decode(self, frame: bytes) -> Dict[str, int]:
        if len(frame) != PACKET_SIZE_BYTES:
            raise ValueError(
                f"Frame is {len(frame)} bytes, expected {PACKET_SIZE_BYTES}"
            )
        values = self._struct.unpack(frame)
        return dict(zip(PACKET_FIELDS, values))


class PacketParser:
    """Top-level parser: raw bytes in, `Packet` objects out. Combines a
    `FrameExtractor` (framing/sync) with a `PacketDecoder`
    (endianness/signedness) - see module docstring for why these are
    separate.
    """

    def __init__(
        self,
        fmt: Optional[PacketFormat] = None,
        frame_extractor: Optional[FrameExtractor] = None,
    ) -> None:
        self.fmt = fmt or PacketFormat()
        self._decoder = PacketDecoder(self.fmt)
        self._framer = frame_extractor or NullFrameExtractor()
        self._seq = 0
        self._malformed_count = 0

    @property
    def malformed_count(self) -> int:
        return self._malformed_count

    def feed(self, data: bytes) -> List[Packet]:
        """Feed newly-received bytes; returns any complete `Packet`s.
        Correctly handles partial packets (buffered internally) and
        multiple packets arriving in a single serial read."""
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
