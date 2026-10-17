"""1D-i D2: the non-target bitlines of the selected row during a row-parallel write.

In a row-parallel SET every cell has one target device (its LRS device) and one non-target (its partner) on the other bitline; with a partial row (n_par < 160) whole cells
are non-targets. Three ways to handle a non-target bitline, measured on the full row deck at the write voltage:
  float   : bitline driver off. The bitline (512 x 0.2 fF) charges toward the row line through the non-target device + access transistor (the word line is shared, so
            that transistor is ON): the device sees nearly the full write voltage until the bitline catches up. Transient (ngspice), device held at its state
            (fixed resistor) so the WAVEFORM is measured; disturb = time the device spends above a threshold vth, compared with the swept tmin.
  clamp0  : bitline held at 0 V. Each clamped device sees the full write voltage for the whole pulse (it is being written) and is a DC load (V/(R_dev+R_tx), transistor-limited).
  inhibit : bitline driven to the row-line level (V-inhibit, zero volts nominally) or to v_drive/2 (V/2-inhibit). Residual = IR mismatch between the ideal inhibit
            level and the drooping row line, and for V/2 the half-select voltage itself.
Usage: python -m write.d2_unselected"""
from __future__ import annotations

import itertools
import json
from multiprocessing import Pool

import numpy as np

import paths as RP
from write import d1_parallel as D1, rowdeck as RD, run as R

V_DRIVE = (1.0, 1.2, 1.4, 1.6, 1.8, 2.0, 2.2)
V_TH = D1.V_TH
T_RISE, T_FLAT = 1e-9, 1e-6


def probe_bitlines(tg: np.ndarray) -> list[int]:
    """Non-target bitlines at the start, middle and end of macros 0 and 4."""
    nt = np.flatnonzero(~tg)
    picks = []
    for m in (0, 4):
        idx = nt[(nt >= m * 64) & (nt < (m + 1) * 64)]
        picks += [int(idx[0]), int(idx[np.argmin(np.abs(idx - m * 64 - 31.5))]), int(idx[-1])]
    return picks


def _float_job(a):
    v, state, row = a
    w = RD.RowWrite(v_drive=v, row=row, unselected="float")
    tg = D1.set_targets(D1.weights())
    pr = probe_bitlines(tg)
    r_dev = np.where(tg, RD.R_HRS, RD.R_LRS if state == "LRS" else RD.R_HRS)
    deck = RD.build(w, tg, r_dev=r_dev, tran=(T_RISE, T_FLAT, 2 * T_RISE + T_FLAT + 50e-9))
    probes = []
    for j in pr:
        m, k = divmod(j, 64)
        probes += [f"v(w{m}_{k})", f"v(d{j})"]
    from spice import osdi
    d = osdi.run_wrdata(deck.splitlines(), probes)
    t = d["time"]
    out = dict(v_drive=v, state=state, row=row, bitlines=pr, curves={})
    for j in pr:
        m, k = divmod(j, 64)
        vd = d[f"v(w{m}_{k})"] - d[f"v(d{j})"]
        above = {}
        for vth in V_TH:
            mask = vd > vth
            above[f"{vth}"] = float(np.sum(np.diff(t)[mask[:-1]])) if mask.any() else 0.0
        sel = np.unique(np.concatenate([np.searchsorted(t, np.logspace(-11, np.log10(t[-1]), 160)).clip(0, len(t) - 1)]))
        out["curves"][str(j)] = dict(t=t[sel].tolist(), v_dev=vd[sel].tolist(), peak=float(vd.max()), time_above_s=above)
    return out


def _dc_job(a):
    v, mode, row, state = a
    kw = dict(v_drive=v, row=row)
    if mode == "clamp0":
        kw["unselected"] = "clamp0"
    elif mode == "inhibit_V":
        kw["unselected"] = "inhibit"
    elif mode == "inhibit_V2":
        kw.update(unselected="inhibit", v_inh=v / 2)
    w = RD.RowWrite(**kw)
    tg = D1.set_targets(D1.weights())
    res = {}
    for snap in ("before", "after"):
        r_dev = np.where(tg, RD.R_HRS if snap == "before" else RD.R_LRS, RD.R_LRS if state == "LRS" else RD.R_HRS)
        d = R.dc(w, tg, r_dev)
        nt = ~tg
        res[snap] = dict(nontarget_vdev_max=float(np.abs(d["v_dev"][nt]).max()), nontarget_vdev_min_signed=float(d["v_dev"][nt].min()), nontarget_vdev_max_signed=float(d["v_dev"][nt].max()),
                         nontarget_i_total=float(np.abs(d["i_dev"][nt]).sum()), target_i_total=float(np.abs(d["i_dev"][tg]).sum()), i_supply=d["i_supply"],
                         v_rail_droop=d["v_rail_droop"], i_driver_max=d["i_driver_max"], target_vdev_min=float(d["v_dev"][tg].min()), vds_max=float(d["v_ds"].max()))
    return dict(v_drive=v, mode=mode, row=row, nontarget_state=state, **res)


def main() -> None:
    fl = list(itertools.product(V_DRIVE, ("LRS", "HRS"), (512,)))
    dcj = list(itertools.product(V_DRIVE, ("clamp0", "inhibit_V", "inhibit_V2"), (256, 512), ("LRS", "HRS")))
    with Pool(24) as p:
        fr = p.map(_float_job, fl)
        dr = p.map(_dc_job, dcj)
    out = dict(float=fr, dc=dr, t_flat=T_FLAT, t_rise=T_RISE,
               note="floating non-target bitlines: device held at its state (fixed resistor) to measure the stress waveform; disturb if time above vth > tmin")
    (RP.WRITE / "d2_unselected.json").write_text(json.dumps(out, indent=1))
    for r in fr:
        worst = max(r["curves"].values(), key=lambda c: c["peak"])
        print(f"float v={r['v_drive']} nontarget {r['state']}: peak {worst['peak']:.3f} V, time above 1.0 V {worst['time_above_s']['1.0'] * 1e9:.2f} ns, above 0.8 V {worst['time_above_s']['0.8'] * 1e9:.2f} ns")
    for r in dr:
        if r["row"] == 512:
            a = r["after"]
            print(f"{r['mode']:11s} v={r['v_drive']} nontarget {r['nontarget_state']}: |Vdev| max {a['nontarget_vdev_max']:.4f} V, nontarget I {a['nontarget_i_total'] * 1e3:.2f} mA, target I {a['target_i_total'] * 1e3:.2f} mA, supply {a['i_supply'] * 1e3:.1f} mA")


if __name__ == "__main__":
    main()
