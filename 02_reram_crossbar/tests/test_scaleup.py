"""1C: extended mesh solver, transient model, group tables, accumulation, budget re-closure."""
import numpy as np
import pytest

import device.constants as C
from device.constants import DEFAULT
from margin.core import params_for
from spice.runner import ngspice_available
from wire.mesh import MeshConvergenceError, solve_mesh, solve_mesh_ext

P = DEFAULT


def _gaps(n, K, seed=0):
    rng = np.random.default_rng(seed)
    return rng.uniform(0.2, 1.7, (n, K))


def test_ext_default_equals_original_mesh():
    g = _gaps(8, 12); pos = np.arange(40.0, 48.0)
    a = solve_mesh(g, pos, P, r_bl=0.72, r_wl=0.72, r_drv=10.0, r_s=1.0)
    b = solve_mesh_ext(g, pos, P, r_bl=0.72, r_wl=0.72, r_drv=10.0, r_s=1.0)
    assert np.max(np.abs(a.i_col / b.i_col - 1)) < 1e-12


def test_ext_blocks_are_independent_macros():
    # two blocks with their own drivers == two separate solves (no rails): the row line is broken between blocks
    g = _gaps(4, 16, 1); pos = np.arange(10.0, 14.0)
    both = solve_mesh_ext(g, pos, P, r_bl=0.72, r_wl=0.72, r_drv=10.0, r_s=1.0, blocks=(8, 8)).i_col
    left = solve_mesh_ext(g[:, :8], pos, P, r_bl=0.72, r_wl=0.72, r_drv=10.0, r_s=1.0).i_col
    right = solve_mesh_ext(g[:, 8:], pos, P, r_bl=0.72, r_wl=0.72, r_drv=10.0, r_s=1.0).i_col
    assert np.allclose(both, np.concatenate([left, right]), rtol=1e-9)


def test_rail_droop_monotone_and_ideal_limit():
    g = np.full((8, 16), P.gap_lrs); pos = np.arange(500.0, 508.0)
    base = solve_mesh_ext(g, pos, P, r_bl=0.72, r_wl=0.72, r_drv=10.0, r_s=1.0).i_col.sum()
    tiny = solve_mesh_ext(g, pos, P, r_bl=0.72, r_wl=0.72, r_drv=10.0, r_s=1.0, r_rail=1e-9, r_gnd=1e-9).i_col.sum()
    assert tiny == pytest.approx(base, rel=5e-3)        # R_FLOOR (1e-4 ohm/pitch) x 500 pitches still drops ~0.15 mV: the ideal limit is only reached to that level
    prev = base
    for rr in (0.0007, 0.007, 0.07):
        cur = solve_mesh_ext(g, pos, P, r_bl=0.72, r_wl=0.72, r_drv=10.0, r_s=1.0, r_rail=rr, r_gnd=rr).i_col.sum()
        assert cur < prev
        prev = cur
    m = solve_mesh_ext(g, pos, P, r_bl=0.72, r_wl=0.72, r_drv=10.0, r_s=1.0, r_rail=0.007, r_gnd=0.007)
    assert np.all(m.v_rail < P.v_read) and np.all(m.v_gnd >= 0) and m.i_row.sum() == pytest.approx(m.i_col.sum(), rel=1e-9)   # supply current = sense current


def test_both_end_feed_and_drive_reduce_drop():
    g = np.full((8, 16), P.gap_lrs); pos = np.arange(500.0, 508.0)
    one = solve_mesh_ext(g, pos, P, r_bl=0.72, r_wl=0.72, r_drv=10.0, r_s=1.0, r_rail=0.05)
    two = solve_mesh_ext(g, pos, P, r_bl=0.72, r_wl=0.72, r_drv=10.0, r_s=1.0, r_rail=0.05, rail_length=513.0)
    assert (P.v_read - two.v_rail).max() < (P.v_read - one.v_rail).max()
    d1 = solve_mesh_ext(g, pos, P, r_bl=0.72, r_wl=0.72, r_drv=10.0, r_s=1.0)
    d2 = solve_mesh_ext(g, pos, P, r_bl=0.72, r_wl=0.72, r_drv=10.0, r_s=1.0, drive_both_ends=True)
    assert d2.i_col.sum() > d1.i_col.sum()


