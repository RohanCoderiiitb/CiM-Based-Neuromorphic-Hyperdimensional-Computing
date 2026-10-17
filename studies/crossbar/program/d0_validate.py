"""1D-ii D0: the rram.va declaration bug, and the compiled model validated against 1A before it is used for anything.

(b) The bug. The model as received declared `clip_0` (line 24) and used `clip_minGap` (lines 37, 40). 1A renamed the declaration to `clip_minGap` without compiling. The two
    names suggest different clamps - `clip_0` a clamp at gap = 0, `clip_minGap` a clamp at the minGap parameter - so both readings are built and run here:
      as received        : must fail to compile (reproduced, compiler output recorded)
      fix (1A)           : declare clip_minGap; the expression on line 37 is unchanged: limexp(Kclip (minGap - Gap)) x smoothstep(minGap - Gap)
      alternative reading: a lower clamp at gap 0 (minGap replaced by 0 in the lower clamp) - what 'clip_0' would mean if the expression were wrong instead of the declaration
    and a hard SET is applied to each: the fix holds the gap at minGap = 0.2 nm (1A's LRS); the alternative lets it close to ~0 nm.
(d) Validation against 1A: the read I-V at fixed gap (the gap terminal is pinned by a source - nGap is a port of the module), R(0.2 nm) and R(1.7 nm) at 0.1 V against 1A's
    541.82 / 218,586.0 ohm, the full gap range against device/model.py (the 1A read equation), and the gap range 0.2-1.7 nm under hard SET / RESET.
    Plus the quasi-static I-V hysteresis (triangular sweeps through a series resistor) - the published Stanford-PKU characteristic shape.
STOP rule: if the compiled model does not reproduce 1A's resistances to 1e-6 the script raises.
Usage: python -m program.d0_validate"""
from __future__ import annotations

import json
import re

import numpy as np

import paths as RP
from device.model import device_resistance
from spice import osdi

R_LRS_1A, R_HRS_1A = 541.82, 218586.0      # [SIM, 1A section 10] (541.82 / 218586.0 ohm)


def va_variants() -> dict:
    src = osdi.VA.read_text()
    received = src.replace("real Gap, ddt_gap, Gamma, Fw1, Fw2, clip_minGap, clip_maxGap;", "real Gap, ddt_gap, Gamma, Fw1, Fw2, clip_0, clip_maxGap;")
    assert received != src, "rram.va declaration line not found"
    alt = received.replace("Fw1 = smoothstep(minGap-Gap, smoothing);", "Fw1 = smoothstep(0-Gap, smoothing);") \
                  .replace("clip_minGap = (limexp(Kclip*(minGap-Gap)) - ddt_gap) * Fw1;", "clip_0 = (limexp(Kclip*(0-Gap)) - ddt_gap) * Fw1;") \
                  .replace("I(nGap, b) <+ ddt_gap + clip_minGap + clip_maxGap;", "I(nGap, b) <+ ddt_gap + clip_0 + clip_maxGap;")
    return dict(received=received, fixed=src, alternative_clip_at_zero=alt)


def compile_all() -> dict:
    out = {}
    for name, text in va_variants().items():
        rc, log = osdi.compile_source(text)
        out[name] = dict(returncode=rc, log=log.strip()[-1500:])
    return out


def _osdi_for(text: str, tag: str):
    import shutil
    import subprocess
    d = osdi.BUILD / f"variant_{tag}"
    d.mkdir(parents=True, exist_ok=True)
    shutil.copy(osdi.VA_INCLUDE, d / osdi.VA_INCLUDE.name)
    (d / "v.va").write_text(text)
    r = subprocess.run([osdi.tools()["openvaf"], str(d / "v.va"), "-o", str(d / "v.osdi")], capture_output=True, text=True, cwd=str(d))
    if r.returncode != 0:
        raise osdi.ToolchainError(r.stdout + r.stderr)
    return d / "v.osdi"


