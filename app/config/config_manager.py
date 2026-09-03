"""Load/save `AppConfig` as human-readable JSON."""
from __future__ import annotations

import json
from pathlib import Path

from models.app_config import AppConfig
from models.signal_config import signal_config_from_dict


class ConfigManager:
    @staticmethod
    def save(config: AppConfig, path: str) -> None:
        payload = {
            "serial_port": config.serial_port,
            "baud_rate": config.baud_rate,
            "data_field_names": config.data_field_names,
            "signals": [s.to_dict() for s in config.signals],
        }
        Path(path).write_text(json.dumps(payload, indent=2), encoding="utf-8")

    @staticmethod
    def load(path: str) -> AppConfig:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        signals = [signal_config_from_dict(s) for s in payload.get("signals", [])]
        return AppConfig(
            serial_port=payload.get("serial_port", ""),
            baud_rate=payload.get("baud_rate", 115200),
            data_field_names=payload.get("data_field_names", {}),
            signals=signals,
        )

    @staticmethod
    def default() -> AppConfig:
        return AppConfig()
