"""Top-level, persistable application configuration."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List

from models.signal_config import SignalConfig
from models.packet import DATA_FIELDS


@dataclass
class AppConfig:
    serial_port: str = ""
    baud_rate: int = 115200
    signals: List[SignalConfig] = field(default_factory=list)
    data_field_names: Dict[str, str] = field(
        default_factory=lambda: {f: f for f in DATA_FIELDS}
    )
