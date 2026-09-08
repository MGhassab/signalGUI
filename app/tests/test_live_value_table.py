"""Regression tests for the compact per-panel Name/Value table.

Bug guarded: after hiding the fixed OD_DATA rows ("Show Raw Data" off) with
no signal rows present, a phantom "DATA1" row remained on screen. Root
cause: `QTableWidget.setRowCount(n)` keeps the existing items inside rows
that are retained, so shrinking the table from 12 data rows to 1 retained
row left the stale "DATA1" cell text visible.

Run:  cd app && QT_QPA_PLATFORM=offscreen python3 -m unittest tests.test_live_value_table -v
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import unittest

from PySide6.QtWidgets import QApplication

from gui.live_value_table import LiveValueTable
from models.packet import DATA_FIELDS


class LiveValueTableTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tbl = LiveValueTable()

    def _names(self) -> list:
        return [self.tbl.item(r, 0).text()
                for r in range(self.tbl.rowCount())]

    def test_hide_data_with_no_signals_leaves_no_rows(self):
        self.assertEqual(self.tbl.rowCount(), len(DATA_FIELDS))
        self.tbl.set_data_visible(False)
        self.assertEqual(self.tbl.rowCount(), 0, "no phantom rows may remain")

    def test_hide_data_with_signals_keeps_only_signal_rows(self):
        self.tbl.set_signal_names(["PosA", "PosB"])
        self.tbl.set_data_visible(False)
        self.assertEqual(self._names(), ["PosA", "PosB"])

    def test_toggle_restores_all_rows(self):
        self.tbl.set_signal_names(["PosA"])
        self.tbl.set_data_visible(False)
        self.tbl.set_data_visible(True)
        names = self._names()
        self.assertEqual(names[: len(DATA_FIELDS)],
                         [f"DATA{i}" for i in range(1, len(DATA_FIELDS) + 1)])
        self.assertEqual(names[-1], "PosA")

    def test_update_signal_values_targets_right_rows_after_hide(self):
        self.tbl.set_signal_names(["PosA", "PosB"])
        self.tbl.set_data_visible(False)
        self.tbl.update_signal_values({"PosA": 1.25, "PosB": -3.0})
        self.assertEqual(self.tbl.item(0, 1).text(), "1.25")
        self.assertEqual(self.tbl.item(1, 1).text(), "-3")


if __name__ == "__main__":
    unittest.main()