"""F2(c), a negative result kept on record: chopping the two conveyors between the bitlines half-way through the integration window (sense.b2) and dynamic element matching of the copy devices (sense.dem) were
built to cancel the copy-gain mismatch without calibration. They cancel it only if the conveyors collect the same charge after the swap as before it; they do not: each conveyor has to re-slew its gate
from the BL+ current to the BL- current (a 2-3x change of the array current) and the window is shorter than that. Measured here on the nominal (no mismatch) circuit: the differential charge collected
with the swap vs without it, relative to an ideal virtual ground, far group, integration capacitor sized for a 0.3 V swing. Usage: python -m sense.run_chop"""
from __future__ import annotations

import json

import numpy as np

import paths as RP
from multiprocessing import Pool

from sense import b2, cal, dem, mc, port as P
from sense.cal import DESIGN

T_MC, TAIL_MC, C_MC = 1e-9, 0.5e-9, 600e-15


def _job(a):
    m, pos, dv, chopped, cm = a
    dz = mc.Design(**DESIGN)
    qp, qn, _ = b2.run_charges(dz, m, pos, b2.Chop(c_int=C_MC, t_tail=TAIL_MC), T_MC, dv, chopped=chopped, c_mis_p=cm)
    return qp / T_MC, qn / T_MC


def mismatch_mc(n: int = 30) -> dict:
    """Pelgrom mismatch on every transistor of both conveyors (and 0.2% on the integration capacitor) for the plain dual-integrator and the chopped one, T = 1 ns: uncalibrated rms error and what is left
    after one common gain per column and after one gain per channel (uA, referred to the array current)."""
    dz = mc.Design(**DESIGN)
    rng = np.random.default_rng(7)
    draws = [(b2.draw(dz, rng), float(rng.normal(0, 0.002))) for _ in range(n)]
    out = {}
    with Pool(10) as pool:
        for chopped in (False, True):
            nom = np.array(pool.map(_job, [(m, pos, None, chopped, 0.0) for pos, m in cal.POINTS]))
            meas = np.array([pool.map(_job, [(m, pos, d, chopped, cm) for pos, m in cal.POINTS]) for d, cm in draws])
            raw = np.array([(meas[i][:, 0] - meas[i][:, 1]) - (nom[:, 0] - nom[:, 1]) for i in range(n)])
            r1, r2 = [], []
            for i in range(n):
                A = np.concatenate([nom[:, 0], nom[:, 1]])[:, None]; y = np.concatenate([meas[i][:, 0], meas[i][:, 1]])
                c, *_ = np.linalg.lstsq(A, y, rcond=None); r = meas[i] - c[0] * nom; r1.append(r[:, 0] - r[:, 1])
                rr = []
                for k in (0, 1):
                    ck = (meas[i][:, k] @ nom[:, k]) / (nom[:, k] @ nom[:, k]); rr.append(meas[i][:, k] - ck * nom[:, k])
                r2.append(rr[0] - rr[1])
            r1, r2 = np.array(r1), np.array(r2)
            out["chopped" if chopped else "plain"] = dict(raw_rms_uA=float(np.sqrt(np.mean(raw ** 2)) * 1e6), one_gain_worst_far_uA=float(r1.std(0)[:9].max() * 1e6), two_gain_worst_far_uA=float(r2.std(0)[:9].max() * 1e6),
                                                         two_gain_worst_near_uA=float(r2.std(0)[9:].max() * 1e6))
            print(("chopped" if chopped else "plain"), out["chopped" if chopped else "plain"])
    return out


def main() -> None:
    dz = mc.Design(**DESIGN)
    out = dict(b2=[], dem=[])
    for T, c_int in ((0.5e-9, 600e-15), (1e-9, 600e-15), (2e-9, 1.2e-12)):
        ch = b2.Chop(c_int=c_int, t_tail=0.5e-9)
        for m in (1, 7):
            ip, inn = b2.ideal_charges(m, P.FAR_POS0, ch, T)
            r = {}
            for chopped in (False, True):
                qp, qn, _ = b2.run_charges(dz, m, P.FAR_POS0, ch, T, chopped=chopped)
                r["chopped" if chopped else "plain"] = (qp - qn) / (ip - inn)
            out["b2"].append(dict(T=T, m=m, c_int=c_int, step_ratio_plain=r["plain"], step_ratio_chopped=r["chopped"]))
            print(f"b2 T {T*1e9:g} ns m={m}: differential step / ideal: plain {r['plain']:.2f}, chopped {r['chopped']:.2f}")
    for T in (1e-9, 2e-9):
        t0 = 0.3e-9
        for m in (1, 7):
            idp = P.levels(P.FAR_POS0)[0][m]; idn = P.levels(P.FAR_POS0)[1][m]
            r = {}
            for name, tsw in (("plain", None), ("swapped", t0 + 0.5 * (T + 0.3e-9))):
                qp, qn = dem.charges(dz, m, P.FAR_POS0, None, T, tsw)
                r[name] = (qp - qn) / ((idp - idn) * T)
            out["dem"].append(dict(T=T, m=m, step_ratio_plain_gate_switches=r["plain"], step_ratio_swapped=r["swapped"]))
            print(f"dem T {T*1e9:g} ns m={m}: differential step / ideal: no swap {r['plain']:.2f}, swap {r['swapped']:.2f}")
    out["mismatch_mc_T1ns_tail0p5ns"] = mismatch_mc()
    (RP.SENSE / "chopping_negative.json").write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
