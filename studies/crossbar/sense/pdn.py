"""F4: power delivery of the read pulse. Lumped PDN of the array's row-supply rail (0.35 V = V_VG + V_READ), ngspice transient:

   regulator (ideal V_REG behind R_reg, L_reg) -> package/bump R_pad, L_pad -> rail node -> [R_grid] -> load node (the five macros' current steps)
   on-chip decoupling C_dec with a series damping resistor R_d between the load node and ground; the load is five current pulses (one per macro), amplitude I_ARRAY/5 each, 100 ps ramps (the array's own
   current rise, 1C: 130-160 ps settling), width T, stagger s between consecutive macros.

Baseline values from the brief / 1C: R_pad 0.5 ohm, L_pad 100 pH, 69.2 mA step. Regulator R_reg 0.05 ohm, L_reg 0.5 nH (a ~16 MHz loop: it cannot follow a nanosecond pulse; it recharges the decoupling between reads) [ASSUM].
Rail wire resistance R_grid 0.1 ohm lumped (0.0072 ohm/pitch both ends, 1C) [MODEL]. C_dec = decoupling referred to the pulse's rail; area = C_dec / density; density at the 0.35 V rail measured from the PTM card
(sense/pdn.py: MOS capacitor C(V) sweep): 5.0 fF/um2 (NMOS gate at 0.35 V over ground), 8.2 fF/um2 (accumulation-mode, isolated well), 1C's 5-20 fF/um2 range kept for the sensitivity.
Metrics: rail droop (V_REG-referred minimum of the load-node voltage during the pulse, mV), droop at the end of the pulse, the steady (DC) drop, ring-down time (until within 1 mV of the DC level),
and the minimum C_dec for a droop budget. Usage: python -m sense.pdn"""
from __future__ import annotations

import itertools
import json
from multiprocessing import Pool

import numpy as np

import device.constants as C
import paths as RP
from sense.ngs import f as fmt, run_wrdata

V_REG = 0.35
I_ARRAY = 69.2e-3
N_MACRO = C.N_MACROS
R_PAD, L_PAD = 0.5, 100e-12
R_REG, L_REG = 0.05, 0.5e-9
R_GRID = 0.1
T_RAMP = 100e-12
DENSITY_FF_UM2 = (5.0, 8.2)


def netlist(c_dec, r_d, t_pulse, stagger, i_array=I_ARRAY, r_pad=R_PAD, l_pad=L_PAD, c_pre=True, t0=0.5e-9, l_reg=L_REG):
    L = ["pdn", ".options reltol=1e-6 abstol=1e-12 gmin=1e-15", f"Vreg reg 0 {V_REG}", f"Rreg reg r1 {R_REG}", f"Lreg r1 r2 {fmt(max(l_reg, 1e-13))}", f"Rpad r2 r3 {r_pad}", f"Lpad r3 rail {fmt(l_pad)}",
         f"Rgrid rail load {R_GRID}"]
    if c_dec > 0:
        L += [f"Cdec load cd {fmt(c_dec)}", f"Rd cd 0 {r_d}"]
    ia = i_array / N_MACRO
    for m in range(N_MACRO):
        ts = t0 + m * stagger
        L += [f"I{m} load 0 PWL(0 0 {fmt(ts)} 0 {fmt(ts + T_RAMP)} {fmt(ia)} {fmt(ts + T_RAMP + t_pulse)} {fmt(ia)} {fmt(ts + 2 * T_RAMP + t_pulse)} 0)"]
    t_end = t0 + (N_MACRO - 1) * stagger + 2 * T_RAMP + t_pulse + 30e-9
    return L, t0, t_end


