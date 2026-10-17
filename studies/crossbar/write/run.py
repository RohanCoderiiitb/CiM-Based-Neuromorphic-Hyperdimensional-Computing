"""1D-i: run row-write decks (write/rowdeck.py) and turn node voltages into per-bitline quantities."""
from __future__ import annotations

import numpy as np

from spice import osdi
from write import rowdeck as RD


def _run_op(deck: str, timeout: float = 1800.0) -> dict:
    out = osdi.run(deck + "\n.control\npre_set num_threads=1\nset noaskquit\nset numdgt=12\nop\nprint all\n.endc\n.end\n", timeout=timeout)
    s = osdi.scalars(out)
    if "rt" not in s:
        raise osdi.ToolchainError("row deck failed:\n" + "\n".join(out.splitlines()[-30:]))
    return s


def dc(w: RD.RowWrite, targets, r_dev) -> dict:
    """DC snapshot. Returns per-bitline device voltage, device current, access-transistor terminal voltages, and the rail / driver numbers."""
    targets = np.asarray(targets, bool)
    r_dev = np.asarray(r_dev, float)
    s = _run_op(RD.build(w, targets, r_dev=r_dev))
    v = lambda n: s[n.lower()]
    top = np.array([v(f"w{j // RD.BL_PER_MACRO}_{j % RD.BL_PER_MACRO}") for j in range(RD.N_BL)])
    mid = np.array([v(f"d{j}") for j in range(RD.N_BL)])
    bot = np.array([v(f"x{j}") for j in range(RD.N_BL)])
    e = np.array([v(f"e{j}") if f"e{j}" in s else np.nan for j in range(RD.N_BL)])
    if w.orientation == "bl":
        v_dev, v_tx_d, v_tx_s = top - mid, mid, bot
    else:
        v_dev, v_tx_d, v_tx_s = mid - bot, top, mid
    i_dev = v_dev / r_dev
    vds = np.abs(v_tx_d - v_tx_s)
    vgd = np.maximum(np.abs(w.v_wl - v_tx_d), np.abs(w.v_wl - v_tx_s))
    v_rt = v("rt")
    i_row = float(np.sum(np.where(np.isfinite(e), 0, 0)))   # placeholder (not used)
    i_supply = (v("pad") - v_rt) / RD.rail_r_eff(w.r_rail, w.row) if RD.rail_r_eff(w.r_rail, w.row) > 1e-6 else float("nan")
    drv = []
    for m in range(RD.N_MACROS):
        drv += [abs(v_rt - v(f"w{m}_0")) / w.r_wdrv, abs(v_rt - v(f"w{m}_{RD.BL_PER_MACRO - 1}")) / w.r_wdrv]
    return dict(v_dev=v_dev, i_dev=i_dev, v_row=top, v_bl_cell=bot, v_ds=vds, v_gate_term=vgd, v_rail_tap=v_rt, v_rail_droop=abs(v("pad") - v_rt),
                i_supply=abs(i_supply), i_driver_max=float(max(drv)), v_driver_drop_max=float(max(drv) * w.r_wdrv), raw=s)


def tran(w: RD.RowWrite, targets, behavioural: dict, t_rise: float, t_flat: float, t_stop: float, probes: list[str], timeout: float = 3600.0) -> dict:
    deck = RD.build(w, np.asarray(targets, bool), behavioural=behavioural, tran=(t_rise, t_flat, t_stop))
    return osdi.run_wrdata(deck.splitlines(), probes, timeout=timeout)
