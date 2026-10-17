"""1D-i D3: half-select inside the 2T2R cell and on the unselected rows - which bias scheme writes the target without disturbing anything else, and what it does to the
1.1 V core access transistors.

Both devices of a cell share the word line and the row line; they are on DIFFERENT bitlines, so they are addressed separately by their bitline levels and the write is two
phases (a SET phase for the devices that must become LRS, then a RESET phase for the devices that must become HRS; each phase is row-parallel).
Four device classes during one phase, each a series (device + PTM BSIM4 access transistor) between ideal row-line and bitline levels (ideal drivers: the array IR was D1/D2):
  S-T  selected row, target bitline          (the device being written)
  S-N  selected row, non-target bitline      (the partner of a target, or an unwritten cell)
  U-T  unselected row, target bitline        (511 rows x the target columns)
  U-N  unselected row, non-target bitline    (511 rows x the other columns)
Levels: selected row line / target bitline fixed by the phase (SET: V / 0, RESET: 0 / V); swept: non-target bitline, unselected row line, unselected word line in {0, V/2, V}
(word line {0, V/2}). Every class is simulated with its device LRS and HRS, at 27 C and 125 C (leakage). Recorded: the voltage across every device (signed: + = SET
direction), the current per device, and |Vgs|, |Vgd|, |Vds| of every access transistor.
Usage: python -m write.d3_halfselect"""
from __future__ import annotations

import itertools
import json
from multiprocessing import Pool

import numpy as np

import paths as RP
from spice import osdi
from spice.netlist import PTM_LIB
from write.rowdeck import R_HRS, R_LRS, TX_L_UM, TX_W_UM

V_WRITE = (1.0, 1.2, 1.4, 1.6, 1.8, 2.0, 2.2)
LEVELS = ("0", "V/2", "V")
CLASSES = ("S-T", "S-N", "U-T", "U-N")


def lvl(s: str, v: float) -> float:
    return {"0": 0.0, "V/2": v / 2, "V": v}[s]


def deck(phase: str, v: float, bln: str, rlu: str, wlu: str, ori: str, temp: float, v_wl: float = 1.1) -> str:
    rls, blt = (v, 0.0) if phase == "set" else (0.0, v)
    nodes = {"S-T": (rls, blt, v_wl), "S-N": (rls, lvl(bln, v), v_wl), "U-T": (lvl(rlu, v), blt, lvl(wlu, v)), "U-N": (lvl(rlu, v), lvl(bln, v), lvl(wlu, v))}
    L = ["half-select classes", f".include {PTM_LIB}", f".temp {temp}", ".options reltol=1e-6 abstol=1e-16 vntol=1e-9 gmin=1e-18 itl1=500"]
    k = 0
    for c in CLASSES:
        r, b, g = nodes[c]
        for st, rd in (("LRS", R_LRS), ("HRS", R_HRS)):
            L += [f"Vr{k} r{k} 0 DC {r:.9g}", f"Vb{k} b{k} 0 DC {b:.9g}", f"Vg{k} g{k} 0 DC {g:.9g}"]
            if ori == "bl":
                L += [f"R{k} r{k} m{k} {rd:.9g}", f"M{k} m{k} g{k} b{k} 0 ptm45n_lp W={TX_W_UM}u L={TX_L_UM}u"]
            else:
                L += [f"M{k} r{k} g{k} m{k} 0 ptm45n_lp W={TX_W_UM}u L={TX_L_UM}u", f"R{k} m{k} b{k} {rd:.9g}"]
            k += 1
    L += [".op", ".control", "pre_set num_threads=1", "set noaskquit", "set numdgt=12", "op", "print all"]
    L += [f"print i(Vb{i})" for i in range(k)]
    L += [".endc", ".end"]
    return "\n".join(L) + "\n"


def _job(a):
    phase, v, bln, rlu, wlu, ori, temp = a
    s = osdi.scalars(osdi.run(deck(phase, v, bln, rlu, wlu, ori, temp)))
    out = {}
    k = 0
    for c in CLASSES:
        for st in ("LRS", "HRS"):
            r, m, b, g = s[f"r{k}"], s[f"m{k}"], s[f"b{k}"], s[f"g{k}"]
            v_dev = (r - m) if ori == "bl" else (m - b)
            d_, s_ = (m, b) if ori == "bl" else (r, m)
            out[f"{c}|{st}"] = dict(v_dev=v_dev, i=abs(s[f"i(vb{k})"]), vgs=max(abs(g - d_), abs(g - s_)), vds=abs(d_ - s_))
            k += 1
    return dict(phase=phase, v=v, bln=bln, rlu=rlu, wlu=wlu, ori=ori, temp=temp, classes=out)


