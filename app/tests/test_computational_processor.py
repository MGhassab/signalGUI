"""Numerical tests for the Computational signal processor.

The derivative must be a real, robust numerical derivative, not a noisy
one-sided difference:
  - 1st derivative of a clean sine  -> cosine-like (correct amplitude/phase)
  - 2nd derivative of a clean sine  -> negative-sine-like
  - robust to integer quantization (a 16-bit device stream)
  - robust to irregular / jittered sample times
  - no startup spikes / NaN / Inf

Run:  cd app && ../.venv/bin/python -m unittest tests.test_computational_processor -v
"""
from __future__ import annotations

import unittest

import numpy as np

from models.signal_config import ComputationalSignalConfig, Operation
from processing.computational_processor import ComputationalProcessor

DT = 0.05  # 20 Hz, matching the device simulator


def run_processor(x, t, operation, x_degree):
    cfg = ComputationalSignalConfig(
        name="sig", source_field="Data1", operation=operation,
        x_degree=x_degree, gain=1.0, offset=0.0,
    )
    proc = ComputationalProcessor(cfg)
    out_t, out_v = [], []
    for value, tt in zip(x, t):
        for sample_t, sample_v in proc.process(value, tt):
            out_t.append(sample_t)
            out_v.append(sample_v)
    return np.asarray(out_t), np.asarray(out_v)


def fit_amp_phase(x, y, freq):
    """Least-squares amplitude + phase of y ~ A*cos(wx) + B*sin(wx)."""
    w = 2 * np.pi * freq
    c, *_ = np.linalg.lstsq(
        np.column_stack([np.cos(w * x), np.sin(w * x), np.ones_like(x)]),
        y, rcond=None,
    )
    return float(np.hypot(c[0], c[1])), float(np.arctan2(c[1], c[0]))


