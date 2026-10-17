"""Newton solver unit tests. No ngspice required."""
import numpy as np
import pytest
from scipy.optimize import brentq

from device.constants import DEFAULT, GAP_HRS, GAP_LRS, NEWTON_MAX_ITER
from device.model import device_current, device_resistance, on_off_ratio
from solver.comparator import decide, nominal_levels
from solver.newton import ConvergenceError, solve_column, solve_differential

P = DEFAULT


def scalar_ref(gaps, p=P, r_s=None, r_tx=None):
    """Independent reference: nested scalar root-finds with brentq (no Newton, no shared code)."""
    r_s = p.r_s if r_s is None else r_s
    r_tx = p.r_tx if r_tx is None else r_tx

    def branch_i(vbl, gap):
        vx = p.v_read - vbl
        if r_tx == 0:
            return float(device_current(vx, gap, p))
        return brentq(lambda i: i - float(device_current(vx - i * r_tx, gap, p)), 0.0, vx / r_tx, xtol=1e-18, rtol=1e-14)

    f = lambda v: v / r_s - sum(branch_i(v, g) for g in gaps)
    return brentq(f, 0.0, p.v_read, xtol=1e-16, rtol=1e-14) / r_s


def test_model_limits_reproduce_plan_numbers():
    assert device_resistance(GAP_LRS) == pytest.approx(541.8, abs=0.05)
    assert device_resistance(GAP_HRS) == pytest.approx(218586, abs=1)
    assert on_off_ratio(GAP_LRS, GAP_HRS) == pytest.approx(403.4, abs=0.05)
    assert on_off_ratio(GAP_LRS, 1.5) == pytest.approx(181, abs=1)
    assert on_off_ratio(0.3, GAP_HRS) == pytest.approx(270, abs=1)


def test_zero_active_gives_exactly_zero():
    r = solve_column(np.full((3, 8), GAP_LRS), np.zeros((3, 8), bool))
    assert np.all(r.i_col == 0.0) and np.all(r.v_bl == 0.0)
    d = solve_differential(np.full((1, 8), GAP_LRS), np.full((1, 8), GAP_HRS), np.zeros((1, 8), bool))
    assert d.i_plus[0] == 0 and d.i_minus[0] == 0 and d.i_diff[0] == 0


@pytest.mark.parametrize("gap", [GAP_LRS, 0.5, GAP_HRS])
def test_single_branch_matches_scalar_solution(gap):
    got = solve_column(np.array([[gap]]), np.array([[True]])).i_col[0]
    assert got == pytest.approx(scalar_ref([gap]), rel=1e-10)


def test_many_branches_match_independent_brentq():
    rng = np.random.default_rng(3)
    gaps = rng.uniform(0.2, 1.7, size=12)
    got = solve_column(gaps[None], np.ones((1, 12), bool)).i_col[0]
    assert got == pytest.approx(scalar_ref(gaps), rel=1e-10)


def test_rtx_zero_collapses_to_single_sinh_term():
    # r_tx = 0 and n identical LRS branches: V_bl/R_s = n*A*sinh((V_read-V_bl)/V0) + GMIN*(V_read-V_bl)*n
    n = 6
    r = solve_column(np.full((1, n), GAP_LRS), np.ones((1, n), bool), r_tx=0.0)
    vbl = r.v_bl[0]
    rhs = n * float(device_current(P.v_read - vbl, GAP_LRS))
    assert vbl / P.r_s == pytest.approx(rhs, rel=1e-10)


def test_rs_to_zero_gives_full_drive_current():
    n = 5
    r = solve_column(np.full((1, n), GAP_LRS), np.ones((1, n), bool), r_s=1e-9)
    assert r.v_bl[0] < 1e-9 * 10e-3          # V_bl = I*R_s -> ~1e-11 V
    # each branch: full V_read across (R_tx + device); solve one branch by scalar root find
    one = scalar_ref([GAP_LRS], r_s=1e-9)
    assert r.i_col[0] == pytest.approx(n * one, rel=1e-8)