def test_mesh_ext_rejects_bad_blocks():
    with pytest.raises(ValueError):
        solve_mesh_ext(_gaps(2, 8), np.array([1.0, 2.0]), P, r_bl=0.72, r_wl=0.72, r_drv=10.0, blocks=(3, 3))


def test_macro_is_64_bitlines_and_160_cells():
    assert C.MACRO_BITLINES == 64 and C.FULL_CELLS == 160 and C.GROUPS_PER_COLUMN == 64 and C.N_MACROS * C.CELLS_PER_MACRO_ROW == 160


def test_group_table_levels_and_antisymmetry():
    from scaleup.column import build_group_table, decide
    t0 = build_group_table(8, 0, n_fit=6, n_held=6); t1 = build_group_table(8, 63, n_fit=6, n_held=6)
    assert t0["worst_step_full"] > 2.5 * t1["worst_step_full"] > 0                      # near-group step 3.6x the far group's (1B)
    for t in (t0, t1):
        for a in range(1, 9):
            lv = np.array(t["level"][str(a)]); assert np.all(np.diff(lv) > 0)          # levels strictly increase with m
            thr = np.array(t["thr"][str(a)]); assert np.all(lv[:-1] < thr) and np.all(thr < lv[1:])
        assert t["antisym_dev"] < 0.01 * t["span"]
    assert decide(t1, 8, t1["level"]["8"][3]) == 3 and decide(t1, 0, 1.0) == 0


def test_ragged_group_partition_covers_all_rows():
    from scaleup.column import group_rows, n_groups
    for g in (4, 5, 6, 7, 8, 24, 48):
        rows = np.concatenate([group_rows(g, G) for G in range(n_groups(g))])
        assert np.array_equal(rows, np.arange(512))


def test_accumulation_sum_equals_true_match_count():
    from scaleup.accumulate import read_column
    from scaleup.column import build_group_table, n_groups
    g = 8
    tabs = [build_group_table(g, G, n_fit=4, n_held=4) for G in (0, 21, 42, 63)]
    # a 4-group "column" of 32 rows keeps the test fast; the full 64-group test is scaleup/run_accumulate.py
    rng = np.random.default_rng(5); p = params_for(C.AREA_1C, C.RS_1C)
    import scaleup.column as col
    w = rng.random(512) < 0.5; x = np.zeros(512, bool); x[np.concatenate([np.arange(0, 8), np.arange(168, 176), np.arange(336, 344), np.arange(504, 512)])] = True
    class T(list): pass
    # rows of group Gi in this reduced test are mapped to the table of the same physical position
    m_true = m_hat = 0
    for G, tab in zip((0, 21, 42, 63), tabs):
        rows = col.group_rows(g, G); S = rows[x[rows]]; wS = w[S]
        i_d = col.pair_idiff(p, S, wS, 0.72)
        m_hat += col.decide(tab, len(S), i_d); m_true += int(wS.sum())
    assert m_hat == m_true


def test_budget_reclosure_reproduces_1b_final_margin():
    from scaleup.budget1c import close_1c, wire_terms
    t = wire_terms()
    row = {w: {"gain": t[f"row_gain_{w}"], "row_std_a": t[f"row_std_{w}_a"]} for w in ("far", "near")}
    r = close_1c(row)
    assert r["worst_group"] == "far" and r["margin_left_a"] == pytest.approx(0.80e-6, abs=0.03e-6) and r["closes"]


