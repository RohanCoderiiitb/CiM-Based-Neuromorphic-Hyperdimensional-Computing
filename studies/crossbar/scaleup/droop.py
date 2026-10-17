"""C2/C3/C5 DC part: supply droop (and ground rise) of a macro or of the whole array, and how much of it is DATA-DEPENDENT.

Experiment (the 1B row-line method, extended): choose a victim cell column and one group read (G, a active rows). For each of n_own random OWN patterns (active subset, victim weights)
draw n_other random weight sets for every OTHER cell of the array and solve the 2-D nonlinear mesh twice:
    X0 = victim I_diff with ideal supply/ground (row-line IR only, i.e. what 1B measured but for the true 64-bitline macro)
    X1 = the same with the finite supply rail and ground rail
For a fixed own pattern, what varies with the OTHER columns' data cannot be absorbed by any per-(group, a, m) table or per-column scale: it is the uncorrectable, data-dependent
part. Reported: its standard deviation and its maximum deviation over the draws (for the row line alone, and with the rails), the mean shift the rails cause (correctable: a function of
(G, a, column) only), the droop in mV, and the spread of the total supply current across data (the physical origin).
"Alone" = the same pair in a 2-bitline array with ideal supply: the reference for the per-column gain.
"""
from __future__ import annotations

import numpy as np

import device.constants as C
from margin.core import params_for
from wire.mesh import solve_mesh_ext

NO_CONDUCTION_GAP = C.GAP_NO_HRS     # nm: a cell on an un-sensed column (floating bitline) draws no DC current


def _stored(W: np.ndarray) -> np.ndarray:
    K = 2 * W.shape[1]
    return np.repeat(W, 2, axis=1) ^ (np.arange(K)[None, :] % 2 == 1)


