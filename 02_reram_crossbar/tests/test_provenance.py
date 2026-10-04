"""Provenance and spread tests (no ngspice needed)."""
import json
from pathlib import Path

import numpy as np
import pytest

import device.constants as C
from device.spread import resistance_cv, sample_gaps, sigma_gap_from_lng

RES = Path(__file__).resolve().parents[1] / "results"


def test_r_tx_matches_simulated_value():
    tr = RES / "transistor.json"
    if not tr.exists():
        pytest.skip("results/transistor.json not generated")
    nom = json.loads(tr.read_text())["nominal"]
    assert nom["area_f2"] == C.CELL_AREA_F2 and abs(nom["w_um"] - C.TX_W_UM) < 1e-9
    assert nom["rtx_lrs"] == pytest.approx(C.R_TX, abs=0.01)


def test_width_rule_matches_brief_table():
    from spice.transistor import rdsw_floor_ohm, width_um
    assert width_um(20, 0.6, 45) == pytest.approx(0.54)
    assert width_um(100, 0.6, 45) == pytest.approx(2.70)
    assert rdsw_floor_ohm(0.54) == pytest.approx(388.9, abs=0.1)


def test_lognormal_spread_is_unclipped_and_hits_requested_sigma():
    rng = np.random.default_rng(0)
    for sigma in (0.05, 0.10, 0.20):
        gaps = sample_gaps(rng, np.full(400000, C.GAP_LRS), sigma)
        assert np.std(np.log(np.exp(-gaps / C.G0))) == pytest.approx(sigma, rel=0.01)
        assert np.mean(gaps == C.MIN_GAP) == 0.0              # nothing piles up on the model limit
        assert np.std(gaps) == pytest.approx(sigma_gap_from_lng(sigma), rel=0.01)   # sigma_lnG = sigma_gap/g0
    assert resistance_cv(0.04) == pytest.approx(0.04, rel=1e-2)


def test_sigma_zero_is_exactly_nominal():
    g = sample_gaps(np.random.default_rng(1), np.full(10, 0.2), 0.0)
    assert np.all(g == 0.2)
