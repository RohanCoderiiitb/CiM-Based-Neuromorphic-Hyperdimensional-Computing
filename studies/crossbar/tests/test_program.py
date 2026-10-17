"""1D-i / 1D-ii tests. The toolchain-dependent ones skip when OpenVAF/ngspice cannot be resolved (spice/osdi.py)."""
from __future__ import annotations

import numpy as np
import pytest

from program import model as M
from program import verify as V


def test_mirror_reproduces_1a_read_resistances():
    assert abs(M.r_read(0.2) - 541.82) < 0.01
    assert abs(M.r_read(1.7) / 218586.0 - 1) < 1e-5
    assert abs(M.gap_for_r(M.r_read(0.9)) - 0.9) < 1e-6      # GMIN neglected in the inverse


def test_physical_rate_is_zero_at_zero_bias_and_odd_in_v():
    g = np.linspace(0.3, 1.6, 7)
    assert np.all(M.physical_rate_nm_s(0.0, g) == 0.0)
    assert np.allclose(M.physical_rate_nm_s(0.3, g), -M.physical_rate_nm_s(-0.3, g))


def test_window_is_symmetric_in_log_conductance():
    lo, hi = V.window_gaps(0.35, 0.05)
    assert np.isclose(np.exp(-(lo - 0.35) / 0.25), 1.05) and np.isclose(np.exp(-(hi - 0.35) / 0.25), 0.95)


def test_maps_are_exact_at_grid_points():
    gaps = np.linspace(0.2, 1.7, 11)
    widths = np.array([1e-6, 1e-5, 1e-4])
    volts = np.array([1.0, 1.1])
    rng = np.random.default_rng(0)
    go = np.sort(rng.random((2, 3, 11)), axis=-1)
    t = dict(gaps=gaps, widths=widths, volts=volts, gap_out=go, energy_j=go * 0)
    m = V.Maps(t, t)
    g_new, _ = m.step("set", np.array([1, 0]), np.array([1e-5, 1e-4]), np.array([gaps[3], gaps[7]]))
    assert np.allclose(g_new, [go[1, 1, 3], go[0, 2, 7]])


def test_sigma_hrs_default_reproduces_single_sigma():
    from drift.model import draw_z4, mc_levels_drift
    from margin.core import params_for
    p = params_for(20, 1.0)
    z4 = draw_z4(4, 200)
    a = mc_levels_drift(4, 4, p, 0.1, 0.0, 0.0, 0.0, z4)
    b = mc_levels_drift(4, 4, p, 0.1, 0.0, 0.0, 0.0, z4, sigma_hrs=0.1)
    c = mc_levels_drift(4, 4, p, 0.1, 0.0, 0.0, 0.0, z4, sigma_hrs=0.5)
    assert np.allclose(a["std_diff"], b["std_diff"]) and not np.allclose(a["std_diff"], c["std_diff"])


def test_row_deck_structure():
    from write import rowdeck as RD
    tg = np.zeros(RD.N_BL, bool); tg[::2] = True
    deck = RD.build(RD.RowWrite(), tg, r_dev=np.full(RD.N_BL, RD.R_HRS))
    import re
    assert len(re.findall(r"^M\d+ .* ptm45n_lp ", deck, re.M)) == RD.N_BL
    assert len(re.findall(r"^Rd\d[ab] ", deck, re.M)) == 2 * RD.N_MACROS          # both-end drivers per macro row


def _toolchain():
    try:
        from spice import osdi
        osdi.check_ngspice()
        osdi.build_osdi()
        return osdi
    except Exception:          # noqa: BLE001
        return None


def test_compiled_model_reproduces_1a():
    osdi = _toolchain()
    if osdi is None:
        pytest.skip("OpenVAF / ngspice >= 38 not available")
    from program.d0_validate import read_r
    assert abs(read_r(osdi.OSDI, 0.2) / 541.82 - 1) < 1e-4
    assert abs(read_r(osdi.OSDI, 1.7) / 218586.0 - 1) < 1e-4
