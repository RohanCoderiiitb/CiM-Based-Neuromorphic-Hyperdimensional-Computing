"""2-D resistive mesh solver for a crossbar read (1B Part C1).

Topology (same as the ngspice netlist in wire/netlist.py, which validates it):
  per ACTIVE row i:   V_read --R_DRV-- W[i,0] --r_wl-- W[i,1] --r_wl-- ... --r_wl-- W[i,K-1]          (row line, driver at column 0)
  per column j:       S_j --R_s-- ground ;   S_j --r_bl*pos_0-- B[0,j] --r_bl*(pos_1-pos_0)-- B[1,j] -- ...   (bitline, sense node at the bottom)
  cell (i,j) bridges W[i,j] and B[i,j]: access transistor (linear R_tx, 1A section 4) in series with the sinh device (gap[i,j]).
Inactive rows (access transistors open) carry no cell and no row line. Their bitline segments still exist; because no current enters at an
inactive row, a run of inactive rows is an exact series resistance, so the bitline chain is collapsed onto the ACTIVE rows with the physical
distance `pos` (in cell pitches from the sense node) setting each segment. This elimination is exact and is checked against ngspice, which keeps every physical row.

Method: full Newton on all 2*n*K + K unknowns (nonlinear sinh cells), the Jacobian solved directly by sparse LU; step-limited and
backtracked; convergence ASSERTED on every solve (raises MeshConvergenceError). Returns column currents (through R_s) and node voltages.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import scipy.sparse as sp
import scipy.sparse.linalg as spla

from device.constants import DEFAULT, NEWTON_MAX_ITER, Params
from solver.newton import _branch


R_FLOOR = 1e-4   # ohm: smallest wire/driver resistance modelled (conductance 1e4 S keeps the double-precision residual ~1e-13 A)


class MeshConvergenceError(RuntimeError):
    pass


@dataclass
class MeshResult:
    i_col: np.ndarray      # (K,) A, current through each sense resistor
    v_sense: np.ndarray    # (K,)
    v_b: np.ndarray        # (n, K) bitline node voltages at the active rows
    v_w: np.ndarray        # (n, K) row-line node voltages
    i_cell: np.ndarray     # (n, K) cell currents
    iters: int
    residual: float        # max |KCL residual| (A) at exit
    # 1C extension (None when the option is not used)
    v_rail: np.ndarray | None = None    # (n,) supply-rail voltage at each active row's driver tap
    i_row: np.ndarray | None = None     # (n,) total current each active row's drivers draw from the supply
    v_gnd: np.ndarray | None = None     # (K,) ground-rail voltage at each column's sense return


def _cell(vx: np.ndarray, a_amp: np.ndarray, p: Params, r_tx: float):
    """Series (R_tx + sinh device): current and small-signal conductance dI/dvx, vectorised (reuses the validated 1A branch solve)."""
    i, gd, _ = _branch(vx, a_amp, np.asarray(r_tx, dtype=float), p, 60, 1e-15)
    return i, gd / (1.0 + r_tx * gd)


def solve_mesh(gaps: np.ndarray, pos: np.ndarray, p: Params = DEFAULT, *, r_bl: float, r_wl: float, r_drv: float,
               r_s: float | np.ndarray | None = None, r_tx: float | None = None, max_iter: int = 60, tol_v: float = 1e-12,
               tol_i: float = 1e-11) -> MeshResult:
    """gaps (n, K): filament gap of the device at each ACTIVE row i and column j. pos (n,): distance of row i from the sense node in cell pitches
    (strictly increasing, >= 1). r_bl / r_wl: ohm per cell pitch on bitline / row line; r_drv: row driver resistance."""
    gaps = np.asarray(gaps, dtype=float)
    n, K = gaps.shape
    pos = np.asarray(pos, dtype=float)
    if pos.shape != (n,) or np.any(np.diff(pos) <= 0) or pos[0] < 1:
        raise ValueError("pos must be strictly increasing and >= 1")
    rs = np.broadcast_to(np.asarray(p.r_s if r_s is None else r_s, dtype=float), (K,))
    rtx = p.r_tx if r_tx is None else r_tx
    a_amp = p.i0 * np.exp(-gaps / p.g0)
    seg = np.diff(np.concatenate([[0.0], pos]))              # pitches between consecutive chain nodes (sense -> row0 -> row1 ...)
    r_bl, r_wl, r_drv = (max(float(x), R_FLOOR) for x in (r_bl, r_wl, r_drv))   # below R_FLOOR the matrix is too stiff for double precision
    g_seg = 1.0 / (r_bl * seg)
    g_wl = 1.0 / r_wl
    g_dr = 1.0 / r_drv
    # unknown layout: column-major blocks of [B_0, W_0, B_1, W_1, ...]; then K sense nodes
    def bi(i, j): return 2 * (j * n + i)
    def wi(i, j): return 2 * (j * n + i) + 1
    N = 2 * n * K + K
    ii = np.arange(n)[:, None]; jj = np.arange(K)[None, :]
    B = (2 * (jj * n + ii)).ravel(); W = B + 1
    Sx = 2 * n * K + np.arange(K)
    # fixed (linear) part of the Jacobian and its residual contribution, assembled as COO triplets
    rows, cols, vals = [], [], []
    def add(r, c, v):
        rows.append(np.atleast_1d(r)); cols.append(np.atleast_1d(c)); vals.append(np.broadcast_to(np.asarray(v, dtype=float), np.atleast_1d(r).shape))
    # bitline chain: node (i,j) with neighbour (i-1,j) (or S_j for i = 0)
    gs = np.repeat(g_seg[:, None], K, axis=1).ravel(order="F") if False else (g_seg[:, None] * np.ones((1, K))).ravel(order="F")
    # ordering of ravel('F') over (n, K) is column-major: idx = j*n + i  -> matches bi()
    Bf = 2 * np.arange(n * K)
    first = (np.arange(n * K) % n) == 0
    prevB = np.where(first, 2 * n * K + (np.arange(n * K) // n), Bf - 2)          # neighbour toward the sense node
    # F_B = I_c + g_seg*(prev - B) + g_next*(next - B)
    add(Bf, Bf, -gs); add(Bf, prevB, gs)
    nxt_exists = (np.arange(n * K) % n) != (n - 1)
    gnext = np.where(nxt_exists, np.roll(gs, -1), 0.0)
    add(Bf[nxt_exists], Bf[nxt_exists] + 2, gnext[nxt_exists]); add(Bf, Bf, -gnext)
    # sense node: F_S = g_seg0*(B_0 - S) - S/R_s
    add(Sx, Sx, -(g_seg[0] + 1.0 / rs)); add(Sx, 2 * np.arange(K) * n, g_seg[0])
    # row line: W(i,j) <-> W(i,j+1) with g_wl ; driver at j = 0
    Wf = Bf + 1
    jcol = np.arange(n * K) // n
    has_prev = jcol > 0; has_next = jcol < K - 1
    add(Wf, Wf, -(np.where(has_prev, g_wl, g_dr) + np.where(has_next, g_wl, 0.0)))
    add(Wf[has_prev], Wf[has_prev] - 2 * n, g_wl); add(Wf[has_next], Wf[has_next] + 2 * n, g_wl)
    Jlin = sp.csc_matrix((np.concatenate(vals), (np.concatenate(rows), np.concatenate(cols))), shape=(N, N))
    # constant source term: driver injects g_dr * V_read at W(i,0)
    src = np.zeros(N)
    src[Wf[jcol == 0]] = g_dr * p.v_read

    x = np.zeros(N)
    x[W] = p.v_read * 0.9           # start: rows near V_read, bitlines grounded
    a_flat = a_amp.ravel(order="F")  # (j*n + i) order

    def residual_jac(x, want_j: bool):
        vx = x[Wf] - x[Bf]
        i_c, gc = _cell(vx, a_flat, p, rtx)
        F = Jlin @ x + src
        np.add.at(F, Bf, i_c); np.add.at(F, Wf, -i_c)
        if not want_j:
            return F, i_c, None
        Jn = sp.csc_matrix((np.concatenate([-gc, gc, gc, -gc]), (np.concatenate([Bf, Bf, Wf, Wf]), np.concatenate([Bf, Wf, Bf, Wf]))), shape=(N, N))
        return F, i_c, Jlin + Jn

    F, i_c, J = residual_jac(x, True)
    for it in range(1, max_iter + 1):
        dx = spla.splu(J.tocsc()).solve(-F)
        step = float(np.max(np.abs(dx)))
        lam = min(1.0, 0.2 / step) if step > 0.2 else 1.0          # step limit 0.2 V
        f0 = float(np.max(np.abs(F)))
        for _ in range(12):                                          # backtrack on the KCL residual
            xt = x + lam * dx
            Ft, i_t, _ = residual_jac(xt, False)
            if np.max(np.abs(Ft)) <= f0 * (1 - 1e-4 * lam) or lam < 1e-3:
                break
            lam *= 0.5
        x = xt
        F, i_c, J = residual_jac(x, True)
        if lam * step < tol_v and float(np.max(np.abs(F))) < tol_i:
            break
    else:
        raise MeshConvergenceError(f"mesh Newton did not converge in {max_iter} iterations (residual {np.max(np.abs(F)):.3e} A)")
    vs = x[Sx]
    return MeshResult(i_col=vs / rs, v_sense=vs, v_b=x[Bf].reshape(K, n).T, v_w=x[Wf].reshape(K, n).T, i_cell=i_c.reshape(K, n).T,
                      iters=it, residual=float(np.max(np.abs(F))))


def solve_mesh_ext(gaps: np.ndarray, pos: np.ndarray, p: Params = DEFAULT, *, r_bl: float, r_wl: float, r_drv: float,
                   r_s: float | np.ndarray | None = None, r_tx: float | None = None, blocks: tuple[int, ...] | None = None,
                   r_rail: float | None = None, rail_pos: np.ndarray | None = None, rail_length: float | None = None, r_gnd: float | None = None, gnd_pad_pitches: float = 1.0,
                   gnd_pad_per_block: bool = True, drive_both_ends: bool = False, max_iter: int = 60, tol_v: float = 1e-12, tol_i: float = 1e-11) -> MeshResult:
    """1C extension of solve_mesh: the same 2-D nonlinear mesh, plus the pieces that appear when columns share rails.

    blocks     : column-block widths (sum = K). The row line is BROKEN between blocks and each block has its own driver (R_drv) at its first column,
                 which is NeuroHDC's macro organisation. Default one block of K columns (== solve_mesh).
    r_rail     : ohm per pitch of the SUPPLY rail that feeds every row driver. Row i taps the rail at rail_pos[i] pitches from the supply pad (default pos);
                 the rail is a chain through the active rows (inactive rows carry no current: exact series collapse, as for the bitline). The drivers of ALL blocks
                 of a row hang on the same rail node, so the rail carries the whole array's read current. None = ideal supply at every driver (== solve_mesh).
    r_gnd      : ohm per column pitch of the GROUND rail that returns the sense nodes (each R_s goes to its own tap on the rail). The pad is gnd_pad_pitches from the
                 first column, one per block if gnd_pad_per_block (each macro has its own sense periphery) else a single pad. None = ideal ground.
    drive_both_ends: every block's row line has a driver (R_drv, same rail) at its LAST column as well as its first (two drivers per row per macro).
    rail_length: if given, a SECOND supply pad sits at that distance (pitches) from the first, so the rail is fed from both ends (a tap at distance d from pad 1 is rail_length - d from pad 2).
    Extra outputs: v_rail, i_row (supply current per active row), v_gnd. Validated against ngspice in wire/validate_mesh_ext.py."""
    gaps = np.asarray(gaps, dtype=float)
    n, K = gaps.shape
    pos = np.asarray(pos, dtype=float)
    if pos.shape != (n,) or np.any(np.diff(pos) <= 0) or pos[0] < 1:
        raise ValueError("pos must be strictly increasing and >= 1")
    blocks = (K,) if blocks is None else tuple(int(b) for b in blocks)
    if sum(blocks) != K:
        raise ValueError(f"blocks {blocks} must sum to K = {K}")
    c0 = np.concatenate([[0], np.cumsum(blocks)[:-1]])                    # first column of every block
    is_c0 = np.zeros(K, bool); is_c0[c0] = True
    cdrv = np.concatenate([c0, np.cumsum(blocks) - 1]) if drive_both_ends else c0      # columns that carry a driver
    rs = np.broadcast_to(np.asarray(p.r_s if r_s is None else r_s, dtype=float), (K,))
    rtx = p.r_tx if r_tx is None else r_tx
    a_amp = p.i0 * np.exp(-gaps / p.g0)
    seg = np.diff(np.concatenate([[0.0], pos]))
    r_bl, r_wl, r_drv = (max(float(x), R_FLOOR) for x in (r_bl, r_wl, r_drv))
    g_seg, g_wl, g_dr = 1.0 / (r_bl * seg), 1.0 / r_wl, 1.0 / r_drv
    use_rail, use_gnd = r_rail is not None, r_gnd is not None
    iB = np.arange(n * K).reshape(n, K); iW = n * K + iB; iS = 2 * n * K + np.arange(K)
    nxt = 2 * n * K + K
    iR = nxt + np.arange(n) if use_rail else None
    nxt += n if use_rail else 0
    iG = nxt + np.arange(K) if use_gnd else None
    N = nxt + (K if use_gnd else 0)
    rows_, cols_, vals_ = [], [], []
    src = np.zeros(N)

    def link(u, v, g):
        u, v = np.atleast_1d(u), np.atleast_1d(v); g = np.broadcast_to(np.asarray(g, dtype=float), u.shape)
        rows_.extend([u, v, u, v]); cols_.extend([u, v, v, u]); vals_.extend([-g, -g, g, g])

    def tie(u, g, volt):
        u = np.atleast_1d(u); g = np.broadcast_to(np.asarray(g, dtype=float), u.shape)
        rows_.append(u); cols_.append(u); vals_.append(-g); np.add.at(src, u, g * volt)

    link(iS, iB[0], g_seg[0])                                              # bitline chain, sense node -> row 0 -> row 1 ...
    if n > 1:
        link(iB[:-1].ravel(), iB[1:].ravel(), np.repeat(g_seg[1:], K))
    rows_in = np.repeat(np.arange(n), K - len(c0)); cols_in = np.tile(np.flatnonzero(~is_c0), n)   # row line inside blocks
    if len(cols_in):
        link(iW[rows_in, cols_in - 1], iW[rows_in, cols_in], g_wl)
    if use_rail:                                                           # drivers hang on the rail; rail chain from the pad through the active rows
        rp = pos if rail_pos is None else np.asarray(rail_pos, dtype=float)
        order = np.argsort(rp); d = rp[order]
        if d[0] <= 0 or np.any(np.diff(d) <= 0):
            raise ValueError("rail_pos must be positive and distinct")
        r_rail_f = max(float(r_rail), R_FLOOR)
        tie(iR[order[0]], 1.0 / (r_rail_f * d[0]), p.v_read)
        if rail_length is not None:
            if rail_length <= d[-1]:
                raise ValueError("rail_length must exceed every rail_pos")
            tie(iR[order[-1]], 1.0 / (r_rail_f * (rail_length - d[-1])), p.v_read)
        if n > 1:
            link(iR[order[:-1]], iR[order[1:]], 1.0 / (r_rail_f * np.diff(d)))
        link(np.repeat(iR, len(cdrv)), iW[:, cdrv].ravel(), g_dr)
    else:
        tie(iW[:, cdrv].ravel(), g_dr, p.v_read)
    if use_gnd:                                                            # sense returns on a ground rail
        link(iS, iG, 1.0 / rs)
        r_g = max(float(r_gnd), R_FLOOR)
        for b, (c, w) in enumerate(zip(c0, blocks)):
            if gnd_pad_per_block or b == 0:
                tie(iG[c], 1.0 / (r_g * gnd_pad_pitches), 0.0)
            if w > 1:
                link(iG[c:c + w - 1], iG[c + 1:c + w], 1.0 / r_g)
            if not gnd_pad_per_block and b > 0:
                link(iG[c - 1], iG[c], 1.0 / r_g)
    else:
        tie(iS, 1.0 / rs, 0.0)
    Jlin = sp.csc_matrix((np.concatenate(vals_), (np.concatenate(rows_), np.concatenate(cols_))), shape=(N, N))
    Bf, Wf = iB.ravel(), iW.ravel(); a_flat = a_amp.ravel()
    x = np.zeros(N); x[Wf] = 0.9 * p.v_read
    if use_rail:
        x[iR] = p.v_read

    def residual_jac(x, want_j: bool):
        i_c, gc = _cell(x[Wf] - x[Bf], a_flat, p, rtx)
        F = Jlin @ x + src
        np.add.at(F, Bf, i_c); np.add.at(F, Wf, -i_c)
        if not want_j:
            return F, i_c, None
        Jn = sp.csc_matrix((np.concatenate([-gc, gc, gc, -gc]), (np.concatenate([Bf, Bf, Wf, Wf]), np.concatenate([Bf, Wf, Bf, Wf]))), shape=(N, N))
        return F, i_c, Jlin + Jn

    F, i_c, J = residual_jac(x, True)
    for it in range(1, max_iter + 1):
        dx = spla.splu(J.tocsc()).solve(-F)
        step = float(np.max(np.abs(dx)))
        lam = min(1.0, 0.2 / step) if step > 0.2 else 1.0
        f0 = float(np.max(np.abs(F)))
        for _ in range(12):
            xt = x + lam * dx
            Ft, _, _ = residual_jac(xt, False)
            if np.max(np.abs(Ft)) <= f0 * (1 - 1e-4 * lam) or lam < 1e-3:
                break
            lam *= 0.5
        x = xt
        F, i_c, J = residual_jac(x, True)
        if lam * step < tol_v and float(np.max(np.abs(F))) < tol_i:
            break
    else:
        raise MeshConvergenceError(f"mesh Newton did not converge in {max_iter} iterations (residual {np.max(np.abs(F)):.3e} A)")
    vs = x[iS]; vg = x[iG] if use_gnd else np.zeros(K)
    i_row = None
    if use_rail:
        i_row = ((x[iR][:, None] - x[iW[:, cdrv]]) * g_dr).sum(axis=1)
    else:
        i_row = ((p.v_read - x[iW[:, cdrv]]) * g_dr).sum(axis=1)
    return MeshResult(i_col=(vs - vg) / rs, v_sense=vs, v_b=x[Bf].reshape(n, K), v_w=x[Wf].reshape(n, K), i_cell=i_c.reshape(n, K), iters=it,
                      residual=float(np.max(np.abs(F))), v_rail=x[iR] if use_rail else None, i_row=i_row, v_gnd=vg if use_gnd else None)
