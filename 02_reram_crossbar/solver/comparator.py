"""Currents -> integer match count. Deliberately separate from the physics solver.

1A: nearest-ideal-level. 1B replaces this with a non-uniform reference ladder.
"""
from __future__ import annotations

import numpy as np

from device.constants import DEFAULT, Params
from solver.newton import solve_differential


def nominal_levels(a: int, p: Params = DEFAULT, r_s=None, r_tx=None) -> np.ndarray:
    """Nominal (no-spread) I_diff for m = 0..a matches among `a` active rows. Shape (a+1,)."""
    m = np.arange(a + 1)
    idx = np.arange(a)[None, :]
    stored = idx < m[:, None]                      # first m active rows store 1
    gp = np.where(stored, p.gap_lrs, p.gap_hrs)
    gm = np.where(stored, p.gap_hrs, p.gap_lrs)
    return solve_differential(gp, gm, np.ones_like(stored), p, r_s, r_tx).i_diff


def decide(i_diff, levels) -> np.ndarray:
    """Nearest-level decision. i_diff: (...,), levels: (a+1,) ascending in m. Returns integer m."""
    i_diff = np.asarray(i_diff, dtype=float)
    return np.argmin(np.abs(i_diff[..., None] - np.asarray(levels)), axis=-1)
