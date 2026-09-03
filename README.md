# Embedded Device Monitor

Modular PySide6 desktop app for monitoring/processing a fixed-format
42-field serial packet stream from an embedded device.

## Run it

```bash
pip install -r requirements.txt
cd app
python main.py
```

## Project layout

```
app/
├── main.py
├── gui/
│   ├── main_window.py     # wires everything together; owns no serial/parsing logic
│   ├── serial_panel.py    # port/baud/connect/disconnect/status
│   ├── signal_panel.py    # signal list table + add/edit/delete/enable
│   ├── signal_dialog.py   # add/edit dialog, form adapts to signal type
│   ├── data_table.py      # Data1-8 live values + renameable display names
│   └── plot_widget.py     # ONE graph, shared time axis, per-signal Y-axis
├── serial_io/
│   ├── serial_manager.py  # QThread-based serial I/O, never blocks the GUI
│   └── packet_parser.py   # framing (isolated) + endianness/sign decoding
├── processing/
│   ├── base_processor.py
│   ├── raw_processor.py            # Data Type 1
│   ├── computational_processor.py  # Data Type 2 (integral/derivative)
│   ├── criteria_processor.py       # Data Type 3 (TODO algorithm)
│   ├── ring_buffer.py              # bounded plot history
│   └── signal_manager.py           # packet -> processors -> plot buffers
├── models/
│   ├── packet.py          # the ONE place the 42-field layout is defined
│   ├── signal_config.py   # the 3 signal-type dataclasses
│   └── app_config.py
└── config/
    └── config_manager.py  # JSON save/load/reset
```

One deliberate naming deviation from the originally suggested tree:
the serial package is called `serial_io`, not `serial` - naming it
`serial` would shadow the `pyserial` library's own `serial` module from
inside the app.

## Design decisions you should double-check

1. **Packet framing is a placeholder** (`serial_io/packet_parser.py`,
   `NullFrameExtractor`). Since no header/sync-word/checksum was
   specified, it assumes packets arrive back-to-back with nothing
   between them, and just slices the byte stream into 84-byte chunks.
   **This cannot detect or recover from a single dropped/corrupted byte**
   - if that happens, every field will appear shifted until you
   reconnect. As soon as real framing is defined, implement a new
   `FrameExtractor` subclass and pass it into `PacketParser(...)`;
   nothing else changes.

2. **Endianness/signedness** live in one `PacketFormat` dataclass
   (`byte_order`, `signed`), applied to all 42 fields uniformly. Change
   it in `gui/main_window.py` (`self._packet_format = PacketFormat(...)`).

3. **`dT` is per-signal, not the plot's timebase.** Each signal's `dT` is
   the assumed Δt used inside *that signal's own* integral/derivative
   math. The graph's actual X axis uses real elapsed time from packet
   arrival. If you want a signal's math to instead use real arrival-time
   deltas, that's a small, explicit change to
   `processing/computational_processor.py` - not implemented since it
   wasn't requested.

4. **Integral/Derivative numerics** (not specified, so documented in
   code): trapezoidal integration, backward-difference derivative,
   `x_degree` reapplies the operation that many times. First-sample /
   zero-`dt` cases return `0.0` instead of NaN/crashing.

5. **Criteria-Based signal (Type 3) has NO invented algorithm.** The
   config (`ess_criteria_pct`, `delay_criteria_pct`), UI, and processor
   class all exist and are wired end-to-end, but
   `processing/criteria_processor.py::_evaluate_criteria()` is a
   clearly-marked `TODO` that currently just passes the gain/offset'd
   value straight through. Implement the real math there once it's
   specified - everything else (dialog, table, save/load, plotting)
   already works with this signal type.

## Testing without real hardware

The serial layer uses `serial.serial_for_url`, so you can point the
"Port" field at `loop://` to open a local loopback port (useful for UI
testing, though it only loops back what you write yourself - it won't
generate fake packets on its own). For realistic end-to-end testing
without hardware, create a virtual serial pair (e.g. `socat` on
Linux/macOS, or `com0com` on Windows) and write synthetic 84-byte frames
into one end while the app reads the other.

## Extending things later

- **New processing operation**: add an `_op_*` method to
  `ComputationalProcessor` and register it in `_OPERATIONS`.
- **Real packet framing**: implement a `FrameExtractor` subclass in
  `serial_io/packet_parser.py`.
- **Criteria algorithm**: implement `_evaluate_criteria` in
  `processing/criteria_processor.py`.
