"""F2(d): the decision stage after the integrator. The charge Q+ - Q- - Q_thr integrated on C_int appears as the voltage difference V(S-) - V(S+) = dQ/C_int. A clocked comparator reads its sign. ngspice has no
periodic/transient device noise, so the comparator is split into what the simulator CAN give at device level and what it cannot:
  preamplifier (device level): a PMOS-input OTA (the cell used elsewhere, bias as the conveyor OTAs) with the inputs at the integrator level; its input-referred voltage noise PSD from .noise (thermal + flicker),
      integrated over the amplification window t_amp (sinc^2 weight, same convention as sense.metrics); its small-signal gain A_pre (AC) which divides everything behind it;
  latch behind the preamplifier (NOT simulated): input-referred sigma_latch [ASSUM] divided by A_pre; offset of the latch+preamplifier is a static threshold shift removed by the per-column calibration
      (one more number per column) - its calibration residual is part of the 'comparator' term below only through sigma_off_res [ASSUM];
  integrator reset noise: sqrt(kT C_int) sampled on each capacitor at reset, exact formula (the two capacitors are independent: sqrt(2) kT/C on the difference).
Referred to the array current: sigma_I = sigma_V * C_int * k / T_int  (k = copy ratio, T_int = the window over which the charge is collected).
Usage: python -m sense.comparator"""
from __future__ import annotations

import json

import numpy as np

import paths as RP
from sense.acnoise import noise_spectrum
from sense.cells import ota_p
from sense.metrics import KB, TEMP_K
from sense.ngs import VDD, header

SIGMA_LATCH_V = 1.0e-3        # [ASSUM] input-referred noise of a clocked latch in 45 nm (typical 0.3-1 mV rms); only its fraction after the preamplifier gain enters
T_AMP = 0.3e-9                # [CHOICE] preamplifier amplification window
V_CM = 0.55


def preamp(vb: float = 0.46, wi: float = 8e-6, wt: float = 8e-6) -> dict:
    L = header("preamp noise") + ota_p("pre", wi=wi, wt=wt) + [f"Vdd vdd 0 {VDD}", f"Vb vb 0 {vb}", f"Vcm inn 0 {V_CM}", f"Vin inp 0 {V_CM} AC 1", "Xp inp inn o vdd vb pre", "Rl o 0 1G", "Cl o 0 5f"]
    o = noise_spectrum(L, "o", "Vin", fmin=1e6, fmax=2e10)
    f, s_in, s_out = o["f"], o["s_in"], o["s_out"]
    a0 = float(np.sqrt(s_out[0] / s_in[0]))
    sig = {}
    for t in (0.15e-9, 0.3e-9, 0.6e-9):
        w = np.sinc(f * t) ** 2
        sig[f"{t*1e9:g}"] = float(np.sqrt(np.trapezoid(s_in * w, f)))
    return dict(a_pre=a0, sigma_v_by_window=sig)


def sigma_i(sig_pre_v: float, a_pre: float, c_int: float, k: float, t_int: float) -> dict:
    ktc = np.sqrt(2 * KB * TEMP_K / c_int)
    latch = SIGMA_LATCH_V / a_pre
    tot_v = np.sqrt(sig_pre_v ** 2 + latch ** 2 + ktc ** 2)
    sc = c_int * k / t_int
    return dict(preamp_uA=sig_pre_v * sc * 1e6, latch_uA=latch * sc * 1e6, reset_ktc_uA=ktc * sc * 1e6, total_uA=tot_v * sc * 1e6)


def main() -> None:
    p = preamp()
    out = dict(preamp=p, sigma_latch_v=SIGMA_LATCH_V, t_amp=T_AMP, table=[])
    for c_int in (100e-15, 200e-15, 400e-15):
        for t_int in (0.5e-9, 1e-9, 2e-9):
            r = sigma_i(p["sigma_v_by_window"]["0.3"], p["a_pre"], c_int, 4.0, t_int)
            out["table"].append(dict(c_int_fF=c_int * 1e15, t_int_ns=t_int * 1e9, **r))
            print(f"C_int {c_int*1e15:g} fF T_int {t_int*1e9:g} ns: preamp {r['preamp_uA']:.2f} latch {r['latch_uA']:.2f} reset {r['reset_ktc_uA']:.2f} -> {r['total_uA']:.2f} uA")
    print("preamp gain", p["a_pre"], "sigma_v", p["sigma_v_by_window"])
    RP.SENSE.mkdir(parents=True, exist_ok=True)
    (RP.SENSE / "comparator_noise.json").write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
