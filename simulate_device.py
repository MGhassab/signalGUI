"""
simulate_device.py
-------------------
Simulates an embedded device that streams sensor/actuator data over a
serial (COM) port, so you can test your PC-side plotting/GUI code without
having the physical hardware connected.

WHAT IT DOES
    - Opens a serial port at 115200 baud (default: COM8)
    - Builds a fixed-size, FRAMED binary packet:
          [3-byte Header] + [84-byte Data (42 fields)] + [3-byte Footer]
      matching the new microcontroller UART protocol exactly.
    - Fills the 42 data fields with signal-like waveforms (sine and
      triangle waves), each bounded to a physically plausible range per
      field group, so it behaves like a real signal instead of noise.
    - Sends one 90-byte frame 20 times per second (20 Hz) by default.

FRAME FORMAT
    Header (3 bytes):  0xAA 0x55 0xA5
    Data   (84 bytes): 42 fields, 2 bytes each, little-endian,
                       mixed signed/unsigned (see FIELD groups below)
    Footer (3 bytes):  0x5A 0xAA 0x55
    Total frame size = 3 + 84 + 3 = 90 bytes

    No checksum/CRC is included, per the protocol spec.

DATA FIELD GROUPS (in exact wire order)
    Position1-4     int16 signed    raw = physical * 1000
    Feedback1-4     int16 signed    raw = physical * 1000
    Pot_Value1-4    int16 signed    raw = physical * 1000
    Command1-4      int16 signed    raw = physical * 1000
    Current1-4      int16 signed    raw = physical * 1000
    Pwm1-4          uint16 unsigned raw = physical * 100
    Bus_Voltage     uint16 unsigned raw = physical * 1000
    Bus_Current     int16 signed    raw = physical * 100
    Board_Temp1-4   uint16 unsigned raw = physical * 100
    OD_DATA1-12     uint16 unsigned raw = physical * 1000

    (4+4+4+4+4+4+1+1+4+12 = 42 fields, 42*2 = 84 bytes)

HOW TO TEST WITHOUT REAL HARDWARE
    Windows:
        Install "com0com" (free virtual null-modem driver). It creates
        a linked pair of ports, e.g. COM1 <-> COM2. Run this script
        pointed at COM1, and point your existing plotting code at COM2.

    Linux / macOS:
        Use socat to create a virtual serial pair:
            socat -d -d pty,raw,echo=0,link=/tmp/ttyV0 pty,raw,echo=0,link=/tmp/ttyV1
        Then run this script with PORT = "/tmp/ttyV0" and point your
        plotting code at "/tmp/ttyV1".

REQUIREMENTS
    pip install pyserial
"""

import struct
import time
import math
import sys

import serial  # pip install pyserial

# --------------------------------------------------------------------------
# CONFIGURATION - edit these to match your setup
# --------------------------------------------------------------------------
PORT = "COM8"          # e.g. "COM1" on Windows, "/tmp/ttyV0" on Linux/Mac
BAUDRATE = 115200
SEND_RATE_HZ = 20       # send 20 frames per second, as requested
RUN_SECONDS = None      # None = run forever until Ctrl+C; or set e.g. 30 for 30s

# Optional: exercise the GUI's UART parser against partial/fragmented
# serial reads by splitting each frame into two ser.write() calls with a
# tiny delay in between. Off by default -- the default mode always sends
# one complete 90-byte frame per ser.write() call.
SPLIT_FRAME_TEST_MODE = False
SPLIT_FRAME_AT = 40          # byte offset (within the 90-byte frame) to split at
SPLIT_FRAME_DELAY_SEC = 0.002

# --------------------------------------------------------------------------
# FRAME FRAMING
# --------------------------------------------------------------------------
HEADER = bytes([0xAA, 0x55, 0xA5])
FOOTER = bytes([0x5A, 0xAA, 0x55])

