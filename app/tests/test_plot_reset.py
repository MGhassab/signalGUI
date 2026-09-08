"""Regression test for the "plot turns white after (⟲) refresh" bug.

Reported symptom: after clicking the plot-panel reset button with no live
data on screen, the graph rendered blank/white and did not reliably recover
once new data arrived.

Root cause: `PlotWidget.reset_axes` always re-scrolled the X window to the
latest sample. After `clear_all()` every curve is empty, so "latest" was 0
and it issued `setXRange(0, 0, padding=0)`. A zero-width ViewBox range
collapses the view and pyqtgraph renders it blank/white; the next live
update's re-scroll then interacted with the broken view and left the plot
empty.

Fix: `reset_axes` guards the degenerate empty-data case and keeps a sane
default X window instead of a zero-width range.

Run:  cd app && QT_QPA_PLATFORM=offscreen python3 -m unittest tests.test_plot_reset -v
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest

from PySide6.QtWidgets import QApplication

from models.packet import Packet, PACKET_FIELDS
from models.signal_config import RawSignalConfig
from gui.main_window import MainWindow

DT = 0.05
ARRIVAL_BASE = 1000.0


def make_packet(i: int) -> Packet:
    values = {f: 100.0 + (i % 20) * 3 for f in PACKET_FIELDS}
    return Packet(values=values, seq=i, arrival_time=ARRIVAL_BASE + i * DT)


class PlotResetTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.win = MainWindow()
        self.win._plot_timer.stop()          # drive refresh manually
        self.win._last_active = self.win.new_panel()
        self.panel().set_signals([
            RawSignalConfig(name="PosA", source_field="Position1",
                            enabled=True, y_min=-10, y_max=10)
        ])

    def tearDown(self):
        self.win.close()
        self.win.deleteLater()

    def panel(self):
        return self.win._last_active.panel

    def feed(self, start, count):
        for i in range(start, start + count):
            self.win._on_packet(make_packet(i))

    def curve(self, name):
        return self.panel().plot_widget._axes[name].curve.getData()

    def xrange(self):
        return self.panel().plot_widget._plot_item.vb.viewRange()[0]

    def test_reset_with_data_then_more_data_recovers(self):
        # Baseline: live data renders with a real (non-zero-width) X window.
        self.feed(0, 100)
        self.panel().refresh_plot()
        x, _ = self.curve("PosA")
        self.assertGreater(len(x), 0, "expected data on the curve before reset")
        x0, x1 = self.xrange()
        self.assertGreater(x1 - x0, 0.0, "X window must be non-degenerate")

        # ⟲ reset: clears everything, resumes live.
        self.panel().reset_plot()
        x, _ = self.curve("PosA")
        self.assertEqual(len(x), 0, "reset must empty the on-screen curve")

        # After reset the X window must NOT be a zero-width degenerate range.
        x0, x1 = self.xrange()
        self.assertGreater(x1 - x0, 0.0,
                           "reset must keep a sane X window, not [0, 0] (blank)")

        # New data arriving after the reset must repopulate the curve.
        self.feed(100, 100)
        self.panel().refresh_plot()
        x, _ = self.curve("PosA")
        self.assertGreater(len(x), 0, "curve must recover after reset + new data")
        x0, x1 = self.xrange()
        self.assertGreater(x1 - x0, 0.0, "post-reset X window must be valid")

        # The signal's configured Y axis must survive the reset/repopulate.
        axis = self.panel().plot_widget._axes["PosA"]
        y0, y1 = axis.view_box.viewRange()[1]
        self.assertAlmostEqual(float(y0), -10.0, places=6)
        self.assertAlmostEqual(float(y1), 10.0, places=6)

    def test_reset_with_no_data_keeps_sane_window(self):
        # Reset before ANY data has arrived must not blank the plot.
        self.panel().reset_plot()
        x0, x1 = self.xrange()
        self.assertGreater(x1 - x0, 0.0,
                           "empty reset must keep a sane X window, not [0, 0]")


if __name__ == "__main__":
    unittest.main()
