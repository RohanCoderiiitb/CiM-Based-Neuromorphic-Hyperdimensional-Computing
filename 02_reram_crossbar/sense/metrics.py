"""Channel metrics shared by all four topologies: integrated input-referred current noise for a measurement window T, input impedance, bias power, area (layout-density estimate)."""
from __future__ import annotations

import numpy as np

KB, TEMP_K = 1.380649e-23, 300.15


def sigma_i(f: np.ndarray, s_in: np.ndarray, t: float, mode: str = "integrator") -> float:
    """1-sigma input-referred current (A) of a current measurement that averages over a window of length t.
    integrator: the charge collected over t divided by t: variance = integral S_i(f) sinc^2(pi f t) df (S_i one-sided A^2/Hz, f from the noise run's lowest frequency up).
    The part of the spectrum below f_min is bounded by the 1/f extrapolation (S_i held at its f_min value down to 1/(10 t) is NOT added: the window high-passes nothing below 1/t, so the
    low-frequency tail contributes at most S_i(f_min) * f_min, negligible here and reported by lowest_freq_share)."""
    w = (np.sinc(f * t)) ** 2                     # np.sinc(x) = sin(pi x)/(pi x)
    return float(np.sqrt(np.trapezoid(s_in * w, f)))


def bandlimited_sigma(f, s_in, fc: float) -> float:
    m = f <= fc
    return float(np.sqrt(np.trapezoid(s_in[m], f[m])))


def white_equiv(f, s_in, lo=1e8, hi=1e9) -> float:
    m = (f >= lo) & (f <= hi)
    return float(np.sqrt(np.mean(s_in[m])))


def sigma_i_out(f: np.ndarray, s_out: np.ndarray, h0: float, t: float) -> float:
    """1-sigma input-referred current of a copy-and-integrate measurement: the OUTPUT noise (the copy current/voltage noise that actually reaches the integrator) is weighted by the integration window
    sinc^2(pi f t) and divided by the low-frequency transfer h0 (the channel's signal gain). Avoids inflating noise at frequencies where the channel does not pass signal."""
    w = (np.sinc(f * t)) ** 2
    return float(np.sqrt(np.trapezoid(s_out * w, f)) / h0)
