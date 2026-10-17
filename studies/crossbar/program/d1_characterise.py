"""1D-ii D1: forming, SET and RESET with the compiled model inside the array's delivery envelope (1D-i), and what a different array would need.

(a) Forming: rram.va has no forming - no pristine state, no forming voltage (the gap starts wherever the initial condition puts it, inside [0.2, 1.7] nm). Named as ABSENT.
(b)/(c) SET and RESET maps come from the main pulse tables (program/tables.py: the 1D-i cell, bitline-side 20 F^2 transistor, word line 1.1 V, far row): the state reached
    from HRS (SET) and from an LRS (RESET) for every amplitude x width, the energy, the peak current and the transistor's terminal voltage (flagged above 1.1 V).
    The design states of 1A (gap 0.2 / 1.7 nm) sit ON the model's clamps; the nearest states the model can hold away from them are taken as 'design-adjacent':
    0.35 nm (987 ohm) and 1.55 nm (120 kohm), ratio 121 (1B: the ratio must stay above 92 at g = 8).
    Out-of-envelope sweep (this script): access width 0.54 (20 F^2) ... 5.4 um and word line 1.1 ... 2.5 V - the write device that would reach the design-adjacent states
    within 1 us. Everything beyond 20 F^2 / 1.1 V is a DIFFERENT ARRAY.
(d) Gradual or abrupt: the gap change per pulse as a function of amplitude, from the tables.
Usage: python -m program.d1_characterise"""
from __future__ import annotations

import itertools
import json
from multiprocessing import Pool

import numpy as np

import paths as RP
from program import tables as T
from program.cell import Cell, run_pulse

W_UM = (0.54, 1.08, 2.7, 5.4, 10.8)            # 20, 40, 100, 200, 400 F^2 (fill 0.6, 1A)
V_WL = (1.1, 1.8, 2.5, 3.0)
R_BL = (379.0, 11.0)             # ohm: far row (the 1D-i worst case) and near row
WIDTHS = (1e-8, 1e-7, 1e-6)
VOLTS = tuple(np.round(np.arange(0.8, 2.41, 0.2), 2))
G_LRS_ADJ, G_HRS_ADJ = 0.35, 1.55


def _job(a):
    w, vwl, direction, v, tw, rbl = a
    c = T.CELL.with_(w_um=w, v_wl=vwl, r_bl=rbl)
    g_in = (1.7, 1.55) if direction == "set" else (0.2, 0.35, 0.6, 1.0, 1.3)
    try:
        r = run_pulse(c, direction, v, tw, g_in)
        return dict(w_um=w, v_wl=vwl, r_bl=rbl, direction=direction, v=v, width=tw, gap_in=list(g_in), gap_out=r["gap_out"].tolist(), i_peak=r["i_peak_a"].tolist(),
                    v_tx_max=r["v_tx_max"].tolist(), v_gate_max=r["v_gate_max"].tolist(), energy=r["energy_j"].tolist())
    except Exception as e:     # noqa: BLE001
        return dict(w_um=w, v_wl=vwl, r_bl=rbl, direction=direction, v=v, width=tw, error=str(e)[-200:])


def in_envelope_maps() -> dict:
    t = T.main_tables()
    out = {}
    for d, tb in t.items():
        g0 = 1.7 if d == "set" else 0.35
        k = int(np.argmin(np.abs(tb["gaps"] - g0)))
        out[d] = dict(volts=tb["volts"].tolist(), widths=tb["widths"].tolist(), gap_in=float(tb["gaps"][k]), gap_out=tb["gap_out"][:, :, k].tolist(),
                      energy=tb["energy_j"][:, :, k].tolist(), i_peak=tb["i_peak_a"][:, :, k].tolist(), v_tx_max=tb["v_tx_max"][:, :, k].tolist())
        # from the in-envelope LRS (the state 1 us at 1.3 V reaches from HRS) for RESET
        if d == "reset":
            k2 = int(np.argmin(np.abs(tb["gaps"] - 1.3)))
            out["reset_from_1.3"] = dict(gap_in=float(tb["gaps"][k2]), gap_out=tb["gap_out"][:, :, k2].tolist(), energy=tb["energy_j"][:, :, k2].tolist())
            k3 = int(np.argmin(np.abs(tb["gaps"] - 0.6)))
            out["reset_from_0.6"] = dict(gap_in=float(tb["gaps"][k3]), gap_out=tb["gap_out"][:, :, k3].tolist(), energy=tb["energy_j"][:, :, k3].tolist())
    # (d) gradualness: per-pulse gap change at the design-adjacent and in-envelope targets, vs amplitude, at 1 us and 1 ms
    grad = {}
    for d, tb in t.items():
        for gt in (0.35, 0.6, 1.3, 1.55):
            k = int(np.argmin(np.abs(tb["gaps"] - gt)))
            for tw in (1e-6, 1e-4, 1e-3):
                j = int(np.argmin(np.abs(np.log(tb["widths"] / tw))))
                grad[f"{d}|{gt}|{tw:g}"] = dict(volts=tb["volts"].tolist(), dgap=(tb["gap_out"][:, j, k] - tb["gaps"][k]).tolist())
    out["gradual"] = grad
    return out


def main() -> None:
    RP.PROGRAM.mkdir(parents=True, exist_ok=True)
    env = in_envelope_maps()
    J = list(itertools.product(W_UM, V_WL, ("set", "reset"), VOLTS, WIDTHS, R_BL))
    with Pool(30) as p:
        rows = p.map(_job, J, chunksize=2)
    # smallest write device reaching the design-adjacent states within 1 us
    need = {}
    for (d, g_target, gi), tw, rbl in itertools.product((("set", G_LRS_ADJ, 0), ("reset", G_HRS_ADJ, 1)), WIDTHS, R_BL):
        if True:
            ok = [r for r in rows if "error" not in r and r["direction"] == d and r["width"] == tw and r["r_bl"] == rbl
                  and ((r["gap_out"][gi] <= g_target) if d == "set" else (r["gap_out"][gi] >= g_target))]
            ok.sort(key=lambda r: (r["w_um"], r["v_wl"], r["v"]))
            need[f"{d}|{tw:g}|{rbl:g}"] = None if not ok else dict(w_um=ok[0]["w_um"], v_wl=ok[0]["v_wl"], v=ok[0]["v"], gap_out=ok[0]["gap_out"][gi],
                                                           i_peak=ok[0]["i_peak"][gi], v_tx_max=ok[0]["v_tx_max"][gi], v_gate_max=ok[0]["v_gate_max"][gi])
    out = dict(forming="absent from rram.va: no pristine state, no forming dynamics", envelope=env, sweep=rows, need=need,
               design_adjacent=dict(lrs_gap=G_LRS_ADJ, hrs_gap=G_HRS_ADJ))
    (RP.PROGRAM / "d1_characterise.json").write_text(json.dumps(out, indent=1))
    for k, v in need.items():
        print("needs:", k, v)
    print("errors", sum("error" in r for r in rows))


if __name__ == "__main__":
    main()