# --------------------------------------------------------------------------
# FIELD ORDER / TYPES / SCALES
# --------------------------------------------------------------------------
# Each entry: (name, "signed" | "unsigned", scale)
# raw_value = physical_value * scale
# physical_value = raw_value / scale
FIELD_SPEC = (
    [(f"Position{i}", "signed", 1000) for i in range(1, 5)]
    + [(f"Feedback{i}", "signed", 1000) for i in range(1, 5)]
    + [(f"Pot_Value{i}", "signed", 1000) for i in range(1, 5)]
    + [(f"Command{i}", "signed", 1000) for i in range(1, 5)]
    + [(f"Current{i}", "signed", 1000) for i in range(1, 5)]
    + [(f"Pwm{i}", "unsigned", 100) for i in range(1, 5)]
    + [("Bus_Voltage", "unsigned", 1000)]
    + [("Bus_Current", "signed", 100)]
    + [(f"Board_Temp{i}", "unsigned", 100) for i in range(1, 5)]
    + [(f"OD_DATA{i}", "unsigned", 1000) for i in range(1, 13)]
)
assert len(FIELD_SPEC) == 42, "field count changed, check FIELD_SPEC above"

FIELD_ORDER = [name for name, _, _ in FIELD_SPEC]
FIELD_KIND = {name: kind for name, kind, _ in FIELD_SPEC}
FIELD_SCALE = {name: scale for name, _, scale in FIELD_SPEC}

# struct format: '<' little-endian, one char per field ('h' signed, 'H' unsigned)
PACKET_FORMAT = "<" + "".join("h" if kind == "signed" else "H" for _, kind, _ in FIELD_SPEC)
PACKET_SIZE = struct.calcsize(PACKET_FORMAT)  # 84 bytes
assert PACKET_SIZE == 84, f"data section must be 84 bytes, got {PACKET_SIZE}"

FRAME_SIZE = len(HEADER) + PACKET_SIZE + len(FOOTER)  # 90 bytes
assert FRAME_SIZE == 90, f"frame must be 90 bytes, got {FRAME_SIZE}"


def clamp_int16(value):
    """Keep a value inside the signed 16-bit range so struct.pack doesn't blow up."""
    return max(-32768, min(32767, int(round(value))))


def clamp_uint16(value):
    """Keep a value inside the unsigned 16-bit range so struct.pack doesn't blow up."""
    return max(0, min(65535, int(round(value))))


# --------------------------------------------------------------------------
# WAVEFORM GENERATION
# --------------------------------------------------------------------------
def unit_sine(t, freq, phase):
    """Sine wave in the range [-1, 1]."""
    return math.sin(2 * math.pi * freq * t + phase)


def unit_triangle(t, freq, phase):
    """
    Triangle wave in the range [-1, 1].
    Standard triangle formula (period = 1/freq), phase-shifted.
    """
    x = freq * t + phase / (2 * math.pi)
    return 2 * abs(2 * (x - math.floor(x + 0.5))) - 1


def sine_wave(t, freq, phase):
    """Sine wave, normalized to the range [0, 100]. Kept for reference/back-compat."""
    return 50 + 50 * unit_sine(t, freq, phase)


def triangle_wave(t, freq, phase):
    """Triangle wave, normalized to the range [0, 100]. Kept for reference/back-compat."""
    return 50 + 50 * unit_triangle(t, freq, phase)


def wave_value(shape, t, freq, phase, offset, amplitude):
    """
    Generic waveform generator: returns offset + amplitude * unit_wave(t),
    where unit_wave is a sine or triangle wave in [-1, 1]. This lets each
    field group use a physically sensible offset/amplitude instead of the
    fixed [0, 100] range used by the old simulator.
    """
    if shape == "sine":
        unit = unit_sine(t, freq, phase)
    elif shape == "triangle":
        unit = unit_triangle(t, freq, phase)
    else:
        raise ValueError(f"unknown shape: {shape}")
    return offset + amplitude * unit


