"""Background serial I/O. Reception runs entirely inside a QThread so the
GUI thread never blocks on a serial read, and - crucially - packet
processing also happens there: the worker feeds decoded packets straight
into the shared `AcquisitionCore` instead of emitting one Qt signal per
packet. The GUI only reads snapshots at its own refresh cadence (see
`acquisition/core.py`), so a high incoming rate can never flood the GUI
event queue or cause missed/corrupted samples.
"""
from __future__ import annotations

import time
from typing import List, Optional

import serial
from PySide6.QtCore import QObject, QThread, Signal, Slot

from serial_io.packet_parser import PacketParser, FRAME_TOTAL_SIZE

READ_CHUNK_SIZE = 4096
READ_TIMEOUT_S = 0.1

# Serial framing is 8N1: 1 start + 8 data + 1 stop = 10 bits per byte on
# the wire. Used to reconstruct a per-frame arrival time from the byte
# count and the configured baud rate (see _SerialWorker.run).
BITS_PER_BYTE = 10


class _SerialWorker(QObject):
    """Lives inside the worker QThread. Owns the actual serial.Serial
    instance, drives the packet parser for the current connection, stamps
    per-frame times, and feeds the shared acquisition core."""

    connectionLost = Signal(str)             # error message
    errorOccurred = Signal(str)
    started_ok = Signal()

    def __init__(self, port: str, baudrate: int, parser: PacketParser, core):
        super().__init__()
        self._port_name = port
        self._baudrate = baudrate
        self._parser = parser
        self._core = core
        self._serial: Optional[serial.Serial] = None
        self._running = False
        self._last_stamp = 0.0

    @Slot()
    def run(self) -> None:
        try:
            self._serial = serial.serial_for_url(
                self._port_name,
                baudrate=self._baudrate,
                timeout=READ_TIMEOUT_S,
                do_not_open=False,
            )
        except serial.SerialException as exc:
            self.errorOccurred.emit(f"Could not open {self._port_name}: {exc}")
            return
        except ValueError as exc:
            self.errorOccurred.emit(f"Invalid port/baud rate: {exc}")
            return

        self._running = True
        self._parser.reset()
        self._last_stamp = 0.0
        # Start the new session HERE, before reading anything: because this
        # worker thread feeds the core directly, resetting it must be
        # ordered before the first packet of the new connection or those
        # samples would be wiped by the reset.
        if self._core is not None:
            self._core.begin_session()
        self.started_ok.emit()

        # Wire time for one complete frame, at the configured baud rate.
        frame_seconds = BITS_PER_BYTE * FRAME_TOTAL_SIZE / max(1, self._baudrate)

        while self._running:
            try:
                data = self._serial.read(READ_CHUNK_SIZE)
            except serial.SerialException as exc:
                self.connectionLost.emit(str(exc))
                break
            except OSError as exc:
                # e.g. device physically unplugged mid-session
                self.connectionLost.emit(str(exc))
                break

            if not data:
                continue

            # Timestamp at the moment the bytes were read: the last byte of
            # the last complete frame arrived at/just before `now`.
            now = time.monotonic()
            packets = self._parser.feed(data)
            if packets:
                self._stamp_packets(packets, now, frame_seconds)
                # Process in this (non-GUI) thread; the GUI only reads
                # snapshots, so it cannot miss or corrupt samples.
                self._core.on_packets(packets)

        if self._serial is not None and self._serial.is_open:
            self._serial.close()

    def _stamp_packets(self, packets: List, now: float,
                       frame_seconds: float) -> None:
        """Assign each decoded frame a per-frame arrival time.

        Frames completed within this read are spaced one frame-transmit
        time apart, ending at `now`. The running `_last_stamp` clamp keeps
        times strictly non-decreasing even if reads arrive irregularly or
        a frame completed from buffered leftover bytes.
        """
        k = len(packets)
        base = now - (k - 1) * frame_seconds
        for i, packet in enumerate(packets):
            t = base + i * frame_seconds
            if t <= self._last_stamp:
                t = self._last_stamp + 1e-9
            packet.arrival_time = t
            self._last_stamp = t

    @Slot()
    def stop(self) -> None:
        self._running = False


class SerialManager(QObject):
    """Public, GUI-facing API for serial connectivity.

    Owns a QThread + `_SerialWorker` pair. Reconnecting creates a fresh
    thread/worker each time, which is the simplest safe pattern for
    QThread lifecycle management.
    """

    connected = Signal()
    disconnected = Signal(str)        # reason; "" if user-initiated
    errorOccurred = Signal(str)

    def __init__(self, parser: PacketParser, core):
        super().__init__()
        self._parser = parser
        self._core = core
        self._thread: Optional[QThread] = None
        self._worker: Optional[_SerialWorker] = None
        self._is_connected = False

    @property
    def is_connected(self) -> bool:
        return self._is_connected

    def connect_to(self, port: str, baudrate: int) -> None:
        if self._is_connected or self._thread is not None:
            return
        self._thread = QThread()
        self._worker = _SerialWorker(port, baudrate, self._parser, self._core)
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.started_ok.connect(self._on_started_ok)
        self._worker.connectionLost.connect(self._on_connection_lost)
        self._worker.errorOccurred.connect(self._on_error)

        self._thread.start()

    def disconnect(self) -> None:
        if self._thread is None:
            return
        was_connected = self._is_connected
        if self._worker:
            self._worker.stop()
        self._thread.quit()
        self._thread.wait(2000)
        self._thread = None
        self._worker = None
        self._is_connected = False
        if was_connected:
            self.disconnected.emit("")

    @Slot()
    def _on_started_ok(self) -> None:
        self._is_connected = True
        self.connected.emit()

    @Slot(str)
    def _on_connection_lost(self, reason: str) -> None:
        self._is_connected = False
        self.disconnected.emit(reason or "Connection lost")
        if self._thread:
            self._thread.quit()
            self._thread = None
            self._worker = None

    @Slot(str)
    def _on_error(self, message: str) -> None:
        self._is_connected = False
        self.errorOccurred.emit(message)
        if self._thread:
            self._thread.quit()
            self._thread = None
            self._worker = None