def macro_stats(G: int, a: int, victim_cell: int, *, n_cells: int = C.CELLS_PER_MACRO_ROW, blocks_cells: tuple[int, ...] | None = None, r_rail: float | None = None,
                r_gnd: float | None = None, feed_both: bool = True, drive_both_ends: bool = False, r_wl: float | None = None, own_all_match: bool = False, pos_of_rows=None, enabled_cells: np.ndarray | None = None, n_own: int = 6, n_other: int = 30, r: float = 0.72,
                area: int = C.AREA_1C, r_s: float = C.RS_1C, r_drv: float = C.R_DRV_DEFAULT, seed: int = C.WIRE_SEED, g: int = C.G_1C, rows_total: int = C.ROWS_TOTAL) -> dict:
    """One configuration. n_cells: total cells per row (32 = one macro, 160 = the array); blocks_cells: macro split (default one block). enabled_cells: bool mask of the cells
    whose bitlines are sensed (others float: no current). victim_cell must be enabled."""
    p = params_for(area, r_s)
    K = 2 * n_cells
    blocks = None if blocks_cells is None else tuple(2 * b for b in blocks_cells)
    en = np.ones(n_cells, bool) if enabled_cells is None else np.asarray(enabled_cells, bool)
    assert en[victim_cell]
    rng = np.random.default_rng([seed, G, a, victim_cell, n_cells, int((r_rail or 0) * 1e5), int(feed_both)])
    allrows = np.arange(G * g, min((G + 1) * g, rows_total))
    pos_fn = (lambda rr: rr + 1.0) if pos_of_rows is None else pos_of_rows        # distance of a physical row from its sense node, in pitches (default: sense node at row 0's end)
    kw0 = dict(r_bl=r, r_wl=r if r_wl is None else r_wl, r_drv=r_drv, r_s=r_s, blocks=blocks, drive_both_ends=drive_both_ends)
    out = dict(own=[], droop_mean_v=[], droop_max_v=[], gnd_max_v=[], isup_a=[])
    X0s, X1s, alones = [], [], []
    for _ in range(n_own):
        act = np.sort(rng.choice(len(allrows), a, replace=False)); rows = allrows[act]
        rows = rows[np.argsort(pos_fn(rows))]; pos = pos_fn(rows)                    # the mesh wants rows ordered by distance from the sense node
        w_own = np.ones(a, bool) if own_all_match else rng.random(a) < 0.5     # own_all_match: the full-scale level (m = a), the well-conditioned gain probe
        x0, x1 = [], []
        for _ in range(n_other):
            W = rng.random((a, n_cells)) < 0.5
            W[:, victim_cell] = w_own
            gaps = np.where(_stored(W), p.gap_lrs, p.gap_hrs)
            gaps[:, np.repeat(~en, 2)] = NO_CONDUCTION_GAP
            m0 = solve_mesh_ext(gaps, pos, p, **kw0)
            kw1 = dict(kw0, r_rail=r_rail, rail_length=(rows_total + 1.0) if (feed_both and r_rail is not None) else None, r_gnd=r_gnd, gnd_pad_per_block=True)
            m1 = m0 if (r_rail is None and r_gnd is None) else solve_mesh_ext(gaps, pos, p, **kw1)
            x0.append(m0.i_col[2 * victim_cell] - m0.i_col[2 * victim_cell + 1]); x1.append(m1.i_col[2 * victim_cell] - m1.i_col[2 * victim_cell + 1])
            out["isup_a"].append(float(m1.i_row.sum()))
            if m1.v_rail is not None:
                out["droop_mean_v"].append(float((C.V_READ - m1.v_rail).mean())); out["droop_max_v"].append(float((C.V_READ - m1.v_rail).max()))
            if m1.v_gnd is not None:
                out["gnd_max_v"].append(float(m1.v_gnd.max()))
        al = solve_mesh_ext(np.where(np.stack([w_own, ~w_own], 1), p.gap_lrs, p.gap_hrs), pos, p, **dict(kw0, blocks=None, drive_both_ends=False))
        alones.append(al.i_col[0] - al.i_col[1]); X0s.append(np.array(x0)); X1s.append(np.array(x1))
    X0, X1, al = np.array(X0s), np.array(X1s), np.array(alones)           # (n_own, n_other), (n_own, n_other), (n_own,)
    d = X1 - X0
    gain0 = float((al * X0.mean(1)).sum() / (al * al).sum()); gain1 = float((al * X1.mean(1)).sum() / (al * al).sum())
    isup = np.array(out["isup_a"])
    res = dict(G=G, a=a, victim_cell=victim_cell, n_cells=n_cells, drive_both_ends=drive_both_ends, r_wl=r if r_wl is None else r_wl, r_drv=r_drv, n_enabled=int(en.sum()), r_rail=r_rail, r_gnd=r_gnd, feed_both=feed_both, n_own=n_own, n_other=n_other,
               row_std_a=float(X0.std(1, ddof=1).max()), row_maxdev_a=float(np.abs(X0 - X0.mean(1, keepdims=True)).max()),
               tot_std_a=float(X1.std(1, ddof=1).max()), tot_maxdev_a=float(np.abs(X1 - X1.mean(1, keepdims=True)).max()),
               rail_inc_std_a=float(d.std(1, ddof=1).max()), rail_inc_maxdev_a=float(np.abs(d - d.mean(1, keepdims=True)).max()),
               rail_mean_shift_a=float(np.abs(d.mean(1)).max()), gain_row=gain0, gain_total=gain1,
               gain_resid_row_a=float(np.abs(X0.mean(1) - gain0 * al).max()), gain_resid_total_a=float(np.abs(X1.mean(1) - gain1 * al).max()),
               isup_mean_a=float(isup.mean()), isup_std_a=float(isup.std(ddof=1)), isup_min_a=float(isup.min()), isup_max_a=float(isup.max()),
               droop_mean_v=float(np.mean(out["droop_mean_v"])) if out["droop_mean_v"] else 0.0, droop_max_v=float(np.max(out["droop_max_v"])) if out["droop_max_v"] else 0.0,
               gnd_max_v=float(np.max(out["gnd_max_v"])) if out["gnd_max_v"] else 0.0)
    return res
