"""End-to-end regression test: signals added mid-session must stay
time-aligned on the shared global X axis.

Bug being guarded against: `GraphPanel.refresh_plot` used to slice every
signal by the SHORTEST signal's sample count. That is only correct when all
signals start at the same packet. When a signal is added while acquisition
is already running, its buffer starts later (it correctly begins at its
enable moment), and the min-count slice then truncated the OLDER signals to
an arbitrary early time - so traces appeared to "start/stop at different
time points" and were no longer aligned on the time axis.

The fix renders by GLOBAL TIME: live mode draws each signal's full buffer
(late-added signals start further right on the same axis); paused mode
slices every signal to the same wall-clock cut time. These tests drive the
real MainWindow (offscreen) by feeding simulator-style packets through the
real parser/fan-out path and assert on the actual plotted curve data.

Run:  cd app && ../.venv/bin/python -m unittest tests.test_plot_alignment -v
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest

from PySide6.QtWidgets import QApplication

from models.packet import Packet, PACKET_FIELDS
from models.signal_config import RawSignalConfig
from gui.main_window import MainWindow

DT = 0.05  # seconds between packets (20 Hz), matching the device simulator
ARRIVAL_BASE = 1000.0


def make_packet(i: int) -> Packet:
    """One simulator-style packet: arrival at ARRIVAL_BASE + i*DT."""
    values = {f: 1000 + (i % 20) * 3 for f in PACKET_FIELDS}
    return Packet(values=values, seq=i,
                  arrival_time=ARRIVAL_BASE + i * DT)


class PlotAlignmentTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.win = MainWindow()
        self.win._plot_timer.stop()          # we drive refresh_plot() manually
        self.win._last_active = self.win.new_panel()  # one panel window

    def tearDown(self):
        self.win.close()
        self.win.deleteLater()

    def feed(self, start: int, count: int) -> None:
        for i in range(start, start + count):
            self.win._on_packet(make_packet(i))

    # -- panel API used by the test ----------------------------------------
    def panel(self):
        return self.win._last_active.panel  # the GraphPanel widget

    def set_signals(self, configs):
        self.win._last_active.set_signals(configs)

    def curve(self, name):
        axis = self.panel().plot_widget._axes[name]
        return axis.curve.getData()

    def refresh(self):
        self.win._last_active.refresh_plot()

    # -- helpers to set up the "signal added mid-session" scenario ---------
    def add_signal_a(self):
        self.set_signals([
            RawSignalConfig(name="PosA", source_field="position11", enabled=True)
        ])

    def add_signal_b(self):
        configs = self.win._last_active.get_configs()
        self.set_signals(configs + [
            RawSignalConfig(name="PosB", source_field="position21", enabled=True),
        ])

    # ----------------------------------------------------------------------
    def test_live_alignment_when_signal_added_mid_session(self):
        """Older signal keeps its full history; newer signal starts at its
        enable moment; both end at the same live time."""
        self.add_signal_a()
        self.feed(0, 200)          # A runs for 10 s
        self.add_signal_b()        # B is enabled at global t = 10 s
        self.feed(200, 100)        # both then run to t = 15 s
        self.refresh()

        xa, _ = self.curve("PosA")
        xb, _ = self.curve("PosB")

        # B starts at its enable moment...
        self.assertAlmostEqual(float(xb[0]), 10.0, places=6)
        self.assertEqual(len(xb), 100)
        # ...and the older signal A is NOT truncated to B's shorter length.
        self.assertEqual(len(xa), 300)
        self.assertAlmostEqual(float(xa[0]), 0.0, places=6)
        # Both end on the same (live) time sample.
        self.assertAlmostEqual(float(xa[-1]), float(xb[-1]), places=6)
        self.assertAlmostEqual(float(xa[-1]), 14.95, places=6)

    def test_paused_step_alignment_when_signal_added_mid_session(self):
        """Pausing at live and stepping back must slice both signals by the
        same wall-clock cut, not by their local sample counts."""
        self.add_signal_a()
        self.feed(0, 200)
        self.add_signal_b()
        self.feed(200, 100)
        self.refresh()

        self.panel()._toggle_playback()        # pause at live (t = 14.95)
        self.refresh()
        xa, _ = self.curve("PosA")
        xb, _ = self.curve("PosB")
        self.assertAlmostEqual(float(xa[-1]), float(xb[-1]), places=6)
        self.assertEqual(len(xa), 300)
        self.assertEqual(len(xb), 100)

        # One step back -> both end at 14.90.
        self.panel()._step_back()
        self.refresh()
        xa, _ = self.curve("PosA")
        xb, _ = self.curve("PosB")
        self.assertAlmostEqual(float(xa[-1]), float(xb[-1]), places=6)
        self.assertAlmostEqual(float(xa[-1]), 14.90, places=6)
        self.assertEqual(len(xa), 299)
        self.assertEqual(len(xb), 99)

        # Step back before B was enabled (past t = 10): B has nothing to
        # draw, A keeps going - but A is never truncated by B's emptiness.
        for _ in range(110):
            self.panel()._step_back()
        self.refresh()
        xa, _ = self.curve("PosA")
        xb, _ = self.curve("PosB")
        self.assertEqual(len(xb), 0)               # B's buffer starts later
        self.assertGreater(len(xa), 0)
        self.assertLessEqual(float(xa[-1]), 10.0)

    def test_aligned_start_no_regression(self):
        """When all signals are enabled before data starts, live + paused
        behavior is unchanged (slicing == time slicing)."""
        self.set_signals([
            RawSignalConfig(name="PosA", source_field="position11", enabled=True),
            RawSignalConfig(name="PosB", source_field="position21", enabled=True),
        ])
        self.feed(0, 200)
        self.refresh()

        xa, _ = self.curve("PosA")
        xb, _ = self.curve("PosB")
        self.assertEqual(len(xa), 200)
        self.assertEqual(len(xb), 200)
        self.assertAlmostEqual(float(xa[-1]), float(xb[-1]), places=6)

        # Pause at live then step back several samples: both remain equal in
        # length and end on the same time (the all-aligned baseline case).
        self.panel()._toggle_playback()
        for _ in range(50):
            self.panel()._step_back()
        self.refresh()
        xa, _ = self.curve("PosA")
        xb, _ = self.curve("PosB")
        self.assertEqual(len(xa), len(xb))
        self.assertAlmostEqual(float(xa[-1]), float(xb[-1]), places=6)


if __name__ == "__main__":
    unittest.main()
