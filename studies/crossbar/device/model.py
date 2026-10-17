"""Read-path I-V of the Stanford-PKU RRAM model at fixed gap (no switching dynamics)."""
from __future__ import annotations

import numpy as np

from .constants import DEFAULT, Params


def device_current(v, gap, p: Params = DEFAULT):
    """Current through one device at voltage v (V) and filament gap (nm). Matches rram.va."""
    v = np.asarray(v, dtype=float)
    gap = np.asarray(gap, dtype=float)
    return p.i0 * np.exp(-gap / p.g0) * np.sinh(v / p.v0) + p.gmin * v


def device_resistance(gap, v: float | None = None, p: Params = DEFAULT):
    """Secant resistance V/I at v (default V_read)."""
    v = p.v_read if v is None else v
    return v / device_current(v, gap, p)


def on_off_ratio(gap_lrs, gap_hrs, v: float | None = None, p: Params = DEFAULT):
    return device_resistance(gap_hrs, v, p) / device_resistance(gap_lrs, v, p)
