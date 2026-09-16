"""Criteria reference-signal tests.

A criteria row's REFERENCE is now one of the Command channels
(Command1..Command4). These tests pin down:

- the default reference and the selectable set,
- migration of legacy Position references saved by older configs,
- end-to-end use of the selected Command channel by the criteria engine.

Run:  cd app && python3 -m unittest tests.test_criteria_reference -v
"""
from __future__ import annotations

import unittest

from models.packet import REFERENCE_FIELDS, Packet
from models.signal_config import (
    CriteriaSignalConfig, Criterion, SourceKind,
    normalize_reference_field, signal_config_from_dict,
)
from processing.signal_manager import SignalManager


class ReferenceFieldTest(unittest.TestCase):
    def test_reference_field_set_is_commands(self):
        self.assertEqual(
            REFERENCE_FIELDS, ["Command1", "Command2", "Command3", "Command4"]
        )

    def test_default_reference_is_command1(self):
        cfg = CriteriaSignalConfig(name="C", source_field="Position1")
        self.assertEqual(cfg.reference_field, "Command1")

    def test_normalize_maps_position_to_command(self):
        self.assertEqual(normalize_reference_field("Position1"), "Command1")
        self.assertEqual(normalize_reference_field("Position4"), "Command4")
        self.assertEqual(normalize_reference_field("Command3"), "Command3")
        self.assertEqual(normalize_reference_field("Position9"), "Position9")


class LegacyMigrationTest(unittest.TestCase):
    def test_legacy_position_reference_migrated_on_load(self):
        cfg = signal_config_from_dict({
            "name": "C",
            "source_field": "Position1",
            "signal_type": "criteria",
            "reference_field": "Position3",
        })
        self.assertIsInstance(cfg, CriteriaSignalConfig)
        self.assertEqual(cfg.reference_field, "Command3")

    def test_missing_reference_defaults_to_command1(self):
        cfg = signal_config_from_dict({
            "name": "C",
            "source_field": "Position1",
            "signal_type": "criteria",
        })
        self.assertEqual(cfg.reference_field, "Command1")


class ReferenceUsedByEngineTest(unittest.TestCase):
    def test_steady_state_error_uses_selected_command_reference(self):
        cfg = CriteriaSignalConfig(
            name="C",
            source_field="Position1",
            source_kind=SourceKind.FIELD,
            reference_field="Command3",
            criterion=Criterion.STEADY_STATE_ERROR,
            enabled=True,
        )
        mgr = SignalManager()
        mgr.set_signals([cfg])

        packet = Packet(
            values={"Position1": 1.0, "Command3": 5.0, "Command1": 99.0},
            seq=0,
        )
        mgr.on_packet(packet, t=0.0)

        _, y = mgr.get_plot_data("C")
        self.assertEqual(y.size, 1)
        # steady-state error = reference - source = 5.0 - 1.0
        self.assertAlmostEqual(float(y[-1]), 4.0, places=6)

    def test_reference_follows_configured_channel_not_position(self):
        cfg = CriteriaSignalConfig(
            name="C",
            source_field="Position1",
            source_kind=SourceKind.FIELD,
            reference_field="Command2",
            criterion=Criterion.STEADY_STATE_ERROR,
            enabled=True,
        )
        mgr = SignalManager()
        mgr.set_signals([cfg])

        packet = Packet(
            values={"Position1": 2.0, "Command2": 10.0, "Command3": 100.0},
            seq=0,
        )
        mgr.on_packet(packet, t=0.0)

        _, y = mgr.get_plot_data("C")
        # reference - source = 10.0 - 2.0
        self.assertAlmostEqual(float(y[-1]), 8.0, places=6)


if __name__ == "__main__":
    unittest.main()