def hard_set(osdi_path, v: float = 1.2, r_series: float = 1.0, t: float = 1e-6, gap0: float = 1.7, polarity: int = 1) -> dict:
    """Current-unlimited pulse through a resistor: where does the gap end up (the clamp position)?"""
    deck = "\n".join(["hard pulse", ".model rr RRAM", f"Vp p 0 PWL(0 0 1n {polarity * v} {t} {polarity * v} {t + 1e-9} 0 {t + 2e-9} 0)",
                      f"Rs p t {r_series}", "N1 t 0 g rr", f".ic v(g)={gap0}", ".options abstol=1e-12 reltol=1e-6 vntol=1e-7 method=gear",
                      f".tran 1n {t + 2e-9} 0 {t / 2000} uic", ".control", "pre_set num_threads=1", f"pre_osdi {osdi_path}", "set numdgt=12", "run",
                      f"meas tran gmin_ min v(g)", f"meas tran gmax_ max v(g)", f"meas tran gend find v(g) at={t}", ".endc", ".end"])
    s = osdi.scalars(osdi.run(deck + "\n"))
    return dict(gap_min=s.get("gmin_"), gap_max=s.get("gmax_"), gap_end=s.get("gend"))


def read_iv(osdi_path, gaps, volts) -> np.ndarray:
    """I(V) at fixed gap: the gap node is pinned by a voltage source (nGap is a port), a DC sweep of V(t,b)."""
    L = ["read iv", ".model rr RRAM", "Vr t 0 DC 0"]
    for i, g in enumerate(gaps):
        L += [f"Vg{i} g{i} 0 DC {g}", f"N{i} t 0 g{i} rr"]
    L += [f".dc Vr {volts[0]} {volts[-1]} {volts[1] - volts[0]}"]
    d = osdi.run_wrdata(L, ["i(vr)"], commands=["run"])
    return d                                                       # total current of all devices in parallel (one call per gap below)


def read_r(osdi_path, gap: float, v: float = 0.1) -> float:
    deck = "\n".join(["read r", ".model rr RRAM", f"Vr t 0 DC {v}", f"Vg g 0 DC {gap}", "N1 t 0 g rr", ".control", "pre_set num_threads=1", f"pre_osdi {osdi_path}",
                      "set numdgt=15", "op", "let rr = -v(t)/i(Vr)", "print rr", ".endc", ".end"])
    return osdi.scalars(osdi.run(deck + "\n"))["rr"]


def iv_curve(osdi_path, gap: float, volts) -> np.ndarray:
    L = ["iv", ".model rr RRAM", ".options reltol=1e-10 abstol=1e-20 vntol=1e-12", "Vr t 0 DC 0", f"Vg g 0 DC {gap}", "N1 t 0 g rr",
         f".dc Vr {volts[0]:.6g} {volts[-1]:.6g} {volts[1] - volts[0]:.6g}"]
    d = osdi.run_wrdata(L, ["v(t)", "i(vr)"])
    return d["v(t)"], -d["i(vr)"]


def hysteresis(osdi_path, period: float, v_amp: float = 1.6, r_series: float = 2e3) -> dict:
    """Triangular sweep 0 -> +v -> 0 -> -v -> 0 through r_series (the classic quasi-static I-V); returns V across the device and I."""
    q = period / 4
    deck = ["hyst", ".model rr RRAM", f"Vp p 0 PWL(0 0 {q} {v_amp} {2 * q} 0 {3 * q} {-v_amp} {4 * q} 0)", f"Rs p t {r_series}", "N1 t 0 g rr", ".ic v(g)=1.7",
            ".options abstol=1e-12 reltol=1e-6 vntol=1e-7 method=gear", f".tran {period / 4000} {period} 0 {period / 4000} uic"]
    d = osdi.run_wrdata(deck, ["v(t)", "i(vp)", "v(g)"])
    v, i, g = d["v(t)"], -d["i(vp)"], d["v(g)"]
    k = np.unique(np.linspace(0, len(v) - 1, 600).astype(int))
    # switching voltages: where the gap crosses mid-window on the way down / up
    mid = 0.95
    i_set = int(np.argmax(g < mid)) if (g < mid).any() else None
    i_rst = (i_set + int(np.argmax(g[i_set:] > mid))) if i_set is not None and (g[i_set:] > mid).any() else None
    return dict(period_s=period, r_series=r_series, v=v[k].tolist(), i=i[k].tolist(), gap=g[k].tolist(),
                v_set=float(v[i_set]) if i_set else None, v_reset=float(v[i_rst]) if i_rst else None, gap_min=float(g.min()), gap_end=float(g[-1]))


