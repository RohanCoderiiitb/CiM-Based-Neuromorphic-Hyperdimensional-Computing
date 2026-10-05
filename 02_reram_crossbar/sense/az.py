"""F2(c): offset cancellation by autozero for the regulating amplifier OTA1 of the front-end (b), as small transistor-level pieces:
  1. input offset of OTA1 (Pelgrom Monte-Carlo on the amplifier in unity-gain feedback, DC),
  2. the autozero loop itself: OTA1 in unity feedback with the offset stored on a capacitor C_az in series with the reference input; transient settling of the stored value (time cost) and the error left
     after the switch opens: charge injection of the transmission gate (transient, per switch width) and kT/C (sampled thermal noise, exact formula),
  3. what an input-referred voltage error dV does to the read: error current = dV x G_array(state), G_array up to 1.78 mS (far, 8 LRS) / 5.1 mS (near).
Usage: python -m sense.az"""
from __future__ import annotations

import json
from multiprocessing import Pool

import numpy as np

import device.constants as C
import paths as RP
from sense import port as P
from sense.cells import NM, PM, ota_p, tgate
from sense.metrics import KB, TEMP_K
from sense.ngs import VDD, f as fmt, header, run, run_wrdata, scalars

V_VG = 0.25
VB = 0.46
G_FAR_MAX = 1.0 / (1.0 / P.branch_g(8, 0) + P.wire_r(P.FAR_POS0))
G_NEAR_MAX = 1.0 / (1.0 / P.branch_g(8, 0) + P.wire_r(P.NEAR_POS0))


def _ota_flat(dv: dict, wi=8e-6, li=90e-9, wm=4e-6, lm=180e-9, wt=8e-6) -> list[str]:
    g = lambda n: f" delvto={dv.get(n, 0.0):.6g}"
    return [f"Mt nt vb vdd vdd {PM} W={fmt(wt)} L=90n", f"M1 n1 inp nt vdd {PM} W={fmt(wi)} L={fmt(li)}" + g("M1"), f"M2 out inn nt vdd {PM} W={fmt(wi)} L={fmt(li)}" + g("M2"),
            f"M3 n1 n1 0 0 {NM} W={fmt(wm)} L={fmt(lm)}" + g("M3"), f"M4 out n1 0 0 {NM} W={fmt(wm)} L={fmt(lm)}" + g("M4")]


def offset_sample(dv: dict) -> float:
    """Input offset (V) of OTA1 with the mismatch draw dv: unity-gain follower (output tied to the inverting input), reference at V_VG; offset = V(out) - V_VG, divided by 1 (follower)."""
    L = header("ota offset") + [f"Vdd vdd 0 {VDD}", f"Vb vb 0 {VB}", f"Vin inp 0 {V_VG}", "Vz out inn 0"] + _ota_flat(dv)
    o = scalars(run("\n".join(L + [".op", ".control", "set noaskquit", "run", "print v(out)", ".endc", ".end"]) + "\n"))
    return o["v(out)"] - V_VG


def _draw(rng, wi=8e-6, li=90e-9, wm=4e-6, lm=180e-9):
    s = lambda w, l: C.AVT_MV_UM * 1e-3 / np.sqrt(w * l * 1e12)
    return dict(M1=rng.normal(0, s(wi, li)), M2=rng.normal(0, s(wi, li)), M3=rng.normal(0, s(wm, lm)), M4=rng.normal(0, s(wm, lm)))


def _off(dv):
    return offset_sample(dv)


def az_transient(w_sw: float, c_az: float, t_on: float = 0.5e-9, t_az: float = 12e-9, t_hold: float = 3e-9) -> dict:
    """Autozero of OTA1 (nominal devices: the systematic offset of the circuit): the OTA output is tied to its inverting input through transmission gate S1 for t_az while the reference V_VG is on the
    non-inverting input and C_az (between the amplifier's input node `in` and the inverting input) stores the difference; then S1 opens. Returns the stored-voltage error caused by the switch opening
    (charge injection, from the transient) and the time the AZ phase needs to settle to 0.1 mV."""
    L = header("az loop") + [f"Vdd vdd 0 {VDD}", f"Vb vb 0 {VB}", f"Vref inp 0 {V_VG}", f"Vin in 0 {V_VG}"] + _ota_flat({}) + [f"Caz in inn {fmt(c_az)}", "Cpar inn 0 5f", f"Rl inn rlr 1G", f"Vrl rlr 0 {V_VG}"]
    L += [f"Vph ph 0 PULSE(0 {VDD} {fmt(t_on)} 20p 20p {fmt(t_az)} 1)", f"Vphb phb 0 PULSE({VDD} 0 {fmt(t_on)} 20p 20p {fmt(t_az)} 1)"] + tgate("s1", "out", "inn", "ph", "phb", w_sw)
    tend = t_on + t_az + t_hold
    d = run_wrdata(L + [f".tran 2p {fmt(tend)}"], ["v(inn)", "v(out)"])
    t, vi = d["time"], d["v(inn)"]
    i_pre = int(np.argmin(abs(t - (t_on + t_az - 100e-12)))); i_post = int(np.argmin(abs(t - tend)))
    v_final = float(vi[i_pre])
    idx = np.where(abs(vi[:i_pre] - v_final) > 1e-4)[0]
    settle = float(t[idx[-1]] - t_on) if len(idx) else 0.0
    return dict(w_sw=w_sw, c_az=c_az, v_stored=v_final, injection_V=float(vi[i_post] - v_final), settle_to_0p1mV_ns=settle * 1e9)


def main(n: int = 200) -> None:
    rng = np.random.default_rng(21)
    draws = [_draw(rng) for _ in range(n)]
    with Pool(10) as p:
        offs = np.array(p.map(_off, draws))
    nom = offset_sample({})
    out = dict(ota1_offset_sigma_mV=float(offs.std() * 1e3), ota1_offset_nominal_mV=float(nom * 1e3), n=n, g_far_max_mS=G_FAR_MAX * 1e3, g_near_max_mS=G_NEAR_MAX * 1e3,
               offset_current_far_sigma_uA=float(offs.std() * G_FAR_MAX * 1e6), offset_current_near_sigma_uA=float(offs.std() * G_NEAR_MAX * 1e6), az=[])
    for w in (1e-6, 4e-6):
        for c in (0.1e-12, 0.3e-12, 1e-12):
            r = az_transient(w, c)
            ktc = float(np.sqrt(KB * TEMP_K / c))
            r["ktc_sigma_uV"] = ktc * 1e6
            r["ktc_current_far_uA"] = ktc * G_FAR_MAX * 1e6
            r["injection_current_far_uA"] = abs(r["injection_V"]) * G_FAR_MAX * 1e6
            out["az"].append(r)
            print(f"W_sw {w*1e6:g} um C_az {c*1e12:g} pF: injection {r['injection_V']*1e3:.2f} mV ({r['injection_current_far_uA']:.2f} uA far), kT/C {r['ktc_sigma_uV']:.0f} uV ({r['ktc_current_far_uA']:.2f} uA far), settle {r['settle_to_0p1mV_ns']} ns", flush=True)
    print("OTA1 offset sigma %.2f mV -> %.1f uA (far) %.1f uA (near)" % (out["ota1_offset_sigma_mV"], out["offset_current_far_sigma_uA"], out["offset_current_near_sigma_uA"]))
    RP.SENSE.mkdir(parents=True, exist_ok=True)
    (RP.SENSE / "autozero.json").write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
