# Embedded Device Monitor

Modular PySide6 desktop app for monitoring/processing a fixed-format
42-field serial packet stream from an embedded device.

## Run it

```bash
pip install -r requirements.txt
cd app
python main.py
```

## GUI structure

The main window is an application controller/panel manager, not a graph
panel:

- **Main window** shows the **Panel Manager** list (every created panel +
  status) with New/Show/Hide/Rename/Delete controls, plus menus, a toolbar,
  and the serial status bar. It owns the single serial connection.
- **Menus**: `File` (save/load/reset configuration, clear the active
  panel's graph, exit), `Window` (New Panel, a live list of panels, Hide
  Panel, Delete Panel), `Settings` (Serial Configuration..., Connect/
  Disconnect), `Help`.
- **Panels are independent child tool windows**: open one via `Window >
  New Panel` (toolbar or Panel Manager). Each is a real OS window that can
  be moved, resized, stacked and overlapped freely. Pressing its **X (or
  Hide) only hides it** - it stays registered with all config/data intact
  and can be reopened from the Panel Manager. **Delete** really removes it.
  Closing/hiding a panel never closes the Main Window.
- **Per-panel playback**: each panel has its own Play/Pause toggle plus
  Previous/Next/Latest navigation. Pause freezes that panel's displayed
  view (data acquisition and history continue); you can step backward /
  forward through the retained history or jump back to live. Pausing one
  panel never affects another.
- **Left data table**: DATA1-DATA8 (raw, display-only, always on top) then
  the panel's enabled signal outputs. DATA1-8 are never user-selectable
  signals or criteria sources - they only appear here.
- **Display settings**: `dY` (per signal) and `dT` (per panel, in the
  panel control row) are axis-tick steps only - they change neither signal
  values nor data acquisition. They are applied when signal/panel
  configuration is applied; the first manual mouse-wheel/pan on an axis
  releases the fixed spacing back to pyqtgraph's adaptive ticks (so manual
  zoom/pan stays fast and is never overwritten by live data).
- **Serial configuration** lives in its own dialog (`Settings > Serial
  Configuration...`); saved settings apply on the next Connect. Connection
  status shows in the status bar.
- **Inside each panel** there are two tabs: *Plot* (Name/Value table +
  graph) and *Signal Configuration* (that panel's signal table). Each panel
  owns its own processor state, so editing one panel's signals never
  affects another panel.
- **Packets** are fanned out to every open panel; each panel computes only
  its own enabled signals on a shared, throttled (50 ms) plot-refresh timer.
- **One global acquisition timeline**: every packet receives a single
  timestamp from the centralized `AcquisitionManager` before it is
  distributed, so all panels/signals share the same X-axis time reference.
  A new session (time resets to 0) starts on each serial Connect; creating
  a panel/signal later never re-zeros time, and new panels backfill the
  retained global history so side-by-side panels are comparable.

## Project layout

```
app/
├── main.py
├── acquisition/
│   └── manager.py          # centralized global acquisition timeline + history
├── gui/
│   ├── main_window.py        # controller: menus, serial, panel registry, packet fan-out
│   ├── panel_manager.py      # Main-Window list of panels (new/show/hide/rename/delete)
│   ├── panel_window.py       # a graph panel as an independent child tool window
│   ├── graph_panel.py        # one analysis panel: Plot + Signal Configuration tabs
│   ├── playback_controller.py# per-panel Play/Pause + history navigation state
│   ├── serial_config_dialog.py  # port/baud settings dialog (separate from graph UI)
│   ├── live_value_table.py   # DATA1-8 + panel signal outputs (Name/Value readout)
│   ├── signal_panel.py       # per-panel signal list table + add/edit/delete/enable
│   ├── signal_dialog.py      # add/edit dialog (Raw/Computational signals)
│   ├── criteria_dialog.py    # criteria (derived metric) configuration dialog
│   └── plot_widget.py        # one graph per panel, shared time axis, per-signal Y-axis
├── serial_io/
│   ├── serial_manager.py  # QThread-based serial I/O, never blocks the GUI
│   └── packet_parser.py   # framing (isolated) + endianness/sign decoding
├── processing/
│   ├── base_processor.py
│   ├── raw_processor.py            # Data Type 1
│   ├── computational_processor.py  # Data Type 2 (integral/derivative)
│   ├── criteria/                   # derived control-performance metrics
│   │   ├── engine.py               # step detection + per-step metric computation
│   │   ├── response.py             # StepResponse window model
│   │   └── calculators/            # one class per criterion (registry)
│   ├── ring_buffer.py              # bounded plot history
│   └── signal_manager.py           # packet -> processors/criteria engines -> plot buffers
├── models/
│   ├── packet.py          # the ONE place the 42-field layout is defined
│   ├── signal_config.py   # the 3 signal-kind dataclasses (+ criteria params)
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
   code): trapezoidal integration for Integral; Derivative is a real-time
   Savitzky-Golay-style differentiator - a least-squares quadratic is fit
   to the last W `(measured_time, value)` samples and the slope is reported
   at the window CENTER (phase/amplitude-accurate, robust to the integer
   quantization of the device stream and to irregular arrival times).
   `x_degree` reapplies the operation that many times; derivative stages
   cascade, with window sizes 5, 7, 9, ... growing per degree. Derivative
   output samples are stamped with their center time, so the trace stays
   aligned on the global X axis at the cost of a fixed group delay
   (~0.1 s for a 1st derivative, ~0.25 s for a 2nd at 20 Hz - the newest
   samples simply aren't drawn yet). Insufficient-history / zero-`dt` cases
   emit no sample instead of NaN/crashing, so there are no startup spikes.

5. **Criteria signals are derived Source->Reference metrics.** A Criteria
   row compares one SOURCE (a configured signal or a raw channel) against
   a POSITION-4 reference channel (`position41..position44`, the only valid
   references) and reports one metric: steady-state error, settling time,
   rise/fall time, overshoot, or inverse response. On each reference step
   the engine (`processing/criteria/engine.py`) captures the response and
   computes the metric via a per-criterion calculator; the result is held
   between steps and plotted as a dashed derived series. Steady-state error
   is reported continuously as e(t) = reference - source. A criteria row
   only sees steps that occur after it is enabled.

6. **Criteria metrics update per reference step.** Settling/rise/fall
   times are measured from the start of each detected reference step. Step
   detection uses a configurable threshold (`step_threshold`, 0 = auto)
   plus plateau confirmation; the analysis window ends once the source has
   observably settled or the horizon (5 s) elapses. Add a new criterion by
   writing a `CriterionCalculator` subclass and registering it in
   `processing/criteria/calculators/__init__.py`.

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
- **New criterion**: write a `CriterionCalculator` subclass and register
  it in `processing/criteria/calculators/__init__.py`.
