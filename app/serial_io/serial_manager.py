"""Background serial I/O. Reception runs entirely inside a QThread so the
GUI thread never blocks on a serial read. The GUI only ever talks to
`SerialManager` through Qt signals/slots - it must never touch pyserial
or the packet parser directly (see gui/main_window.py).
"""
from __future__ import annotations

from typing import Optional

import serial
from PySide6.QtCore import QObject, QThread, Signal, Slot

from serial_io.packet_parser import PacketParser

READ_CHUNK_SIZE = 4096
READ_TIMEOUT_S = 0.1


class _SerialWorker(QObject):
    """Lives inside the worker QThread. Owns the actual serial.Serial
    instance and drives the packet parser for the current connection."""

    packetReceived = Signal(object)          # Packet
    connectionLost = Signal(str)             # error message
    errorOccurred = Signal(str)
    started_ok = Signal()

    def __init__(self, port: str, baudrate: int, parser: PacketParser):
        super().__init__()
        self._port_name = port
        self._baudrate = baudrate
        self._parser = parser
        self._serial: Optional[serial.Serial] = None
        self._running = False

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
        self.started_ok.emit()

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

            if data:
                for pkt in self._parser.feed(data):
                    self.packetReceived.emit(pkt)

        if self._serial is not None and self._serial.is_open:
            self._serial.close()

    @Slot()
    def stop(self) -> None:
        self._running = False


class SerialManager(QObject):
    """Public, GUI-facing API for serial connectivity.

    Owns a QThread + `_SerialWorker` pair. Reconnecting creates a fresh
    thread/worker each time, which is the simplest safe pattern for
    QThread lifecycle management.
    """

    packetReceived = Signal(object)   # Packet
    connected = Signal()
    disconnected = Signal(str)        # reason; "" if user-initiated
    errorOccurred = Signal(str)

    def __init__(self, parser: PacketParser):
        super().__init__()
        self._parser = parser
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
        self._worker = _SerialWorker(port, baudrate, self._parser)
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.packetReceived.connect(self.packetReceived)
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
