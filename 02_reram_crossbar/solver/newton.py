"""Vectorised Newton nodal solver for one 2T2R column read.

Network per column: ideal V_read source -> R_tx -> device (sinh) -> shared bitline node -> R_s -> ground.
Only ACTIVE branches exist; an inactive row (access transistor open) is excluded entirely.

Unknown: bitline voltage V_bl, from  V_bl/R_s = sum_i I_i(V_bl),  where each branch current I_i satisfies
    (V_read - V_bl - v_i)/R_tx = Id(v_i; gap_i),   Id(v;gap) = A*sinh(v/V0) + GMIN*v,   A = I0*exp(-gap/g0)
with v_i the voltage across the device. R_tx is series with the device, so I_i is itself implicit; it is
resolved by an inner scalar Newton per branch (exact, no linearisation). Both loops are safeguarded and
raise if they fail to converge. Returns raw currents; no decisions are made here.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from device.constants import DEFAULT, NEWTON_MAX_ITER, NEWTON_TOL_V, Params


class ConvergenceError(RuntimeError):
    pass


@dataclass
class ColumnResult:
    i_col: np.ndarray      # A, current through R_s (= column current), shape = batch shape
    v_bl: np.ndarray       # V, bitline voltage
    outer_iters: int       # worst-case outer iterations used
    inner_iters: int       # worst-case inner iterations used in any outer step


def _branch(vx, a_amp, r_tx, p: Params, max_iter: int, tol: float):
    """Solve each branch for device voltage given drive vx = V_read - V_bl. Returns (i, g_eff, iters).

    h(v) = (vx - v)/r_tx - Id(v) is decreasing and concave on v>=0, h(0)>0, so Newton from v=0 overshoots
    the root once and then converges monotonically from the right; no overflow (first step lands in [0, vx]).
    r_tx == 0 is handled exactly: the device sees the full drive, v = vx.
    """
    zero = r_tx == 0.0
    rt = np.where(zero, 1.0, r_tx)
    v = np.zeros(np.broadcast_shapes(vx.shape, a_amp.shape))
    iters = 0
    for iters in range(1, max_iter + 1):
        idv = a_amp * np.sinh(v / p.v0) + p.gmin * v
        gd = a_amp * np.cosh(v / p.v0) / p.v0 + p.gmin
        step = ((vx - v) / rt - idv) / (1.0 / rt + gd)
        v = v + step
        if np.max(np.abs(np.where(zero, 0.0, step)), initial=0.0) < tol:
            break
    else:
        raise ConvergenceError(f"inner branch Newton did not converge in {max_iter} iterations")
    v = np.where(zero, vx, v)
    idv = a_amp * np.sinh(v / p.v0) + p.gmin * v
    gd = a_amp * np.cosh(v / p.v0) / p.v0 + p.gmin
    i_br = np.where(zero, idv, (vx - v) / rt)
    return i_br, gd, iters


def solve_column(gaps, active, p: Params = DEFAULT, r_s=None, r_tx=None,
                 max_iter: int = NEWTON_MAX_ITER, tol: float = NEWTON_TOL_V) -> ColumnResult:
    """Solve a batch of columns.

    gaps   : (..., n) per-branch filament gap in nm (any value for inactive branches).
    active : (..., n) bool, True where the row is switched on.
    r_s, r_tx : optional overrides, scalar or broadcastable to the batch shape (...,).
    """
    gaps = np.asarray(gaps, dtype=float)
    active = np.asarray(active, dtype=bool)
    if gaps.shape != active.shape:
        raise ValueError(f"gaps {gaps.shape} and active {active.shape} must match")
    batch = gaps.shape[:-1]
    rs = np.broadcast_to(np.asarray(p.r_s if r_s is None else r_s, dtype=float), batch)[..., None]
    rtx = np.broadcast_to(np.asarray(p.r_tx if r_tx is None else r_tx, dtype=float), batch)[..., None]
    a_amp = p.i0 * np.exp(-gaps / p.g0)

    lo = np.zeros(batch + (1,))
    hi = np.full(batch + (1,), p.v_read)
    vbl = np.zeros(batch + (1,))
    done = np.zeros(batch + (1,), dtype=bool)
    worst_inner = 0
    for outer in range(1, max_iter + 1):
        i_br, gd, it = _branch(p.v_read - vbl, a_amp, rtx, p, max_iter, tol)
        worst_inner = max(worst_inner, it)
        i_br = np.where(active, i_br, 0.0)
        # equivalent branch conductance dI/d(-V_bl) = gd/(1 + r_tx*gd)
        g_br = np.where(active, gd / (1.0 + rtx * gd), 0.0)
        f = vbl / rs - i_br.sum(axis=-1, keepdims=True)
        fp = 1.0 / rs + g_br.sum(axis=-1, keepdims=True)
        # maintain bracket: f is increasing in V_bl
        hi = np.where(f > 0, np.minimum(hi, vbl), hi)
        lo = np.where(f < 0, np.maximum(lo, vbl), lo)
        cand = vbl - f / fp
        cand = np.where((cand < lo) | (cand > hi), 0.5 * (lo + hi), cand)
        step = np.where(done, 0.0, cand - vbl)
        vbl = vbl + step
        done = done | (np.abs(step) < tol)
        if done.all():
            break
    else:
        raise ConvergenceError(f"outer bitline Newton did not converge in {max_iter} iterations")
    return ColumnResult(i_col=vbl[..., 0] / rs[..., 0], v_bl=vbl[..., 0], outer_iters=outer, inner_iters=worst_inner)


@dataclass
class DiffResult:
    i_plus: np.ndarray
    i_minus: np.ndarray
    i_diff: np.ndarray
    outer_iters: int
    inner_iters: int


def solve_differential(gaps_plus, gaps_minus, active, p: Params = DEFAULT, r_s=None, r_tx=None) -> DiffResult:
    """Both columns of a 2T2R group. I_diff = I_plus - I_minus. Columns have independent sense resistors."""
    a = solve_column(gaps_plus, active, p, r_s, r_tx)
    b = solve_column(gaps_minus, active, p, r_s, r_tx)
    return DiffResult(a.i_col, b.i_col, a.i_col - b.i_col, max(a.outer_iters, b.outer_iters),
                      max(a.inner_iters, b.inner_iters))
