"""C1 (b): the sum of the group counts equals the true 512-row match count.

Each trial is one column read: a random 512-bit weight vector (stored LRS in the + device where w = 1, complementary in the - device) and a random activation vector.
For every group the active rows are solved on the mesh (device spread optional, gap = nominal - g0*sigma*z as in 1B) and the match count is DECIDED from the group's own
ladder table (indexed by that group's active count a); the 64 (or n_groups) decisions are added and compared with the integer Python model sum(x & w). Also run for group
sizes that do not divide 512 (g = 5, 6, 7: ragged last group) to expose boundary / offset errors in the group sequencing.
Tracked per decision: whether it was right, and the margin (distance of the measured current from the nearest threshold, in uA and as a multiple of the 1-sigma spread of
that decision).
"""
from __future__ import annotations

import numpy as np

import device.constants as C
from margin.core import params_for
from scaleup.column import decide, group_rows, n_groups, pair_idiff


def read_column(tables: list[dict], g: int, w: np.ndarray, x: np.ndarray, sigma: float, rng, r: float, p, margins: list | None = None, table_offset: int = 0,
                a_bias: int = 0) -> tuple[int, int, int]:
    """Returns (m_true, m_hat, number of wrong group decisions). table_offset / a_bias exist only for the NEGATIVE CONTROLS (a sequencer that indexes the wrong
    group's table, or a miscounted active count a): the test must catch the second and quantifies the tolerance to the first."""
    m_true = int(np.sum(w & x)); m_hat = 0; wrong = 0
    for Gi, tab in enumerate(tables):
        rows = group_rows(g, Gi)
        act = x[rows]
        a = int(act.sum())
        if a == 0:
            continue
        S = rows[act]; wS = w[S]
        z = rng.standard_normal((a, 2)) if sigma > 0 else None
        i_diff = pair_idiff(p, S, wS, r, None if z is None else -p.g0 * sigma * z)
        tab_use = tables[(Gi + table_offset) % len(tables)]
        mh = decide(tab_use, int(np.clip(a + a_bias, 1, len(rows))), i_diff)
        mt = int(wS.sum())
        m_hat += mh; wrong += int(mh != mt)
        if margins is not None:
            thr = np.asarray(tab["thr"][str(a)]); lv = np.asarray(tab["level"][str(a)])
            lo = thr[mt - 1] if mt > 0 else -np.inf; hi = thr[mt] if mt < a else np.inf
            margins.append((Gi, a, min(i_diff - lo, hi - i_diff), 0.5 * float(np.min(np.diff(lv)))))
    return m_true, m_hat, wrong


def trial_batch(args: tuple) -> dict:
    tables, g, r, area, r_s, sigma, density, n, seed = args
    p = params_for(area, r_s)
    rng = np.random.default_rng(seed)
    n_bad_total = n_wrong_dec = n_dec = 0; marg = []
    for _ in range(n):
        w = rng.random(C.ROWS_TOTAL) < 0.5
        x = rng.random(C.ROWS_TOTAL) < density
        mt, mh, wr = read_column(tables, g, w, x, sigma, rng, r, p, marg)
        n_bad_total += int(mt != mh); n_wrong_dec += wr
        n_dec += int(sum(x[group_rows(g, Gi)].any() for Gi in range(len(tables))))
    m = np.array([[mm[2] / 1e-6, mm[3] / 1e-6] for mm in marg])
    return dict(g=g, r=r, sigma=sigma, density=density, reads=n, sum_errors=n_bad_total, wrong_group_decisions=n_wrong_dec, group_decisions=n_dec,
                min_margin_uA=float(m[:, 0].min()), min_margin_frac_of_halfstep=float((m[:, 0] / m[:, 1]).min()),
                p01_margin_frac_of_halfstep=float(np.percentile(m[:, 0] / m[:, 1], 1)), mean_margin_frac_of_halfstep=float((m[:, 0] / m[:, 1]).mean()))