def _build_field_params():
    """
    Assign a (frequency, phase, shape, offset, amplitude) to every field in
    FIELD_ORDER. Values are chosen so that:
      - each channel is visually distinguishable on a plot
      - the resulting raw (scaled) integers stay comfortably within the
        signed/unsigned int16 range for that field (see module docstring)
    """
    params = {}

    # Position1-4: sine, distinct phase/frequency per axis
    for i in range(1, 5):
        params[f"Position{i}"] = (0.05 * i, i * (math.pi / 4), "sine", 0.0, 10.0)

    # Feedback1-4: triangle (tracks position-like signal but visually distinct)
    for i in range(1, 5):
        params[f"Feedback{i}"] = (0.05 * i, i * (math.pi / 4) + 0.3, "triangle", 0.0, 8.0)

    # Pot_Value1-4: sine, positive-ish potentiometer reading
    for i in range(1, 5):
        params[f"Pot_Value{i}"] = (0.08 + 0.01 * i, i * 0.5, "sine", 5.0, 5.0)

    # Command1-4: triangle command signal
    for i in range(1, 5):
        params[f"Command{i}"] = (0.07 + 0.015 * i, i * 0.4, "triangle", 0.0, 6.0)

    # Current1-4: triangle, can swing negative
    for i in range(1, 5):
        params[f"Current{i}"] = (0.1 + 0.02 * i, i * 0.6, "triangle", 0.0, 5.0)

    # Pwm1-4: sine duty-cycle-like signal, clamped to [0, 100] by clamp_uint16 downstream
    for i in range(1, 5):
        params[f"Pwm{i}"] = (0.1 + 0.01 * i, i * 0.5, "sine", 50.0, 50.0)

    # Bus_Voltage: relatively stable, small ripple around a nominal bus voltage
    params["Bus_Voltage"] = (0.02, 0.0, "sine", 24.0, 0.5)

    # Bus_Current: slowly varying
    params["Bus_Current"] = (0.015, 0.0, "sine", 0.0, 10.0)

    # Board_Temp1-4: slow, triangle "heating/cooling" style signal
    for i in range(1, 5):
        params[f"Board_Temp{i}"] = (0.02 + 0.005 * i, i * 0.3, "triangle", 40.0, 15.0)

    # OD_DATA1-12: alternate sine/triangle
    for i in range(1, 13):
        shape = "sine" if i % 2 == 1 else "triangle"
        params[f"OD_DATA{i}"] = (0.04 * i, i * 0.2, shape, 5.0, 5.0)

    return params


FIELD_PARAMS = _build_field_params()


def generate_values(t):
    """
    Build one dict of {field_name: physical_value} for time t (seconds),
    using the waveform assigned to each field in FIELD_PARAMS.
    """
    values = {}
    for name, (freq, phase, shape, offset, amplitude) in FIELD_PARAMS.items():
        values[name] = wave_value(shape, t, freq, phase, offset, amplitude)
    return values


def build_packet(values):
    """
    Pack the values dict into the 84-byte data section, in FIELD_ORDER,
    applying each field's scale and clamping to its signed/unsigned int16
    range.
    """
    raw = []
    for name in FIELD_ORDER:
        scaled = values[name] * FIELD_SCALE[name]
        if FIELD_KIND[name] == "signed":
            raw.append(clamp_int16(scaled))
        else:
            raw.append(clamp_uint16(scaled))
    data = struct.pack(PACKET_FORMAT, *raw)
    assert len(data) == 84, f"data section must be 84 bytes, got {len(data)}"
    return data


def build_frame(values):
    """
    Build the full 90-byte frame: Header + 84-byte data + Footer.
    """
    data = build_packet(values)
    frame = HEADER + data + FOOTER
    assert len(frame) == 90, f"frame must be 90 bytes, got {len(frame)}"
    assert frame[:3] == HEADER
    assert frame[-3:] == FOOTER
    return frame


def decode_packet(data):
    """
    Inverse of build_packet: unpack the 84-byte data section back into a
    dict of {field_name: physical_value}. Used only for the self-test.
    """
    raw = struct.unpack(PACKET_FORMAT, data)
    return {name: raw[i] / FIELD_SCALE[name] for i, name in enumerate(FIELD_ORDER)}