LOAD_MAX_A = 100e-6     # [CHOICE] total DC current allowed through the 81,760 unselected cells and the 160 selected non-targets (vs ~35 mA of write current)


def evaluate(r: dict, vth_min: float = 0.8, disturb_frac: float = 0.5) -> dict:
    """Disturb = any non-target device with |V| > disturb_frac x vth_min in either direction [CHOICE: half the lowest swept threshold]; stress = the largest terminal voltage
    of any access transistor (S-T separately: its Vds in compliance is inherent to the write); deliver = |V| across the target in its starting state (SET: HRS, RESET: LRS)."""
    c = r["classes"]
    start = "HRS" if r["phase"] == "set" else "LRS"
    deliver = abs(c[f"S-T|{start}"]["v_dev"])
    dist = max(abs(c[f"{k}|{st}"]["v_dev"]) for k in ("S-N", "U-T", "U-N") for st in ("LRS", "HRS"))
    stress = max(max(c[k]["vgs"], c[k]["vds"]) for k in c)
    stress_unsel = max(max(c[k]["vgs"], c[k]["vds"]) for k in c if k.startswith("U"))
    stress_others = max(max(c[k]["vgs"], c[k]["vds"]) for k in c if not k.startswith("S-T"))
    stress_target = max(max(c[k]["vgs"], c[k]["vds"]) for k in c if k.startswith("S-T"))
    load = dict(sn=max(c[f"S-N|{st}"]["i"] for st in ("LRS", "HRS")), ut=max(c[f"U-T|{st}"]["i"] for st in ("LRS", "HRS")), un=max(c[f"U-N|{st}"]["i"] for st in ("LRS", "HRS")))
    i_uns = 511 * 160 * (load["ut"] + load["un"])
    return dict(deliver_v=deliver, disturb_v=dist, disturb_ok=bool(dist < disturb_frac * vth_min), stress_v=stress, stress_unselected_v=stress_unsel, stress_others_v=stress_others,
                stress_target_v=stress_target, load_a=load, i_unselected_total_a=i_uns, i_sn_total_a=160 * load["sn"],
                admissible=bool(dist < disturb_frac * vth_min and i_uns + 160 * load["sn"] < LOAD_MAX_A))


def main() -> None:
    J = list(itertools.product(("set", "reset"), V_WRITE, LEVELS, LEVELS, ("0", "V/2"), ("bl", "rl"), (27.0, 125.0)))
    with Pool(24) as p:
        rows = p.map(_job, J, chunksize=8)
    for r in rows:
        r["eval"] = evaluate(r)
    best = {}
    for phase, v, ori, temp in itertools.product(("set", "reset"), V_WRITE, ("bl", "rl"), (27.0, 125.0)):
        cand = [r for r in rows if r["phase"] == phase and r["v"] == v and r["ori"] == ori and r["temp"] == temp and r["eval"]["admissible"]]
        if cand:
            b = min(cand, key=lambda r: (round(r["eval"]["stress_others_v"], 3), r["eval"]["i_unselected_total_a"]))
            best[f"{phase}|{v}|{ori}|{temp}"] = dict(bln=b["bln"], rlu=b["rlu"], wlu=b["wlu"], **b["eval"])
        else:
            best[f"{phase}|{v}|{ori}|{temp}"] = None
    out = dict(rows=rows, best=best, rating_v=1.1, note="ideal drivers; device fixed at its state; disturb threshold = 0.5 x 0.8 V (lowest swept vth)")
    (RP.WRITE / "d3_halfselect.json").write_text(json.dumps(out, indent=1))
    for k, b in best.items():
        if k.endswith("|27.0"):
            print(k, None if b is None else f"BLn={b['bln']} RLu={b['rlu']} WLu={b['wlu']}: deliver {b['deliver_v']:.3f} V, disturb {b['disturb_v']:.3f} V, stress target {b['stress_target_v']:.3f} V, others {b['stress_others_v']:.3f} V, unsel load {b['i_unselected_total_a']*1e6:.3f} uA, S-N load {b['i_sn_total_a']*1e6:.2f} uA")


if __name__ == "__main__":
    main()
