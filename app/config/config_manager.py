"""Load/save `AppConfig` as human-readable JSON.

The current JSON schema is:

    {
      "serial_port": "...",
      "baud_rate": 115200,
      "panels": [ {"signals": [ ... ]}, ... ]
    }

For backward compatibility, files written by the pre-multi-panel app
(a flat `signals` list plus `data_field_names`) are still read: they load
as a single panel, and the legacy display-name map is ignored.
"""
from __future__ import annotations

import json
from pathlib import Path

from models.app_config import AppConfig, PanelConfig
from models.signal_config import signal_config_from_dict


class ConfigManager:
    @staticmethod
    def save(config: AppConfig, path: str) -> None:
        payload = {
            "serial_port": config.serial_port,
            "baud_rate": config.baud_rate,
            "panels": [
                {"signals": [s.to_dict() for s in panel.signals]}
                for panel in config.panels
            ],
        }
        Path(path).write_text(json.dumps(payload, indent=2), encoding="utf-8")

    @staticmethod
    def load(path: str) -> AppConfig:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        serial_port = payload.get("serial_port", "")
        baud_rate = payload.get("baud_rate", 115200)

        panels_payload = payload.get("panels")
        if panels_payload is not None:
            panels = [
                PanelConfig(
                    signals=[signal_config_from_dict(s) for s in panel.get("signals", [])]
                )
                for panel in panels_payload
            ]
        else:
            # Legacy single-panel format.
            legacy_signals = payload.get("signals", [])
            panels = [PanelConfig(
                signals=[signal_config_from_dict(s) for s in legacy_signals]
            )]

        if not panels:
            panels = [PanelConfig()]
        return AppConfig(
            serial_port=serial_port,
            baud_rate=baud_rate,
            panels=panels,
        )

    @staticmethod
    def default() -> AppConfig:
        return AppConfig()
