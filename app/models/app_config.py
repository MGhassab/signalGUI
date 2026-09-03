"""Top-level, persistable application configuration.

With the move to a multi-panel workspace, serial settings are global (a
single physical connection feeds every panel) while each panel owns its
own independent signal list. `AppConfig` therefore stores the serial
settings plus one `PanelConfig` per panel.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from models.signal_config import SignalConfig


@dataclass
class PanelConfig:
    """Signal configuration belonging to a single graph panel."""
    signals: List[SignalConfig] = field(default_factory=list)


@dataclass
class AppConfig:
    serial_port: str = ""
    baud_rate: int = 115200
    panels: List[PanelConfig] = field(default_factory=lambda: [PanelConfig()])
