"""ngspice runs of the 2-D mesh. The decks are NOT built here: they come from the crossbar netlist generator (design/crossbar/crossbar_netlist, via spice.xbar), so the
study code and the design artefact cannot drift apart. This module only translates the mesh solver's arguments into an ArraySpec."""
from __future__ import annotations

import numpy as np

from device.constants import DEFAULT, Params
from spice.xbar import ArraySpec, run_full_op


def mesh_spec(R: int, K: int, p: Params, r_bl: float, r_wl: float, r_drv: float, r_s=None, r_tx: float | None = None) -> ArraySpec:
    """One block of K bitlines, ideal supply and ground, one driver per row at column 0: the 1B mesh (solve_mesh). g is irrelevant to the electrical network."""
    p = p.with_(r_tx=p.r_tx if r_tx is None else r_tx)
    rs = tuple(np.broadcast_to(np.asarray(p.r_s if r_s is None else r_s, dtype=float), (K,)))
    return ArraySpec(rows=R, blocks=(K,), p=p, r_bl=r_bl, r_wl=r_wl, r_drv=r_drv, r_rail=None, r_gnd=None, rail_feed_both_ends=False, r_s=rs, drive_both_ends=False)


def run_mesh_ngspice(gaps, active, p: Params = DEFAULT, *, r_bl: float, r_wl: float, r_drv: float, r_s=None, r_tx: float | None = None) -> np.ndarray:
    """Column currents (K,) from ngspice for the full-physical-array mesh (every physical row present, inactive rows' word lines low)."""
    gaps = np.asarray(gaps, dtype=float); active = np.asarray(active, dtype=bool)
    R, K = gaps.shape
    return run_full_op(mesh_spec(R, K, p, r_bl, r_wl, r_drv, r_s, r_tx), gaps, active)["i_col"]