def test_all_hrs_swaps_plus_minus_roles():
    g = 8
    act = np.ones((1, g), bool)
    d = solve_differential(np.full((1, g), GAP_HRS), np.full((1, g), GAP_LRS), act)   # stored 0 in every row
    e = solve_differential(np.full((1, g), GAP_LRS), np.full((1, g), GAP_HRS), act)   # stored 1 in every row
    assert d.i_plus[0] == pytest.approx(e.i_minus[0], rel=1e-12)
    assert d.i_minus[0] == pytest.approx(e.i_plus[0], rel=1e-12)
    assert d.i_diff[0] == pytest.approx(-e.i_diff[0], rel=1e-12) and d.i_diff[0] < 0 < e.i_diff[0]


def test_result_independent_of_which_rows_are_active():
    rng = np.random.default_rng(7)
    gaps = rng.uniform(0.2, 1.7, size=(1, 16))
    m = np.zeros((1, 16), bool)
    m[0, [1, 4, 5, 9, 12]] = True
    perm = rng.permutation(16)
    a = solve_column(gaps, m).i_col
    b = solve_column(gaps[:, perm], m[:, perm]).i_col
    assert a[0] == pytest.approx(b[0], rel=1e-12)
    # inactive gaps are irrelevant
    g2 = gaps.copy(); g2[~m] = 1.0
    assert solve_column(g2, m).i_col[0] == pytest.approx(a[0], rel=1e-14)


def test_identical_branches_independent_of_row_choice():
    n = 16
    for rows in ([0, 1, 2, 3], [12, 13, 14, 15], [0, 5, 10, 15]):
        act = np.zeros((1, n), bool); act[0, rows] = True
        got = solve_column(np.full((1, n), GAP_LRS), act).i_col[0]
        assert got == pytest.approx(solve_column(np.full((1, 4), GAP_LRS), np.ones((1, 4), bool)).i_col[0], rel=1e-13)


def test_compression_monotone_and_sublinear():
    cur = [solve_column(np.full((1, m), GAP_LRS), np.ones((1, m), bool)).i_col[0] for m in range(1, 9)]
    steps = np.diff(cur)
    assert np.all(steps > 0) and np.all(np.diff(steps) < 0)


def test_vectorised_batch_equals_loop():
    rng = np.random.default_rng(11)
    gaps = rng.uniform(0.2, 1.7, size=(20, 10)); act = rng.random((20, 10)) < 0.6
    rs = rng.uniform(1, 40, size=20)
    batch = solve_column(gaps, act, r_s=rs).i_col
    one = [solve_column(gaps[i:i + 1], act[i:i + 1], r_s=rs[i]).i_col[0] for i in range(20)]
    assert np.allclose(batch, one, rtol=1e-13, atol=0)


def test_convergence_within_fixed_iteration_count_for_extreme_cases():
    # exhaustive-extreme batch: every (a, m) at g=32, plus varied R_s / R_tx
    g = 32
    rows_p, rows_m, rows_a = [], [], []
    for a in range(1, g + 1):
        for m in range(a + 1):
            stored = np.arange(g) < m
            rows_p.append(np.where(stored, GAP_LRS, GAP_HRS)); rows_m.append(np.where(stored, GAP_HRS, GAP_LRS))
            rows_a.append(np.arange(g) < a)
    for rs, rtx in [(20, 200), (1, 0), (0.01, 0), (500, 1), (20, 5000)]:
        d = solve_differential(np.array(rows_p), np.array(rows_m), np.array(rows_a), r_s=rs, r_tx=rtx)
        assert d.outer_iters <= 12 and d.inner_iters <= 20


def test_nonconvergence_fails_loudly():
    with pytest.raises(ConvergenceError):
        solve_column(np.full((1, 32), GAP_LRS), np.ones((1, 32), bool), max_iter=1)


def test_comparator_nearest_level_roundtrip():
    lv = nominal_levels(16)
    assert np.all(np.diff(lv) > 0)
    assert np.array_equal(decide(lv, lv), np.arange(17))
