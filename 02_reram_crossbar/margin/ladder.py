"""Comparator reference ladder design for the differential read.

Given the population-mean level of I_diff for each count m = 0..a (a known: it is the shared digital popcount of the input bit-row group),
the readout needs a threshold between every adjacent pair of levels. Why this is cheap for a BINARY readout: an analog (multi-level) readout
must undo compression on the VALUE with a runtime per-column multiply; a threshold decision only needs its reference in the right place,
which is a one-time design of the thresholds (a lookup, not arithmetic at run time).

Two designs are compared:
  uniform      thresholds equally spaced between L_0 and L_a (what you get if compression is ignored)
  non-uniform  thresholds matched to the actual compressed levels, sigma-weighted so both neighbours keep equal margin in sigma units
"""
from __future__ import annotations

import numpy as np


def uniform_thresholds(levels: np.ndarray) -> np.ndarray:
    a = len(levels) - 1
    return levels[0] + (np.arange(a) + 0.5) * (levels[-1] - levels[0]) / a


def weighted_thresholds(levels: np.ndarray, sigma: np.ndarray | None = None) -> np.ndarray:
    """t_k between level k and k+1, placed at L_k + step * s_k/(s_k + s_{k+1}). sigma=None or equal -> midpoints."""
    levels = np.asarray(levels, dtype=float)
    s = np.ones_like(levels) if sigma is None else np.asarray(sigma, dtype=float)
    s = np.maximum(s, 1e-300)
    return levels[:-1] + np.diff(levels) * s[:-1] / (s[:-1] + s[1:])


def margins(levels: np.ndarray, thresholds: np.ndarray) -> dict:
    """Per-count distance (A) from each level to the nearest threshold, signed: negative = the nominal level is already on the wrong side."""
    levels = np.asarray(levels, dtype=float)
    a = len(levels) - 1
    up = np.full(a + 1, np.inf); dn = np.full(a + 1, np.inf)
    up[:-1] = thresholds - levels[:-1]          # room above level k before crossing t_k
    dn[1:] = levels[1:] - thresholds            # room below level k before crossing t_{k-1}
    return dict(up=up, down=dn, dist=np.minimum(up, dn))


def margin_factor(levels, thresholds, sigma_total, n_sigma: float, headroom: float, resid_a: float = 0.0) -> np.ndarray:
    """Per-count margin factor mu_k = ((1-headroom)*dist_k - resid) / (n_sigma * sigma_k). >1 means count k is decided correctly at n_sigma."""
    d = margins(levels, thresholds)["dist"]
    return ((1.0 - headroom) * d - resid_a) / (n_sigma * np.maximum(np.asarray(sigma_total, dtype=float), 1e-300))


def decide(i_diff, thresholds) -> np.ndarray:
    """Count decision: number of thresholds below the measured value (thresholds ascending)."""
    return np.searchsorted(np.asarray(thresholds), np.asarray(i_diff))
