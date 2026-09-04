"""Criterion calculator registry.

Register a new criterion by adding a calculator class here and mapping its
`Criterion` in `_CALCULATORS` - the GUI, engine and serialization already
follow the model.
"""
from __future__ import annotations

from models.signal_config import Criterion
from processing.criteria.calculators.base import CriterionCalculator
from processing.criteria.calculators.steady_state import SteadyStateErrorCalculator
from processing.criteria.calculators.settling_time import SettlingTimeCalculator
from processing.criteria.calculators.rise_time import RiseTimeCalculator
from processing.criteria.calculators.fall_time import FallTimeCalculator
from processing.criteria.calculators.overshoot import OvershootCalculator
from processing.criteria.calculators.inverse_response import InverseResponseCalculator

_CALCULATORS = {
    Criterion.STEADY_STATE_ERROR: SteadyStateErrorCalculator,
    Criterion.SETTLING_TIME: SettlingTimeCalculator,
    Criterion.RISE_TIME: RiseTimeCalculator,
    Criterion.FALL_TIME: FallTimeCalculator,
    Criterion.OVERSHOOT: OvershootCalculator,
    Criterion.INVERSE_RESPONSE: InverseResponseCalculator,
}

__all__ = [
    "CriterionCalculator",
    "SteadyStateErrorCalculator",
    "SettlingTimeCalculator",
    "RiseTimeCalculator",
    "FallTimeCalculator",
    "OvershootCalculator",
    "InverseResponseCalculator",
    "get_calculator",
]


def get_calculator(criterion: Criterion) -> CriterionCalculator:
    cls = _CALCULATORS[Criterion(criterion)]
    return cls()
