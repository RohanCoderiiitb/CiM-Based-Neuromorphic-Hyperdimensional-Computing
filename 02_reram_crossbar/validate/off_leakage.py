"""Fix 2: off-state leakage of the access transistor (PTM 45nm LP), simulated. Writes results/off_leakage.json.

Branch: Vr(0.1V) -> NMOS(gate 0 V, off) -> LRS device -> bitline held at v_bl by an ammeter source.
The bitline ammeter sees only drain->source channel/subthreshold current plus source-junction leakage. GIDL, drain
junction and gate tunnelling return through Vr/the gate/the body, not the bitline; i(Vr) is recorded too so the
split is visible. v_bl = 0 is the conservative (largest-leakage) bitline bias; a representative active bias is also run.

Usage: python -m validate.off_leakage [--n 500]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

import device.constants as C
from device.constants import DEFAULT, Params
from spice.netlist import OPTIONS, PTM_LIB, _f
from spice.runner import run_deck_prints
from spice.transistor import _dev_source, branch_rtx

ROOT = Path(__file__).resolve().parents[1]
TEMPS = (27.0, 50.0, 85.0, 125.0)
V_BL_BIASES = (0.0, 0.04)     # V: bitline at ground (worst case) and at a typical active-read level
SEED = 11


def sigma_vth_v(p: Params = DEFAULT) -> float:
    """[MODEL] Pelgrom: sigma_Vth = AVT / sqrt(W*L)."""
    return C.AVT_MV_UM * 1e-3 / np.sqrt(p.tx_w_um * p.tx_l_nm * 1e-3)


def off_currents(delvto: np.ndarray, temp: float, v_bl: float, p: Params = DEFAULT) -> tuple[np.ndarray, float]:
    """Leakage into the bitline (A) of each off device (one per delvto entry), plus mean total supply current per device."""
    n = len(delvto)
    lines = ["off leak", OPTIONS, f".include {PTM_LIB}", f".temp {_f(temp)}", f"Vr vr 0 DC {_f(p.v_read)}", "Vwl wl 0 DC 0"]
    for k, dv in enumerate(delvto):
        lines.append(f"M{k} vr wl s{k} 0 ptm45n_lp W={_f(p.tx_w_um * 1e-6)} L={_f(p.tx_l_nm * 1e-9)} delvto={_f(dv)}")
        lines.append(_dev_source(f"d{k}", f"s{k}", f"b{k}", p.gap_lrs, p))
        lines.append(f"Vam{k} b{k} 0 DC {_f(v_bl)}")
    lines += [".op", ".control", "set noaskquit", "set numdgt=15", "run", "print i(Vr)"]
    lines += [f"print i(Vam{k})" for k in range(n)]
    lines += [".endc", ".end"]
    v = run_deck_prints("\n".join(lines) + "\n")
    # i(Vam) is the current flowing into the + (bitline) terminal from the circuit, sign: positive = into ground source.
    i_bl = np.array([v[f"i(vam{k})"] for k in range(n)])
    return np.abs(i_bl), abs(v["i(vr)"]) / n


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=500)
    args = ap.parse_args()
    p = DEFAULT
    rng = np.random.default_rng(SEED)
    sig = sigma_vth_v(p)
    delvto = sig * rng.standard_normal(args.n)
    i_lrs = branch_rtx(C.GAP_LRS, p)["i"]
    out = {"n_devices": args.n, "sigma_vth_v": sig, "avt_mv_um": C.AVT_MV_UM, "i_lrs_branch_a": i_lrs, "rows": []}
    for t in TEMPS:
        for vb in V_BL_BIASES:
            nom, nom_sup = off_currents(np.zeros(1), t, vb, p)
            pop, pop_sup = off_currents(delvto, t, vb, p)
            out["rows"].append(dict(temp_c=t, v_bl=vb, nominal_a=float(nom[0]), nominal_supply_a=nom_sup,
                                    mean_a=float(pop.mean()), std_a=float(pop.std(ddof=1)), median_a=float(np.median(pop)),
                                    max_a=float(pop.max()), samples_a=pop.tolist()))
            print(f"T={t:5.0f}C v_bl={vb:.2f}: nominal {nom[0]:.3e} A  mean {pop.mean():.3e}  sigma {pop.std(ddof=1):.3e}  "
                  f"supply/dev {pop_sup:.3e}  nominal/I_LRS {nom[0] / i_lrs:.2e}")
    (ROOT / "results" / "off_leakage.json").write_text(json.dumps(out))


if __name__ == "__main__":
    main()
