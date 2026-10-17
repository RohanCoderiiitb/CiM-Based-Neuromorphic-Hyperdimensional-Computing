"""1B-ii: mesh solver, wire helpers and drift model."""
import numpy as np
import pytest

import device.constants as C
from device.constants import DEFAULT
from drift.model import ages, draw_z4, mc_levels_drift
from margin.core import draw_z, mc_levels, params_for
from solver.newton import solve_column
from spice.runner import ngspice_available
from wire.decompose import group_rows
from wire.mesh import MeshConvergenceError, solve_mesh

P = DEFAULT


def test_mesh_zero_wire_limit_equals_single_node_solver():
    rng = np.random.default_rng(1)
    gaps = rng.uniform(0.2, 1.7, (8, 3)); pos = np.arange(1, 9, dtype=float)
    m = solve_mesh(gaps, pos, P, r_bl=1e-3, r_wl=1e-3, r_drv=1e-3)
    ref = solve_column(gaps.T, np.ones((3, 8), bool), P)
    assert np.max(np.abs(m.i_col / ref.i_col - 1)) < 1e-4


def test_mesh_single_branch_is_exact_series_combination():
    # one cell: the driver adds to R_tx, the bitline adds to R_s -> the 1A scalar solver with those lumped values must agree to solver precision
    for gap in (0.2, 0.9, 1.7):
        m = solve_mesh(np.array([[gap]]), np.array([37.0]), P, r_bl=0.72, r_wl=0.72, r_drv=10.0)
        ref = solve_column(np.array([[gap]]), np.array([[True]]), P, r_s=P.r_s + 0.72 * 37.0, r_tx=P.r_tx + 10.0).i_col[0]
        assert m.i_col[0] == pytest.approx(ref, rel=1e-9)


def test_far_group_equals_larger_sense_resistor_to_first_order():
    # the lumped statement used in the final budget: a group behind r*pos0 ohm of bitline ~ the 1A solver with R_s + r*pos0 (one column, all LRS)
    g, r = 8, 0.72
    rows = group_rows("contiguous", g, 63)
    gaps = np.full((g, 1), P.gap_lrs)
    m = solve_mesh(gaps, rows + 1.0, P, r_bl=r, r_wl=r, r_drv=1e-4).i_col[0]
    ref = solve_column(gaps.T, np.ones((1, g), bool), P, r_s=P.r_s + r * (rows[0] + 1.0)).i_col[0]
    assert m == pytest.approx(ref, rel=0.02)          # within-group voltage variation is the (small) difference


def test_contiguous_beats_interleaved_within_group_error():
    from wire.terms import within
    # same group size, same wire: spreading the rows of a group over the column must not reduce the pattern-dependent error
    assert within(4, 20, 5.0, 0.72, "near")["within_a"] < 1e-5          # contiguous g = 4: sub-uA
    from wire.decompose import pair_idiff
    p = params_for(20, 5.0)
    contig, inter = group_rows("contiguous", 4, 0), group_rows("interleaved", 4, 0)
    rng = np.random.default_rng(0)
    spread = lambda rows: np.ptp([pair_idiff(p, rows, np.arange(4) < 2, 0.72, 10.0), pair_idiff(p, rows, np.arange(4) >= 2, 0.72, 10.0)])
    assert spread(inter) > 5 * spread(contig)


def test_mesh_raises_on_nonconvergence():
    with pytest.raises(MeshConvergenceError):
        solve_mesh(np.full((4, 2), 0.2), np.arange(1, 5, dtype=float), P, r_bl=0.5, r_wl=0.5, r_drv=10.0, max_iter=1)


@pytest.mark.skipif(not ngspice_available(), reason="ngspice not installed")
def test_mesh_matches_ngspice_small_array():
    from wire.netlist import run_mesh_ngspice
    rng = np.random.default_rng(5)
    R, K = 8, 4
    gaps = rng.uniform(0.2, 1.7, (R, K)); act = np.zeros(R, bool); act[[1, 2, 5, 7]] = True
    ref = run_mesh_ngspice(gaps, act, P, r_bl=2.0, r_wl=2.0, r_drv=20.0)
    rows = np.flatnonzero(act)
    m = solve_mesh(gaps[rows], rows + 1.0, P, r_bl=2.0, r_wl=2.0, r_drv=20.0)
    assert np.max(np.abs(m.i_col / ref - 1)) < 1e-8


def test_drift_nu_zero_reduces_to_1bi_monte_carlo():
    p = params_for(20, 5.0)
    z4 = draw_z4(8, 300)
    a = mc_levels_drift(8, 8, p, 0.10, 0.0, 0.0, 5.0, z4)
    b = mc_levels(8, 8, p, 0.10, (z4[0], z4[1]))
    assert np.allclose(a["mean_diff"], b["mean_diff"], rtol=1e-12) and np.allclose(a["std_diff"], b["std_diff"], rtol=1e-12)


def test_drift_shrinks_levels_and_widens_spread_with_age():
    p = params_for(20, 5.0)
    z4 = draw_z4(8, 400)
    young = mc_levels_drift(8, 8, p, 0.05, 0.01, 0.0025, 0.0, z4)
    old = mc_levels_drift(8, 8, p, 0.05, 0.01, 0.0025, 11.0, z4)
    assert np.all(np.abs(old["mean_diff"][[0, -1]]) < np.abs(young["mean_diff"][[0, -1]]))
    assert old["std_diff"].max() > young["std_diff"].max() * 0.7        # exponent spread adds to (not removes) the t0 spread in log terms; |I| also shrinks
    assert ages(10.0)[0] == 0.0 and ages(10.0)[-1] == pytest.approx(np.log(10 * C.SECONDS_PER_YEAR / C.DRIFT_T0_S))


def test_reference_cell_term_is_added_not_free():
    from drift.strategies import evaluate
    r0 = evaluate(8, 20, 5.0, 0.10, 0.0, 0.25, 10.0, "S3", n_ref=128, ref_mode="abs", n=300, n_ages=2)
    assert r0["ages"][0]["ref_a"] > 0                                    # even with no drift the references add their own spread
    r1 = evaluate(8, 20, 5.0, 0.10, 0.0, 0.25, 10.0, "S3", n_ref=128, ref_mode="ratio", n=300, n_ages=2)
    assert r1["ages"][0]["ref_a"] == 0.0                                 # 'ratio' mode with no drift has nothing to add