class ComputationalProcessorTest(unittest.TestCase):
    def setUp(self):
        self.n = 2000
        self.t = np.arange(self.n) * DT
        self.amp = 1000.0

    # -- helpers ------------------------------------------------------------
    def sine(self, freq, t=None):
        t = self.t if t is None else t
        return self.amp * np.sin(2 * np.pi * freq * t)

    def assert_matches(self, tag, out_t, out_v, true_fn, freq,
                       amp_tol, corr_min, nrms_max, phase_atol_deg=2.0):
        self.assertGreater(out_t.size, 100)
        keep = out_t >= out_t[0] + 0.5
        xs = out_t[keep]
        ys = out_v[keep]
        # truth evaluated at the emitted (already time-correct) sample times
        ts = true_fn(xs)
        nrms = float(np.sqrt(np.mean((ys - ts) ** 2))) / (
            float(np.max(np.abs(ts))) or 1.0)
        corr = float(np.corrcoef(ys, ts)[0, 1])
        amp, phase = fit_amp_phase(xs, ys, freq)
        true_amp, _ = fit_amp_phase(xs, ts, freq)
        err = {
            "tag": tag, "corr": corr, "nrms": nrms,
            "amp": amp, "true_amp": true_amp,
            "amp_err_pct": 100.0 * (amp - true_amp) / true_amp,
            "phase_deg": np.degrees(phase),
        }
        self.assertGreaterEqual(corr, corr_min, err)
        self.assertLessEqual(nrms, nrms_max, err)
        self.assertLessEqual(abs(100.0 * (amp - true_amp) / true_amp),
                             amp_tol, err)
        # phase: 1st deriv -> 0 deg; 2nd deriv -> -90 deg (negative sine)
        expected = 0.0 if "2nd" not in tag else -90.0
        self.assertLessEqual(abs(np.degrees(phase) - expected), phase_atol_deg,
                             err)

    # -- requirements ---------------------------------------------------------
    def test_first_derivative_of_sine_is_cosine(self):
        freq = 0.2
        x = self.sine(freq)
        out_t, out_v = run_processor(x, self.t, Operation.DERIVATIVE, 1)
        w = 2 * np.pi * freq
        self.assert_matches(
            "1st deriv", out_t, out_v,
            lambda ts: self.amp * w * np.cos(w * ts),
            freq, amp_tol=2.0, corr_min=0.999, nrms_max=0.02,
        )

    def test_second_derivative_of_sine_is_negative_sine(self):
        freq = 0.2
        x = self.sine(freq)
        out_t, out_v = run_processor(x, self.t, Operation.DERIVATIVE, 2)
        w = 2 * np.pi * freq
        self.assert_matches(
            "2nd deriv", out_t, out_v,
            lambda ts: -self.amp * w * w * np.sin(w * ts),
            freq, amp_tol=3.0, corr_min=0.995, nrms_max=0.03,
        )

    def test_derivative_handles_irregular_sample_times(self):
        freq = 0.2
        rng = np.random.default_rng(7)
        tj = np.cumsum(np.full(self.n, DT) + rng.uniform(-0.006, 0.006, self.n))
        x = self.sine(freq, tj)
        out_t, out_v = run_processor(x, tj, Operation.DERIVATIVE, 2)
        w = 2 * np.pi * freq
        self.assert_matches(
            "2nd deriv (jittered)", out_t, out_v,
            lambda ts: -self.amp * w * w * np.sin(w * ts),
            freq, amp_tol=4.0, corr_min=0.99, nrms_max=0.05,
        )

    def test_derivative_stable_on_quantized_integer_input(self):
        """16-bit-style integer samples must not blow up (the old backward
        difference produced spikes ~8x the true 2nd-derivative amplitude)."""
        freq = 0.05
        x = np.round(self.sine(freq)).astype(float)
        out_t, out_v = run_processor(x, self.t, Operation.DERIVATIVE, 2)
        w = 2 * np.pi * freq
        true_amp = self.amp * w * w
        self.assert_matches(
            "2nd deriv (quantized)", out_t, out_v,
            lambda ts: -self.amp * w * w * np.sin(w * ts),
            freq, amp_tol=4.0, corr_min=0.97, nrms_max=0.15,
        )
        # no startup/quantization spikes: values stay near the true bound
        self.assertLessEqual(float(np.max(np.abs(out_v))), 4.0 * true_amp)

    def test_derivative_produces_finite_monotonic_time_aligned_output(self):
        x = self.sine(0.2)
        out_t, out_v = run_processor(x, self.t, Operation.DERIVATIVE, 1)
        self.assertTrue(np.all(np.isfinite(out_t)))
        self.assertTrue(np.all(np.isfinite(out_v)))
        self.assertTrue(np.all(np.diff(out_t) > 0))       # strictly increasing
        self.assertTrue(np.all(np.diff(out_t) <= DT + 1e-12))  # one sample each
        # centered => emitted times lag the raw stream but match real samples
        self.assertTrue(float(out_t[0]) >= float(self.t[0]))
        self.assertLessEqual(float(out_t[-1]), float(self.t[-1]))

    def test_derivative_no_output_before_window_is_full(self):
        x = self.sine(0.2)
        out_t, _ = run_processor(x[:20], self.t[:20], Operation.DERIVATIVE, 1)
        # first valid (centered) sample needs a full 5-sample window, and the
        # last (W-1)//2 samples never become a center => n - (W - 1) outputs
        self.assertEqual(out_t.size, 16)

    def test_integral_regression(self):
        x = self.sine(0.2)
        out_t, out_v = run_processor(x, self.t, Operation.INTEGRAL, 1)
        self.assertEqual(out_t.size, self.n)  # immediate output every sample
        w = 2 * np.pi * 0.2
        keep = out_t >= 1.0
        xs = out_t[keep]
        ys = out_v[keep]
        ts = -self.amp / w * np.cos(w * xs) + self.amp / w  # integral of sine
        self.assertLess(float(np.sqrt(np.mean((ys - ts) ** 2)))
                        / (float(np.max(np.abs(ts))) or 1.0), 0.05)

    def test_reset_restarts_cleanly(self):
        freq = 0.2
        x = self.sine(freq)
        cfg = ComputationalSignalConfig(
            name="sig", source_field="Data1", operation=Operation.DERIVATIVE,
            x_degree=2, gain=1.0, offset=0.0,
        )
        proc = ComputationalProcessor(cfg)
        # drain some data, then reset mid-stream
        for v, tt in zip(x[:500], self.t[:500]):
            for _ in proc.process(v, tt):
                pass
        proc.reset()
        out_t, out_v = [], []
        for v, tt in zip(x[500:], self.t[500:]):
            for ot, ov in proc.process(v, tt):
                out_t.append(ot)
                out_v.append(ov)
        out_t = np.asarray(out_t)
        out_v = np.asarray(out_v)
        self.assertTrue(np.all(np.isfinite(out_t)))
        # after reset the windows must be empty again => warm-up re-applies
        # (degree 2 windows 5,7: n - (4 + 6) outputs over the 1500 re-fed)
        self.assertEqual(out_t.size, 1490)
        # and the re-started derivative must still be a valid negative sine
        w = 2 * np.pi * freq
        keep = out_t >= out_t[0] + 0.5
        xs = out_t[keep]
        ys = out_v[keep]
        ts = -self.amp * w * w * np.sin(w * xs)
        self.assertGreaterEqual(float(np.corrcoef(ys, ts)[0, 1]), 0.99)


if __name__ == "__main__":
    unittest.main()
