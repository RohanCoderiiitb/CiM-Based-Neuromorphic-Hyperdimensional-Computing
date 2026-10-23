"""The crossbar netlist generator (design/crossbar/crossbar_netlist): structure, defaults from constants.py, and agreement with the mesh solver on small arrays (ngspice needed for the last four)."""
import numpy as np
import pytest

import device.constants as C
from device.constants import DEFAULT
from spice.runner import ngspice_available
from spice.xbar import ArraySpec, TranSpec, device_resistance, full_deck, reduced_deck, run_full_op, weights_to_gaps
from wire.mesh import solve_mesh_ext


def test_defaults_are_the_constants():
    s = ArraySpec()
    assert s.rows == C.ROWS_TOTAL and s.blocks == (C.MACRO_BITLINES,) * C.N_MACROS and s.g == C.G_1C and s.K == 2 * C.FULL_CELLS
    assert s.r_bl == C.BL_R_PER_PITCH_1C and s.r_drv == C.R_DRV_DEFAULT and s.r_rail == C.RAIL_R_DEFAULT and s.r_s == C.RS_1C
    assert s.p.r_tx == C.RTX_BY_AREA[C.AREA_1C] and s.n_groups == C.GROUPS_PER_COLUMN


def test_resistor_flavour_values_are_the_secant_of_the_device_law():
    assert device_resistance(C.GAP_LRS) == pytest.approx(541.82, abs=0.01)         # 1A: 541.8 ohm
    assert device_resistance(C.GAP_HRS) == pytest.approx(218586.0, abs=1.0)        # 1A: 218,586 ohm


def test_hierarchy_levels_are_emitted():
    rng = np.random.default_rng(0)
    spec = ArraySpec(rows=16, blocks=(8, 8), g=8)
    gaps = weights_to_gaps(rng.integers(0, 2, (16, 8)).astype(bool))
    deck, probes = full_deck(spec, gaps, np.arange(8, 16))
    for token in (".subckt half ", ".subckt cell2t2r ", ".subckt grp2_8 ", ".subckt rowline8 ", ".subckt macro0 ", ".subckt macro1 ", ".subckt array ", "Xm0 ", "Xm1 "):
        assert token in deck, token
    assert deck.count("Vwl") == 16 and len(probes["sense"]) == 16
    assert "St x bl wl 0 swtx" in deck, "the access transistor must sit between the device and the BIT line, gated by the word line"
    assert "Bd rl x" in deck and deck.index("Bd rl x") < deck.index("St x bl wl 0 swtx")


def test_last_group_may_be_shorter():
    spec = ArraySpec(rows=20, blocks=(4,), g=8)
    deck, _ = full_deck(spec, np.full((20, 4), DEFAULT.gap_hrs), [0])
    assert ".subckt grp2_8 " in deck and ".subckt grp2_4 " in deck


def _case(rng, R, blocks, act_n, **kw):
    spec = ArraySpec(rows=R, blocks=blocks, g=8, **kw)
    K = spec.K
    w = rng.integers(0, 2, (R, K // 2 + 1)).astype(bool)
    stored = np.repeat(w, 2, axis=1)[:, :K] ^ (np.arange(K)[None, :] % 2 == 1)
    gaps = np.where(stored, DEFAULT.gap_lrs, DEFAULT.gap_hrs) - DEFAULT.g0 * 0.1 * rng.standard_normal((R, K))
    act = np.sort(rng.choice(R, act_n, replace=False))
    return spec, gaps, act


def _solver(spec, gaps, act):
    return solve_mesh_ext(gaps[act], act + 1.0, spec.p, r_bl=spec.r_bl, r_wl=spec.r_wl, r_drv=spec.r_drv, r_s=spec.rs, blocks=spec.blocks, r_rail=spec.r_rail, rail_pos=spec.rail_pos_arr[act],
                          rail_length=spec.rail_len, r_gnd=spec.r_gnd, gnd_pad_per_block=spec.gnd_pad_per_block, drive_both_ends=spec.drive_both_ends)


@pytest.mark.skipif(not ngspice_available(), reason="ngspice not installed")
def test_full_hierarchy_agrees_with_the_mesh_solver_including_odd_block_widths():
    rng = np.random.default_rng(3)
    for blocks in ((8,), (8, 6), (6, 5, 5)):
        spec, gaps, act = _case(rng, 24, blocks, 5, r_rail=0.5, r_gnd=0.2, rail_feed_both_ends=True)
        ng, m = run_full_op(spec, gaps, act), _solver(spec, gaps, act)
        assert np.max(np.abs(ng["i_col"] / m.i_col - 1)) < 1e-8
        assert np.max(np.abs(ng["i_row"] / m.i_row - 1)) < 1e-7
        assert np.max(np.abs(ng["v_rail"] - m.v_rail)) < 1e-10


@pytest.mark.skipif(not ngspice_available(), reason="ngspice not installed")
def test_ideal_rails_and_single_driver():
    rng = np.random.default_rng(4)
    spec, gaps, act = _case(rng, 16, (8,), 4, r_rail=None, r_gnd=None, rail_feed_both_ends=False, drive_both_ends=False)
    ng, m = run_full_op(spec, gaps, act), _solver(spec, gaps, act)
    assert np.max(np.abs(ng["i_col"] / m.i_col - 1)) < 1e-8


@pytest.mark.skipif(not ngspice_available(), reason="ngspice not installed")
def test_resistor_flavour_equals_the_solver_on_a_linear_device():
    rng = np.random.default_rng(5)
    spec, gaps, act = _case(rng, 16, (8,), 4, device="resistor", r_rail=None, r_gnd=None, rail_feed_both_ends=False)
    ng = run_full_op(spec, gaps, act)
    R = spec.gap_to_state(gaps)[act]
    p = spec.p.with_(i0=1e6, v0=1e6, gmin=0.0)
    m = solve_mesh_ext(p.g0 * np.log(R), act + 1.0, p, r_bl=spec.r_bl, r_wl=spec.r_wl, r_drv=spec.r_drv, r_s=spec.rs, blocks=spec.blocks, drive_both_ends=True)
    assert np.max(np.abs(ng["i_col"] / m.i_col - 1)) < 1e-8


@pytest.mark.skipif(not ngspice_available(), reason="ngspice not installed")
def test_reduced_transient_settles_to_the_full_dc_solution():
    from scaleup.transient import TranConfig, build_tran_deck, currents, run_tran
    rng = np.random.default_rng(6)
    spec, gaps, act = _case(rng, 32, (8,), 4, r_rail=None, r_gnd=None, rail_feed_both_ends=False, drive_both_ends=True, r_s=1.0)
    ng = run_full_op(spec, gaps, act)
    res = run_tran(build_tran_deck(gaps[act], act + 1.0, spec.p, TranConfig(t_stop=0.8e-9, bl_len=32), 1.0, blocks=(8,)), 8)
    assert np.allclose(currents(res, np.ones(8))[-1], ng["i_col"], rtol=1e-5)
