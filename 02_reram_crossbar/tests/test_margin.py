"""1B-i: constants provenance, level structure, ladder, point evaluation, consistency with 1A."""
import json
from pathlib import Path

import numpy as np
import pytest

import device.constants as C
from margin import ladder as LD
from margin.core import RS_ZERO, draw_z, gap_hrs_for_ratio, levels, mc_levels, params_for, worst_step
from margin.point import evaluate_point

RES = Path(__file__).resolve().parents[1] / "results"


def test_rtx_and_ilrs_tables_match_1a_json():
    tr = RES / "transistor.json"
    if not tr.exists():
        pytest.skip("transistor.json not generated")
    for r in json.loads(tr.read_text())["rows"]:
        assert C.RTX_BY_AREA[r["area_f2"]] == pytest.approx(r["rtx_lrs"], abs=0.01)
        assert C.ILRS_BY_AREA_A[r["area_f2"]] == pytest.approx(r["i_lrs"], rel=1e-3)


def test_rtx_times_w_is_roughly_constant():
    prod = [C.RTX_BY_AREA[a] * C.TX_FILL * a * C.FEATURE_NM * 1e-3 for a in C.AREA_SWEEP_F2]
    assert max(prod) / min(prod) < 1.02 and 540 < np.mean(prod) < 555


def test_regression_against_1a_worst_step_g32():
    # 1A section 7 (R_tx 505.79, R_s 20, g 32): worst differential step 110.5 uA at m = 16, worst/uncompressed gap 0.587
    p = params_for(40, 20.0)
    d, loc = worst_step(levels(32, 32, p)["i_diff"])
    assert d == pytest.approx(110.5e-6, rel=2e-3) and loc in (16, 17)
    r = evaluate_point(32, 40, 20.0, 0.0)
    assert r["delta_norm"] == pytest.approx(0.587, abs=2e-3)
    assert r["cmrr_req_db"] == pytest.approx(40.4, abs=0.3)          # 1A: ~40 dB at g = 32


def test_levels_antisymmetric_and_monotone():
    L = levels(16, 16, params_for(60, 5.0))["i_diff"]
    assert np.allclose(L, -L[::-1], atol=1e-15)
    assert np.all(np.diff(L) > 0)


def test_inactive_rows_carry_no_branch_levels_depend_on_a_only():
    p = params_for(40, 10.0)
    assert np.allclose(levels(32, 8, p)["i_diff"], levels(8, 8, p)["i_diff"])      # g does not matter, only the active count


def test_mc_sigma_zero_equals_nominal_and_sigma_scales():
    p = params_for(40, 10.0)
    z = draw_z(8, 400)
    m0 = mc_levels(8, 8, p, 0.0, z)
    assert np.allclose(m0["mean_diff"], levels(8, 8, p)["i_diff"], rtol=1e-12) and np.all(m0["std_diff"] < 1e-18)
    s1, s2 = mc_levels(8, 8, p, 0.05, z)["std_diff"], mc_levels(8, 8, p, 0.10, z)["std_diff"]
    assert np.all(s2 / s1 > 1.9) and np.all(s2 / s1 < 2.1)            # error ~ linear in sigma for small sigma


def test_spread_std_matches_independent_estimate():
    # variance of I_diff ~ a * (dI/dlnG)^2 sigma^2 at the middle; dI/dlnG ~ I_LRS*R_L/(R_L+R_tx) (small compression): 1A numbers at g=2
    p = params_for(40, 1.0)
    z = draw_z(2, 20000)
    std = mc_levels(2, 2, p, 0.05, z)["std_diff"][1]
    i_l = 9.27e-5
    est = np.sqrt(2) * 0.05 * i_l * 542.0 / (542.0 + 505.79) * 1.0
    assert std == pytest.approx(est, rel=0.15)


def test_ladder_decides_every_nominal_level_and_uniform_does_not_when_compressed():
    L = levels(32, 32, params_for(40, 50.0))["i_diff"]
    t = LD.weighted_thresholds(L)
    assert np.array_equal(LD.decide(L, t), np.arange(33))
    assert np.all(LD.margins(L, t)["dist"] > 0)
    tu = LD.uniform_thresholds(L)
    assert LD.margins(L, tu)["dist"].min() < LD.margins(L, t)["dist"].min()      # non-uniform wins at heavy compression


def test_weighted_threshold_hand_case():
    L = np.array([0.0, 10.0, 30.0])
    assert np.allclose(LD.weighted_thresholds(L), [5.0, 20.0])                        # midpoints
    # sigma 1 vs 3 between levels 0 and 10 -> threshold at 10*1/(1+3) = 2.5, equal margin in sigma units (2.5/1 == 7.5/3)
    assert LD.weighted_thresholds(np.array([0.0, 10.0]), np.array([1.0, 3.0]))[0] == pytest.approx(2.5)


def test_leakage_residual_zero_when_ratio_tolerance_zero_and_gap_helper():
    r = evaluate_point(8, 40, 10.0, 0.0, ratio_tol=0.0)
    assert r["leak_resid_a"] == 0.0 and r["leak_raw_shift_a"] > 0
    from device.model import on_off_ratio
    assert on_off_ratio(0.2, gap_hrs_for_ratio(181.3)) == pytest.approx(181.3, rel=1e-6)
    assert gap_hrs_for_ratio(C.RATIO_CEILING) == C.GAP_HRS


def test_compression_not_in_budget_terms():
    r = evaluate_point(16, 40, 20.0, 0.1, n=300)
    assert r["delta_norm"] < 1.0                                            # compression lives in Delta ...
    from margin.point import BUDGET_TERMS     # ... and no budget term is named for it:
    assert not any("compress" in n.lower() for n in BUDGET_TERMS)


def test_ok_requires_both_budget_and_cmrr():
    r = evaluate_point(32, 40, 5.0, 0.0, cmrr_db=10.0)       # absurdly low achievable CMRR must rule the point out
    assert r["budget_closes"] and not r["cmrr_ok"] and not r["ok"]