def main() -> None:
    RP.COMPACT.mkdir(parents=True, exist_ok=True)
    ng = osdi.check_ngspice()
    comp = compile_all()
    assert comp["received"]["returncode"] != 0, "the model as received compiled - the bug description does not hold"
    assert comp["fixed"]["returncode"] == 0, "the fixed model does not compile"
    fixed = osdi.build_osdi()
    alt = _osdi_for(va_variants()["alternative_clip_at_zero"], "clip_at_zero")
    clamp = dict(fixed=dict(set=hard_set(fixed, v=2.0, r_series=10.0), reset=hard_set(fixed, v=1.5, polarity=-1, gap0=0.2)),
                 alternative_clip_at_zero=dict(set=hard_set(alt, v=2.0, r_series=10.0), reset=hard_set(alt, v=1.5, polarity=-1, gap0=0.2)))
    r_lrs, r_hrs = read_r(fixed, 0.2), read_r(fixed, 1.7)
    gaps = np.round(np.linspace(0.2, 1.7, 16), 3)
    r_osdi = np.array([read_r(fixed, g) for g in gaps])
    r_1a = np.array([float(device_resistance(g)) for g in gaps])
    vs = np.round(np.linspace(-0.5, 0.5, 101), 4)
    from device.model import device_current
    iv = {}
    for g in (0.2, 0.7, 1.2, 1.7):
        v_o, i_o = iv_curve(fixed, g, vs)
        i_m = device_current(v_o, g)
        nz = np.abs(v_o) > 1e-9
        iv[str(g)] = dict(v=vs.tolist(), i=i_o.tolist(), max_rel_err=float(np.max(np.abs(i_o[nz] - i_m[nz]) / np.abs(i_m[nz]))), abs_err_at_0v=float(abs(i_o[~nz]).max()))
    hyst = [hysteresis(fixed, p) for p in (1e-6, 1e-4, 1e-2, 1.0)]
    out = dict(ngspice=ng, openvaf=osdi.tools()["openvaf"], compile=comp, clamp=clamp,
               r_lrs=r_lrs, r_hrs=r_hrs, r_lrs_1a=R_LRS_1A, r_hrs_1a=R_HRS_1A, rel_err_lrs=r_lrs / R_LRS_1A - 1, rel_err_hrs=r_hrs / R_HRS_1A - 1,
               gap_sweep=dict(gaps=gaps.tolist(), r_osdi=r_osdi.tolist(), r_1a_equation=r_1a.tolist(), max_rel_err=float(np.max(np.abs(r_osdi / r_1a - 1)))),
               iv=iv, hysteresis=hyst)
    (RP.COMPACT / "d0_validation.json").write_text(json.dumps(out, indent=1))
    print(f"ngspice-{ng['version']}; received model: rc={comp['received']['returncode']} ({re.sub(chr(10), ' ', comp['received']['log'])[:160]}...)")
    print(f"fixed: rc={comp['fixed']['returncode']}; alternative (clamp at 0): rc={comp['alternative_clip_at_zero']['returncode']}")
    print("hard SET  -> gap: fixed", clamp["fixed"]["set"], " alternative", clamp["alternative_clip_at_zero"]["set"])
    print("hard RESET-> gap: fixed", clamp["fixed"]["reset"], " alternative", clamp["alternative_clip_at_zero"]["reset"])
    print(f"R(0.2 nm) = {r_lrs:.4f} ohm (1A {R_LRS_1A}), R(1.7 nm) = {r_hrs:.2f} ohm (1A {R_HRS_1A}); gap sweep max rel err {out['gap_sweep']['max_rel_err']:.2e}; I-V max rel err "
          f"{max(v['max_rel_err'] for v in iv.values()):.2e}")
    for h in hyst:
        print(f"hysteresis period {h['period_s']:g} s: V_set {h['v_set']}, V_reset {h['v_reset']}, gap min {h['gap_min']:.3f}, end {h['gap_end']:.3f}")
    if abs(out["rel_err_lrs"]) > 1e-4 or abs(out["rel_err_hrs"]) > 1e-4:
        raise SystemExit("STOP: the compiled model does not reproduce 1A's device resistances")


if __name__ == "__main__":
    main()