def one(args):
    c_dec, r_d, t_pulse, stagger = args[:4]
    scale = args[4] if len(args) > 4 else 1.0
    pad = args[5] if len(args) > 5 else {}
    L, t0, t_end = netlist(c_dec, r_d, t_pulse, stagger, i_array=I_ARRAY * scale, **pad)
    d = run_wrdata(L + [f".tran 5p {fmt(t_end)} uic", f".ic v(rail)={V_REG} v(load)={V_REG} v(r1)={V_REG} v(r2)={V_REG} v(r3)={V_REG}"], ["v(load)"])
    t, v = d["time"], d["v(load)"]
    sel = (t > t0) & (t < t0 + (N_MACRO - 1) * stagger + 2 * T_RAMP + t_pulse)
    dv_min = float(V_REG - v[sel].min())
    t_pulse_end = t0 + (N_MACRO - 1) * stagger + T_RAMP + t_pulse
    v_end = float(V_REG - v[np.argmin(abs(t - t_pulse_end))])
    # recovery: time after the end of the last pulse until within 1 mV of V_REG
    after = t > t_pulse_end + T_RAMP
    off = np.where(abs(v[after] - V_REG) > 1e-3)[0]
    rec = float(t[after][off[-1]] - (t_pulse_end + T_RAMP)) if len(off) else 0.0
    return dict(c_dec=c_dec, r_d=r_d, t_pulse=t_pulse, stagger=stagger, i_scale=scale, pad=pad, droop_max_mV=dv_min * 1e3, droop_at_pulse_end_mV=v_end * 1e3, recovery_ns=rec * 1e9)


def main() -> None:
    grid = []
    for T in (0.5e-9, 1e-9, 2e-9):
        grid.append((0.0, 1.0, T, 0.0))
        for c, rd, st in itertools.product((0.5e-9, 1e-9, 2e-9, 5e-9, 10e-9, 20e-9), (0.02, 0.1, 0.3, 1.0), (0.0, 200e-12)):
            grid.append((c, rd, T, st))
    # peak current scaled: columns sensed at once (1.0 = 160) or the largest a per read (g = 4 halves it)
    for T in (1e-9, 2e-9):
        for scale, c, rd in itertools.product((0.5, 0.25, 0.125), (0.1e-9, 0.2e-9, 0.5e-9, 1e-9, 2e-9, 5e-9, 10e-9), (0.05, 0.2)):
            grid.append((c, rd, T, 0.0, scale))
    with Pool(10) as p:
        rows = p.map(one, grid, chunksize=2)
    RP.PDN.mkdir(parents=True, exist_ok=True)
    (RP.PDN / "pdn_sweep.json").write_text(json.dumps(rows, indent=1))
    for r in rows:
        if r["i_scale"] == 1.0 and (r["stagger"] == 0.0 and r["r_d"] in (0.1, 1.0, 1.0) or r["c_dec"] == 0):
            print(f"T {r['t_pulse']*1e9:g} ns C {r['c_dec']*1e9:g} nF Rd {r['r_d']} stagger {r['stagger']*1e12:g} ps: droop max {r['droop_max_mV']:.1f} mV end {r['droop_at_pulse_end_mV']:.1f} mV, recovery {r['recovery_ns']:.1f} ns")


def main_pad() -> None:
    """Sensitivity to the pad network and the regulator (R_pad, L_pad, L_reg) at two operating points: full 160 columns / a = 8 with 10 nF (T = 1 ns) and the recommended 40 columns, g = 4 with 1 nF."""
    grid = []
    for (scale, c, rd, T) in ((1.0, 10e-9, 0.02, 1e-9), (0.125, 1e-9, 0.05, 1e-9)):
        for r_pad, l_pad, l_reg in itertools.product((0.1, 0.25, 0.5, 1.0), (50e-12, 100e-12, 200e-12), (0.0, 0.5e-9, 2e-9)):
            grid.append((c, rd, T, 0.0, scale, dict(r_pad=r_pad, l_pad=l_pad, l_reg=l_reg)))
    with Pool(10) as p:
        rows = p.map(one, grid, chunksize=2)
    (RP.PDN / "pdn_pad_sweep.json").write_text(json.dumps(rows, indent=1))
    for sc in (1.0, 0.125):
        sub = [r for r in rows if r["i_scale"] == sc]
        print(f"scale {sc}: droop range {min(r['droop_max_mV'] for r in sub):.1f}-{max(r['droop_max_mV'] for r in sub):.1f} mV; recovery {min(r['recovery_ns'] for r in sub):.1f}-{max(r['recovery_ns'] for r in sub):.1f} ns")
        for key in ("r_pad", "l_pad", "l_reg"):
            vals = sorted({r["pad"][key] for r in sub})
            print("   ", key, {v: (round(np.mean([r["droop_max_mV"] for r in sub if r["pad"][key] == v]), 1), round(np.mean([r["recovery_ns"] for r in sub if r["pad"][key] == v]), 1)) for v in vals})


if __name__ == "__main__":
    import sys
    main_pad() if "--pad" in sys.argv else main()