@pytest.mark.skipif(not ngspice_available(), reason="ngspice not installed")
def test_transient_steady_state_equals_dc_mesh():
    from scaleup.transient import TranConfig, build_tran_deck, currents, energy_to, run_tran
    p = params_for(20, 1.0)
    rows = np.arange(504, 512); pos = rows + 1.0
    w = np.random.default_rng(1).random(8) < 0.5
    gaps = np.where(np.stack([w, ~w], 1), p.gap_lrs, p.gap_hrs)
    res = run_tran(build_tran_deck(gaps, pos, p, TranConfig(t_stop=0.6e-9), 1.0, drive_both_ends=False), 2)
    dc = solve_mesh_ext(gaps, pos, p, r_bl=0.72, r_wl=0.72, r_drv=10.0, r_s=1.0).i_col
    assert np.allclose(currents(res, np.ones(2))[-1], dc, rtol=1e-6)
    # energy is the integral of V*I: after settling it grows linearly with the DC power
    e1, e2 = energy_to(res, 0.4e-9), energy_to(res, 0.6e-9)
    assert (e2 - e1) == pytest.approx(0.2e-9 * p.v_read * dc.sum(), rel=1e-3)


@pytest.mark.skipif(not ngspice_available(), reason="ngspice not installed")
def test_mesh_ext_matches_ngspice_on_a_small_array():
    from wire.validate_mesh_ext import one_case
    rng = np.random.default_rng(7)
    for c in range(6):
        r = one_case(c, rng)
        assert r["rel_icol"] < 1e-6 and r["rel_irow"] < 1e-5


def test_variant_distance_functions_and_far_groups():
    from scaleup.variants import dist_fn, far_group_rows
    assert dist_fn("end")(0) == 1.0 and dist_fn("end")(511) == 512.0
    f = dist_fn("centre")
    assert f(255) == f(256) == 1.0 and f(0) == f(511) == 256.0       # nearest rows 1 pitch from the node, farthest rows 256
    f2 = dist_fn("seg2_end")
    assert f2(0) == f2(256) == 1.0 and f2(255) == f2(511) == 256.0
    assert dist_fn("seg4_mid")(64) < 5 and dist_fn("seg4_mid")(0) > 60
    far = far_group_rows("centre", 8)
    assert far[0] in (0, 504) and len(far) == 8                       # the far group of a centre-tapped column is at an end of the column


def test_area_model_ranking_holds_at_every_density_assumption():
    from scaleup.area import area
    for lv in range(3):
        parts = area(level=lv)["parts_um2"]
        assert parts["row_drivers"] == max(v for k, v in parts.items() if k != "overhead_20pct")
        assert parts["cell_array"] < 0.1 * sum(parts.values())
    assert area(r_drv=20.0)["parts_um2"]["row_drivers"] == pytest.approx(area(r_drv=10.0)["parts_um2"]["row_drivers"] / 2)
    assert area(r_drv=2.0, both_ends=False)["total_mm2"] > area()["total_mm2"]


def test_cycle_model_fits_1e_regressions():
    from pathlib import Path
    reg = Path(__file__).resolve().parents[2] / "03_rtl" / "results" / "regression"
    if not (reg / "dvs_seed0_g8_c160.json").exists():
        pytest.skip("1E regression results not present")
    from scaleup.c5_decision import cycle_model
    cm = cycle_model()
    assert cm["c0_spread"] < 3                                        # cycles = C0 + group reads for every g and column mode, to within 2 cycles
    assert cm["c0"] + cm["reads_160"] == pytest.approx(cm["runs"]["dvs_seed0_g8_c160"]["cycles"], abs=2)
    assert cm["c0"] + 8 * cm["reads_160"] == pytest.approx(cm["runs"]["dvs_seed0_g8_c20"]["cycles"], abs=3)


def test_recorded_final_design_budget_is_marginal_but_closes():
    from paths import MACRO
    import json
    f = MACRO / "budget_final_design.json"
    if not f.exists():
        pytest.skip("run scaleup.c2_budget first")
    b = json.loads(f.read_text())["baseline"]
    assert b["closes"] and 0.0 < b["margin_left_a"] < 0.80e-6          # closes (g stays 8), with less margin than 1B left
    assert not all(x["closes"] for x in json.loads(f.read_text())["vs_rail"])   # and it is not insensitive to the rails
