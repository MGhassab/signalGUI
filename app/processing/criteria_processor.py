"""Data Type 3: Criteria-Based Computational Data.

The exact mathematical definition of "ESS Criteria (%)" and "Delay
Criteria (%)" has NOT been specified. This module deliberately does NOT
invent a settling-time / delay-time algorithm.

What it provides instead:
- A clean, isolated interface (`CriteriaProcessor`) that stores the two
  configured criteria percentages and keeps a bounded rolling history of
  the transformed signal.
- A single, clearly-marked TODO method (`_evaluate_criteria`) where the
  real algorithm should be implemented once it is specified.
- A safe placeholder behavior in the meantime: gain/offset are applied
  and the value is passed through unchanged, so the signal can still be
  wired end-to-end (configured, enabled, plotted) before the algorithm
  exists.
"""
from __future__ import annotations

from collections import deque
from typing import Deque

from processing.base_processor import SignalProcessor

# How much recent history to retain for a future criteria algorithm to
# use (e.g. to look back at a step response). Purely a placeholder buffer
# size - tune once the real algorithm exists.
_HISTORY_LEN = 2048


class CriteriaProcessor(SignalProcessor):
    def __init__(self, config):
        super().__init__(config)
        self._history: Deque[float] = deque(maxlen=_HISTORY_LEN)

    def reset(self) -> None:
        self._history.clear()

    def process(self, raw_value: float, t: float) -> float:
        transformed = self._apply_gain_offset(raw_value)
        self._history.append(transformed)
        return self._evaluate_criteria(transformed, t)

    def _evaluate_criteria(self, transformed: float, t: float) -> float:
        """TODO: implement the real ESS Criteria / Delay Criteria
        algorithm here once it is specified.

        Available to the future implementation:
        - self.config.ess_criteria_pct
        - self.config.delay_criteria_pct
        - self._history (deque of up to the last _HISTORY_LEN transformed
          values, oldest first)

        Placeholder behavior (safe, non-crashing, no invented math): pass
        the transformed value straight through, unaffected by the
        criteria settings.
        """
        return transformed
