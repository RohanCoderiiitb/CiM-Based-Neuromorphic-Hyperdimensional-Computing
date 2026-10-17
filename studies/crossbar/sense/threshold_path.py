"""F5: the path from the ladder's thresholds to the comparators, what it costs and what accuracy it needs.

Requirement (from the 1F budget): a threshold must reach each column's comparator with 1-sigma error <= ~0.2 uA out of up to +/-115 uA (far) / +/-300 uA (near) - i.e. 0.17% / 0.07% of the value, 10-11 bit
absolute accuracy PER COLUMN, because the error of a column's threshold is an error of that column's decision. Four ways to deliver it:
  A  a current DAC per column (160 DACs), code from the digital table
  B  one shared DAC + sample-and-hold per column (the shared DAC is multiplexed over the 160 columns' different corrected values)
  C  a switched ladder: every column has its own set of ladder thresholds on a switched capacitor / resistor ladder, selected by the group index
  D  digital after a per-column ADC (the front-end output digitised, thresholds compared in digital)
and, separately, WHERE the rank-3 row-gain multiply (1C: 12-bit factors, 19,584 bits) is done: per column digitally (160 x 7 multiplies per read), per column POSITION digitally (the 32 distinct column positions of
a macro row, shared by the five macros), as stored corrected thresholds, or in the analog domain with the per-column trims.
Simulated here: the accuracy of a PMOS current mirror (the unit every per-column current DAC / copy is built from) vs its area, by Monte-Carlo on the PTM card with Pelgrom mismatch - it shows why 10 bit absolute
per column cannot come from matching and needs per-column calibration. Everything else (areas, energies) is [MODEL]/[ASSUM] and tagged; no threshold generator is designed at transistor level.
Usage: python -m sense.threshold_path"""
from __future__ import annotations

import json
from multiprocessing import Pool

import numpy as np

import device.constants as C
import paths as RP
from sense import energy_1f as E
from sense.cells import PM
from sense.ngs import VDD, f as fmt, header, run, scalars


def _mirror(dv1, dv2, w, l, iref):
    L = header("pmos mirror") + [f"Vdd vdd 0 {VDD}", f"Iref d1 0 DC {iref}", f"M1 d1 d1 vdd vdd {PM} W={fmt(w)} L={fmt(l)} delvto={dv1:.6g}", f"M2 d2 d1 vdd vdd {PM} W={fmt(w)} L={fmt(l)} delvto={dv2:.6g}", "Vo d2 0 0.45"]
    o = scalars(run("\n".join(L + [".op", ".control", "set noaskquit", "run", "print i(Vo)", ".endc", ".end"]) + "\n"))
    return -o["i(vo)"] / iref


def _mj(a):
    w, l, iref, d1, d2 = a
    return _mirror(d1, d2, w, l, iref)


def mirror_accuracy(n: int = 200) -> list:
    rng = np.random.default_rng(41)
    out = []
    with Pool(10) as p:
        for (w, l) in ((1e-6, 0.09e-6), (4e-6, 0.09e-6), (4e-6, 0.36e-6), (16e-6, 0.36e-6), (16e-6, 1.44e-6), (64e-6, 1.44e-6)):
            for iref in (20e-6,):
                s = C.AVT_MV_UM * 1e-3 / np.sqrt(w * l * 1e12)
                d = [(w, l, iref, rng.normal(0, s), rng.normal(0, s)) for _ in range(n)]
                nom = _mirror(0.0, 0.0, w, l, iref)
                g = np.array(p.map(_mj, d))
                out.append(dict(w_um=w * 1e6, l_um=l * 1e6, area_um2=2 * w * l * 1e12, iref_uA=iref * 1e6, nominal_ratio=nom, sigma_rel=float(g.std())))
    return out


# ---- [MODEL]/[ASSUM] cost tables --------------------------------------------------------------------------------
AREA_UM2 = dict(dac10_current=400.0, sample_hold=60.0, cap_array10=250.0, trim_logic_per_bit=1.5)      # [ASSUM] per column
ADC10_PJ = 20.0                                                                                          # [ASSUM] 10-bit SAR ADC, ~20 fJ/conversion-step x 1024... conservative low end
ADC10_UM2 = 3000.0


def options(rc: dict) -> list[dict]:
    nread8 = rc["8"]["reads_nonzero"]; nread4 = rc["4"]["reads_nonzero"]
    nc8 = E.n_comparisons(rc["8"]["a_hist"])
    out = []
    out.append(dict(option="A: current DAC per column", area_per_col_um2=AREA_UM2["dac10_current"] + 10 * AREA_UM2["trim_logic_per_bit"], accuracy="needs per-column calibration of its 10-bit gain (mirror matching alone is 1-3%)",
                    energy_per_read_pJ=160 * (60e-6 * VDD * 0.3e-9 * 1e12) * nc8, time_ns="0.3-0.5 per comparison (DAC settling to 0.1% into the 200 fF integrator)", note="static bias of 160 DACs while on: 160 x 60 uA x 1.1 V"))
    out.append(dict(option="B: shared DAC + sample-and-hold per column", area_per_col_um2=AREA_UM2["sample_hold"], accuracy="S&H droop and kT/C per column; the DAC is time-multiplexed: 160 values per comparison in < 1 ns is not possible -> only for 20-40 columns per pass",
                    energy_per_read_pJ=None, time_ns="160 x settle (>= 0.3 ns each) per comparison without multiplexing hardware", note="rejected for 160 columns at once"))
    out.append(dict(option="C: switched capacitor-array ladder per column", area_per_col_um2=AREA_UM2["cap_array10"], accuracy="capacitor matching ~0.1-0.2% for 10-bit unit arrays [ASSUM], temperature-stable; the least calibration",
                    energy_per_read_pJ=160 * E.E_DAC_J * nc8 * 1e12, time_ns="0.2 per step (charge redistribution) + 0.3 comparator", note="chosen for the area / accuracy estimate; 10-bit absolute across +/-300 uA needs range switching"))
    out.append(dict(option="D: digital after per-column ADC", area_per_col_um2=ADC10_UM2, accuracy="10-11 bit ADC INL ~ 0.5-1 LSB: needs ~12 bit",
                    energy_per_read_pJ=160 * ADC10_PJ, time_ns=">= 2-4 per conversion", note="160 ADC x 20 pJ x 20,420 reads = %.0f uJ per inference: rejected" % (160 * ADC10_PJ * 1e-12 * nread8 * 1e6)))
    return out


def multiply_options(rc: dict) -> dict:
    return {m: {g: E.threshold_path_J(g, m, rc) * 1e6 for g in (4, 8)} for m in ("per_column_digital", "per_position_digital", "stored_corrected")}


def main() -> None:
    rc = json.loads((RP.SENSE / "read_counts.json").read_text())
    mir = mirror_accuracy()
    for r in mir:
        print(f"PMOS mirror W {r['w_um']:g} L {r['l_um']:g} um (2 devices {r['area_um2']:.1f} um2) at {r['iref_uA']:g} uA: sigma(gain) {100*r['sigma_rel']:.2f} %")
    opts = options(rc)
    mult = multiply_options(rc)
    print("rank-3 correction energy per inference (uJ):", mult)
    RP.SENSE.mkdir(parents=True, exist_ok=True)
    (RP.SENSE / "threshold_path.json").write_text(json.dumps(dict(mirror_mc=mir, options=opts, rank3_multiply_uJ=mult, area_assumptions_um2=AREA_UM2, horowitz=E.HOROWITZ), indent=1, default=float))


if __name__ == "__main__":
    main()
