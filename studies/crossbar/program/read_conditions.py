"""1D-ii: the read path as 1F actually biases it, with the compiled device and the BSIM4 access transistor - the verify read's signal and the read-current temperature
coefficient (D3b), which the compact model's device does not have (ABSENT) but the access transistor does.

1F's read: row line 0.35 V, sense node (virtual ground) 0.25 V, word line 1.1 V. 1A-1F used a linear R_tx of 1016 ohm measured with the transistor's source at 0 V; here the
source sits at the 0.25 V node (either orientation). Cases: one branch (device + transistor) at each state; and the far group's top level (8 LRS branches in parallel behind
the 369 ohm of bitline between the far group and its sense node) and the near group's (no wire) - what a temperature change does to a ladder level.
Usage: python -m program.read_conditions"""
from __future__ import annotations

import json

import numpy as np

import paths as RP
from spice import osdi
from spice.netlist import PTM_LIB

TEMPS = (27.0, 37.0, 47.0, 67.0, 87.0, 125.0)
GAPS = dict(lrs_1a=0.2, lrs_adjacent=0.35, hrs_adjacent=1.55, hrs_1a=1.7)


def _dev(name: str, a: str, b: str, gap: float) -> str:
    """The read equation of rram.va (identical to the compiled model to 1e-15, D0) as a B-source: a DC operating point with the gap held fixed."""
    amp = 1e-3 * np.exp(-gap / 0.25)
    return f"B{name} {a} {b} I = {amp:.15g}*sinh(V({a},{b})/0.25) + 1e-12*V({a},{b})"


def deck(temp: float, ori: str) -> str:
    L = ["read conditions", f".include {PTM_LIB}", f".temp {temp}", ".options reltol=1e-9 abstol=1e-16 vntol=1e-12",
         "Vrl rl 0 DC 0.35", "Vsn sn 0 DC 0.25", "Vwl wl 0 DC 1.1"]
    k = 0
    names = []
    for name, g in GAPS.items():                                   # single branches
        if ori == "bl":
            L += [f"Vi{k} rl a{k} DC 0", _dev(f"{k}", f"a{k}", f"m{k}", g), f"M{k} m{k} wl sn 0 ptm45n_lp W=0.54u L=0.045u"]
        else:
            L += [f"Vi{k} rl a{k} DC 0", f"M{k} a{k} wl m{k} 0 ptm45n_lp W=0.54u L=0.045u", _dev(f"{k}", f"m{k}", "sn", g)]
        names.append(("branch", name, k)); k += 1
    for grp, rw in (("far", 0.72 * 505), ("near", 0.72 * 1)):     # eight LRS branches behind the group's bitline wire
        L += [f"Rw{k} bw{k} sn {rw}", f"Vi{k} rl a{k} DC 0"]
        for j in range(8):
            if ori == "bl":
                L += [_dev(f"{k}_{j}", f"a{k}", f"m{k}_{j}", GAPS["lrs_1a"]), f"M{k}_{j} m{k}_{j} wl bw{k} 0 ptm45n_lp W=0.54u L=0.045u"]
            else:
                L += [f"M{k}_{j} a{k} wl m{k}_{j} 0 ptm45n_lp W=0.54u L=0.045u", _dev(f"{k}_{j}", f"m{k}_{j}", f"bw{k}", GAPS["lrs_1a"])]
        names.append(("group8", grp, k)); k += 1
    L += [".op", ".control", "pre_set num_threads=1", "set numdgt=14", "op"]
    L += [f"print i(Vi{i})" for _, _, i in names] + [".endc", ".end"]
    return "\n".join(L) + "\n", names


READ_GAPS = np.round(np.linspace(0.0, 2.0, 201), 4)


def read_table(temp: float = 27.0, ori: str = "bl") -> np.ndarray:
    """Branch read current vs gap at 1F's bias with the BSIM4 transistor: the verify read's signal I_true(gap) (program/verify.py)."""
    L = ["read table", f".include {PTM_LIB}", f".temp {temp}", ".options reltol=1e-9 abstol=1e-18 vntol=1e-12", "Vrl rl 0 DC 0.35", "Vsn sn 0 DC 0.25", "Vwl wl 0 DC 1.1"]
    for k, g in enumerate(READ_GAPS):
        if ori == "bl":
            L += [f"Vi{k} rl a{k} DC 0", _dev(f"{k}", f"a{k}", f"m{k}", g), f"M{k} m{k} wl sn 0 ptm45n_lp W=0.54u L=0.045u"]
        else:
            L += [f"Vi{k} rl a{k} DC 0", f"M{k} a{k} wl m{k} 0 ptm45n_lp W=0.54u L=0.045u", _dev(f"{k}", f"m{k}", "sn", g)]
    L += [".op", ".control", "pre_set num_threads=1", "set numdgt=14", "op"] + [f"print i(Vi{k})" for k in range(len(READ_GAPS))] + [".endc", ".end"]
    s = osdi.scalars(osdi.run("\n".join(L) + "\n"))
    return np.array([s[f"i(vi{k})"] for k in range(len(READ_GAPS))])


def main() -> None:
    out = {}
    for ori in ("bl", "rl"):
        rows = []
        for T in TEMPS:
            d, names = deck(T, ori)
            s = osdi.scalars(osdi.run(d))
            rec = {f"{kind}|{name}": s[f"i(vi{i})"] for kind, name, i in names}
            rows.append(dict(temp_c=T, **rec))
        out[ori] = rows
    res = {}
    for ori, rows in out.items():
        T = np.array([r["temp_c"] for r in rows])
        for k in [k for k in rows[0] if k != "temp_c"]:
            i = np.array([r[k] for r in rows])
            near = (T >= 27) & (T <= 47)
            slope = float(np.polyfit(T[near], i[near], 1)[0])
            res[f"{ori}|{k}"] = dict(i_27_a=float(i[0]), slope_a_per_k_27_47=slope, rel_per_k=slope / i[0], i_all=i.tolist())
            if k.startswith("branch"):
                gname = k.split("|")[1]
                from program.model import r_read
                r_dev = float(r_read(GAPS[gname]))
                res[f"{ori}|{k}"]["r_tx_eff_27_ohm"] = float(0.1 / i[0] - r_dev)
    tables = {f"{ori}|{T}": read_table(T, ori).tolist() for ori in ("bl", "rl") for T in (27.0, 85.0)}
    js = dict(temps=list(TEMPS), raw=out, summary=res, read_table=dict(gaps=READ_GAPS.tolist(), **tables), f1_calibration_drift_ua_per_k=0.05, f1_window_k=5.0,
              note="device read current has no temperature term in rram.va (ABSENT); all temperature dependence here is the BSIM4 access transistor")
    (RP.PROGRAM / "read_conditions.json").write_text(json.dumps(js, indent=1))
    for k, v in res.items():
        print(f"{k:28s} I(27C) {v['i_27_a'] * 1e6:9.3f} uA  dI/dT {v['slope_a_per_k_27_47'] * 1e9:+8.2f} nA/K  ({v['rel_per_k'] * 1e2:+.3f} %/K)" + (f"  R_tx eff {v['r_tx_eff_27_ohm']:.0f} ohm" if "r_tx_eff_27_ohm" in v else ""))


if __name__ == "__main__":
    main()