def self_test():
    """
    Build one frame at t=0 and verify:
      - field count / data size / frame size
      - header and footer bytes
      - signed fields round-trip through decode without being
        misinterpreted as unsigned (and vice versa)
      - decoded physical values match the originally generated values,
        within the rounding error introduced by the field's scale factor
    Raises AssertionError on any failure. Returns True on success.
    """
    assert len(FIELD_ORDER) == 42, f"expected 42 fields, got {len(FIELD_ORDER)}"

    values = generate_values(0.0)
    frame = build_frame(values)

    assert len(frame) == 90, f"expected 90-byte frame, got {len(frame)}"
    data = frame[3:-3]
    assert len(data) == 84, f"expected 84-byte data section, got {len(data)}"
    assert frame[:3] == HEADER, "header mismatch"
    assert frame[-3:] == FOOTER, "footer mismatch"

    decoded = decode_packet(data)
    for name in FIELD_ORDER:
        scale = FIELD_SCALE[name]
        tolerance = 1.0 / scale  # max rounding error introduced by int() truncation/round
        diff = abs(decoded[name] - values[name])
        assert diff <= tolerance + 1e-9, (
            f"{name}: decoded {decoded[name]} does not match generated "
            f"{values[name]} within tolerance {tolerance} (diff={diff})"
        )

    # Spot-check that unsigned fields are not corrupted by sign extension:
    # e.g. a Pwm/Bus_Voltage/Board_Temp/OD_DATA raw value above 32767 (if it
    # ever occurred) must decode as a large positive number, not negative.
    for name in FIELD_ORDER:
        if FIELD_KIND[name] == "unsigned":
            idx = FIELD_ORDER.index(name)
            raw_val = struct.unpack_from("<H", data, idx * 2)[0]
            assert raw_val >= 0, f"{name} unsigned field decoded as negative raw value"

    return True


def main():
    # Run the self-test once before opening the serial port so protocol
    # bugs are caught immediately instead of after hardware is involved.
    self_test()
    print("Self-test passed: 42 fields, 84-byte data section, 90-byte frame, "
          "header/footer OK, signed/unsigned round-trip OK.")

    print(f"Opening {PORT} at {BAUDRATE} baud...")
    try:
        ser = serial.Serial(PORT, BAUDRATE, timeout=1)
    except serial.SerialException as e:
        print(f"Could not open {PORT}: {e}")
        print("Check the NOTE at the top of this file about virtual serial "
              "ports if you don't have real hardware attached.")
        sys.exit(1)

    period = 1.0 / SEND_RATE_HZ
    print(f"Sending {FRAME_SIZE}-byte frames ({len(FIELD_ORDER)} fields, "
          f"{PACKET_SIZE}-byte data section) at {SEND_RATE_HZ} Hz. "
          f"Press Ctrl+C to stop.")
    if SPLIT_FRAME_TEST_MODE:
        print(f"SPLIT_FRAME_TEST_MODE enabled: each frame will be split at "
              f"byte {SPLIT_FRAME_AT} across two ser.write() calls.")

    start = time.monotonic()
    next_send = start
    frame_count = 0
    try:
        while True:
            now = time.monotonic()
            t = now - start

            if RUN_SECONDS is not None and t >= RUN_SECONDS:
                break

            values = generate_values(t)
            frame = build_frame(values)

            if SPLIT_FRAME_TEST_MODE:
                ser.write(frame[:SPLIT_FRAME_AT])
                time.sleep(SPLIT_FRAME_DELAY_SEC)
                ser.write(frame[SPLIT_FRAME_AT:])
            else:
                ser.write(frame)

            frame_count += 1

            if frame_count % SEND_RATE_HZ == 0:
                print(f"[{t:6.1f}s] sent {frame_count} frames "
                      f"(last Position1={values['Position1']:.3f})")

            next_send += period
            sleep_time = next_send - time.monotonic()
            if sleep_time > 0:
                time.sleep(sleep_time)
            else:
                # we're behind schedule (e.g. slow port); resync instead of
                # trying to "catch up" with zero-delay bursts
                next_send = time.monotonic()

    except KeyboardInterrupt:
        print("\nStopped by user.")
    finally:
        ser.close()
        print(f"Total frames sent: {frame_count}")


if __name__ == "__main__":
    main()

# --------------------------------------------------------------------------
# NOTE ON FRAMING
# --------------------------------------------------------------------------
# Every frame carries a fixed 3-byte header (0xAA 0x55 0xA5) and a fixed
# 3-byte footer (0x5A 0xAA 0x55) around the 84-byte data section, so the
# receiver can resynchronize on the header/footer bytes even if it connects
# mid-stream or a byte gets dropped -- as long as it scans for the marker
# sequence rather than assuming byte 0 of the stream is byte 0 of a frame.
#
# No checksum/CRC is included, per the protocol as specified. If the real
# firmware ever adds one, this simulator and the GUI parser will both need
# to be updated to match.