"""Spread sampling. The compact model has no mismatch, so variability is imposed.

Log-normal conductance: A = A_nom * exp(sigma_lnG * randn). Because A = I0*exp(-gap/g0), this is the gap shift
gap = gap_nom - g0*sigma_lnG*randn, with sigma_lnG = sigma_gap/g0. Gaps may leave [minGap, maxGap]: those bounds
exist to stop the switching dynamics running away and are not a physical limit on a programmed read state.
"""
from __future__ import annotations

import numpy as np

from .constants import DEFAULT, G0, SIGMA_LNG, Params


def sample_gaps(rng: np.random.Generator, nominal, sigma_lng: float = SIGMA_LNG, g0: float = G0):
    nominal = np.asarray(nominal, dtype=float)
    return nominal - g0 * sigma_lng * rng.standard_normal(nominal.shape)


def sample_state_gaps(rng, stored, p: Params = DEFAULT, sigma_lng: float = SIGMA_LNG):
    """Gaps for (+ device, - device) given stored bits. 1 -> (LRS, HRS); 0 -> (HRS, LRS). Same sigma_lnG for both states."""
    stored = np.asarray(stored).astype(bool)
    nom_p = np.where(stored, p.gap_lrs, p.gap_hrs)
    nom_m = np.where(stored, p.gap_hrs, p.gap_lrs)
    return sample_gaps(rng, nom_p, sigma_lng, p.g0), sample_gaps(rng, nom_m, sigma_lng, p.g0)


def sigma_gap_from_lng(sigma_lng: float, g0: float = G0) -> float:
    """sigma_gap = g0 * sigma_lnG  [MODEL]."""
    return g0 * sigma_lng


def resistance_cv(sigma_lng: float) -> float:
    """Relative resistance std of a log-normal with log-sigma sigma_lnG: sqrt(exp(s^2)-1)  [MODEL]."""
    return float(np.sqrt(np.expm1(sigma_lng ** 2)))
