"""1D-i D1/D2: the row-parallel write as a TRANSIENT with the behavioural switching device in every one of the 320 positions (write/behav.py), on the full row deck.
  (1) SET of the whole row, recommended bias (V/2 on non-target bitlines): every target must switch; the supply-current waveform gives the peak write current.
  (2) the same with non-target bitlines FLOATING and their devices HRS, at a short tmin: does a neighbour switch (the disturb predicted from the waveform in d2_unselected)?
Usage: python -m write.d1_transient"""
from __future__ import annotations

import json

import numpy as np

import paths as RP
from write import d1_parallel as D1, rowdeck as RD, run as R

CASES = [
    dict(name="set_row_vhalf", v_drive=1.2, vth=1.0, tmin=100e-9, unselected="inhibit", v_inh=0.6, t_flat=300e-9),
    dict(name="set_row_vhalf_far_vth", v_drive=1.3, vth=1.2, tmin=100e-9, unselected="inhibit", v_inh=0.65, t_flat=300e-9),
    dict(name="float_tmin5ns", v_drive=1.2, vth=0.8, tmin=5e-9, unselected="float", v_inh=None, t_flat=300e-9),
    dict(name="float_tmin10ns", v_drive=1.2, vth=0.8, tmin=10e-9, unselected="float", v_inh=None, t_flat=300e-9),
    dict(name="float_tmin10ns_v2", v_drive=2.0, vth=0.8, tmin=10e-9, unselected="float", v_inh=None, t_flat=300e-9),
]


def one(c: dict) -> dict:
    tg = D1.set_targets(D1.weights())
    w = RD.RowWrite(v_drive=c["v_drive"], row=512, unselected=c["unselected"], v_inh=c["v_inh"])
    probes = ["i(vpad)"] + [f"v(s{j})" for j in range(RD.N_BL)]
    d = R.tran(w, tg, dict(vth=c["vth"], tmin=c["tmin"], tsw=2e-9, x0=np.zeros(RD.N_BL)), 1e-9, c["t_flat"], c["t_flat"] + 100e-9, probes)
    t = d["time"]
    s = np.array([d[f"v(s{j})"] for j in range(RD.N_BL)])
    sw_t = [float(t[np.argmax(s[j] > 0.5)]) if (s[j] > 0.5).any() else None for j in range(RD.N_BL)]
    tgt = [x for j, x in enumerate(sw_t) if tg[j]]
    non = [x for j, x in enumerate(sw_t) if not tg[j]]
    sel = np.unique(np.searchsorted(t, np.linspace(0, t[-1], 400)).clip(0, len(t) - 1))
    return dict(case=c, targets_switched=int(sum(x is not None for x in tgt)), n_targets=int(tg.sum()),
                nontargets_switched=int(sum(x is not None for x in non)), t_switch_min=min([x for x in tgt if x is not None], default=None),
                t_switch_max=max([x for x in tgt if x is not None], default=None), i_peak_a=float(np.abs(d["i(vpad)"]).max()),
                trace=dict(t=t[sel].tolist(), i_supply=np.abs(d["i(vpad)"][sel]).tolist(), s_target_mean=s[tg][:, sel].mean(axis=0).tolist(),
                           s_nontarget_max=s[~tg][:, sel].max(axis=0).tolist()))


def main() -> None:
    from multiprocessing import Pool
    with Pool(len(CASES)) as p:
        res = p.map(one, CASES)
    (RP.WRITE / "d1_transient.json").write_text(json.dumps(res, indent=1))
    for r in res:
        print(r["case"]["name"], f"targets switched {r['targets_switched']}/{r['n_targets']} (t {r['t_switch_min']} .. {r['t_switch_max']}), non-targets switched {r['nontargets_switched']}, peak supply {r['i_peak_a'] * 1e3:.1f} mA")


if __name__ == "__main__":
    main()
