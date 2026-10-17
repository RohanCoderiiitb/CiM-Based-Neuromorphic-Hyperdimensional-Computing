"""C1(d) summary: read energy and latency per group read, per group and averaged over the column (reads results/transient/group_read_energy_latency_macro.json).

Energy of a group read of one macro (32 cells = 64 bitlines, rows driven from both ends) = array energy from the transient (supply energy over a pulse of length T)
+ word-line gate switching energy a * C_WL * V_WL^2 (C_WL = 64 access-transistor gates [SIM, validate/gate_cap.py] + word-line wire C_LINE per pitch [ASSUM]).
Not included (not designed in 1C): sense amplifier / comparator / ladder DAC / digital energy.
Usage: python -m scaleup.analyze_c1d"""
from __future__ import annotations

import paths as RP

import json

import numpy as np

import device.constants as C

EPS = "1e-07"
GATE = json.loads((RP.DEVICE / "access_transistor_gate_cap.json").read_text())["20"]["c_gate_f_read_bias"]   # F per access transistor at the read bias [SIM]


def c_wl_macro(n_cells: int = C.CELLS_PER_MACRO_ROW) -> float:
    return 2 * n_cells * GATE + 2 * n_cells * C.C_LINE_PER_PITCH_F            # 2 transistors per cell + word-line wire (one pitch per bitline)


def e_wl(a: int, n_cells: int = C.CELLS_PER_MACRO_ROW) -> float:
    return a * c_wl_macro(n_cells) * C.V_WL ** 2


def summarise() -> dict:
    res = json.loads((RP.TRANSIENT / "group_read_energy_latency_macro.json").read_text())
    out = {}
    for a in (8, 4):
        rs = [r for r in res if r["a"] == a]
        per_g = {}
        for G in range(C.GROUPS_PER_COLUMN):
            rg = [r for r in rs if r["G"] == G]
            per_g[G] = dict(i_sup_mA=float(np.mean([r["i_sup_final_A"] for r in rg]) * 1e3), t_settle_ps={e: float(max(r["t_settle_s"][e] for r in rg) * 1e12) for e in rg[0]["t_settle_s"]},
                            energy_pJ={T: float(np.mean([r["energy_J"][T] for r in rg]) * 1e12) for T in rg[0]["energy_J"]})
        out[str(a)] = per_g
    return out


def main() -> None:
    s = summarise()
    cw = c_wl_macro()
    print(f"C_WL per row per macro = {cw*1e15:.1f} fF  (gate {GATE*1e15:.3f} fF x 64 + wire); E_WL per row = {cw*C.V_WL**2*1e15:.1f} fJ")
    for a in ("8", "4"):
        per = s[a]
        i = np.array([per[G]["i_sup_mA"] for G in range(64)])
        t = np.array([per[G]["t_settle_ps"][EPS] for G in range(64)])
        print(f"a={a}: supply current {i[0]:.2f} mA (near) -> {i[-1]:.2f} mA (far), mean {i.mean():.2f}; settle(0.1uA) max over groups {t.max():.0f} ps, mean {t.mean():.0f}")
        for T in ("0.5e-09", "1e-09", "5e-09", "1e-08"):
            k = repr(float(T))
            e = np.array([per[G]["energy_pJ"].get(k, np.nan) for G in range(64)])
            if not np.isnan(e).all():
                print(f"   E(T={float(T)*1e9:.1f} ns): near {e[0]:.3f} far {e[-1]:.3f} mean {e.mean():.3f} pJ per macro read")
    (RP.TRANSIENT / "group_read_energy_latency_summary.json").write_text(json.dumps(s, indent=1))


if __name__ == "__main__":
    main()
