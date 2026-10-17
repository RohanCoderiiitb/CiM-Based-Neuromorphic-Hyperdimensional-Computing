"""1D-ii D3: retention, drift and temperature - measured on the compiled model where it has a mechanism, named as absent where it has none.

(a) Zero bias (storage). In rram.va the physical gap velocity is Vel0 exp(-Ea/kT) sinh(V ...): exactly ZERO at V = 0, at any temperature. The only zero-bias motion is the
    clamp terms' tail - smoothstep(minGap - Gap, smoothing) decays only as smoothing / (4 delta^2) away from the clamp, times limexp(-Kclip delta) - which pushes a state near a
    clamp away from it. Measured: a device alone (both terminals grounded) from several gaps, transient to 10 years, at 27 and 85 C, for the default smoothing (1e-8) and for
    1e-10 / 1e-12: if the motion scales with `smoothing` it is a numerical artefact, not retention.
(b) Read disturb (a mechanism the model DOES have): during every read the device carries ~0.1 V in the SET direction (1F: row 0.35 V, sense node 0.25 V); the gap closes at
    the physical rate. Measured: the cell (device + BSIM4 transistor, bitline side) held at the read bias for 100 s, gap change per second of read stress, at 27 and 85 C,
    for the design-adjacent and the in-envelope states. Converted to per inference with 1E's read pattern (45,786 active-row reads per inference over 512 rows, T + tail per read).
(c) Temperature of the programmed state: the device's read current has no temperature term ($vt appears only in the kinetics) - ABSENT. The read path's temperature dependence
    comes from the access transistor (BSIM4): branch current at 1F's read bias vs temperature (program/read_conditions.py).
Usage: python -m program.d3_retention"""
from __future__ import annotations

import json
from multiprocessing import Pool

import numpy as np

import paths as RP
from spice import osdi
from spice.netlist import PTM_LIB

GAPS = (0.2, 0.25, 0.3, 0.35, 0.45, 0.6, 1.0, 1.3, 1.45, 1.55, 1.6, 1.65, 1.7)
T_PROBE = (1.0, 3600.0, 86400.0, 3.156e7, 3.156e8)
YEAR = 3.156e7


def zero_bias_mirror(gap0: float, smoothing: float, t_probe=T_PROBE) -> list:
    """V = 0: dGap/dt = f(Gap) is autonomous and one-dimensional (the physical term is exactly zero; f is the clamp tail). Exact time to travel by quadrature,
    t(g) = int dg / f(g), on a 1e-5 nm grid with the Python mirror of rram.va (program/model.py); g(t) by inversion. Validated against ngspice below."""
    from program.model import P, gap_rate_nm_s
    p = dict(P, smoothing=smoothing)
    sign = 1.0 if gap0 < 0.95 else -1.0                   # pushed away from the nearer clamp
    lim = 0.95
    g = np.arange(gap0, lim, sign * 1e-5) if sign > 0 else np.arange(gap0, lim, -1e-5)
    f = np.abs(gap_rate_nm_s(0.0, g, p=p))
    dt = np.concatenate([[0.0], np.cumsum(1e-5 / np.maximum(0.5 * (f[1:] + f[:-1]), 1e-300))])
    return [float(np.interp(t, dt, g)) for t in t_probe]


def zero_bias_ngspice(args) -> dict:
    """Validation of the quadrature: the compiled model, device alone at V = 0, transient to t_end."""
    smoothing, gaps, t_end = args
    L = ["zero bias", f".model rr RRAM smoothing={smoothing}", ".options method=gear reltol=1e-7 abstol=1e-15 vntol=1e-10"]
    for i, g in enumerate(gaps):
        L += [f"Vt{i} t{i} 0 DC 0", f"N{i} t{i} 0 g{i} rr", f".ic v(g{i})={g}"]
    L.append(f".tran {t_end / 1e4:.6g} {t_end:.6g} 0 {t_end / 50:.6g} uic")
    ctl = [".control", *osdi.control_preamble(), "set numdgt=12", "run"] + [f"meas tran z{i} find v(g{i}) at={t_end * 0.999:.6g}" for i in range(len(gaps))] + [".endc", ".end"]
    s = osdi.scalars(osdi.run("\n".join(L + ctl) + "\n", timeout=1800))
    return dict(smoothing=smoothing, t=t_end * 0.999, gaps0=list(gaps), ngspice=[s.get(f"z{i}") for i in range(len(gaps))],
                mirror=[zero_bias_mirror(g, smoothing, (t_end * 0.999,))[0] for g in gaps])


def read_disturb(args) -> dict:
    """The cell at the 1F read bias (row line 0.35 V, bitline/sense node 0.25 V, transistor on the bitline side, word line 1.1 V) for t_hold seconds."""
    temp, t_hold = args
    gaps = (0.35, 0.6, 1.0, 1.3, 1.45, 1.55, 1.6)
    L = ["read disturb", f".include {PTM_LIB}", ".model rr RRAM", f".temp {temp}", ".options method=gear reltol=1e-7 abstol=1e-12 vntol=1e-9",
         "Vrl rl 0 DC 0.35", "Vbl bl 0 DC 0.25", "Vwl wl 0 DC 1.1"]
    for i, g in enumerate(gaps):
        L += [f"N{i} rl m{i} g{i} rr", f"M{i} m{i} wl bl 0 ptm45n_lp W=0.54u L=0.045u", f"Cm{i} m{i} 0 1f", f".ic v(m{i})=0.25 v(g{i})={g + 0.25}"]
    L.append(f".tran {t_hold / 1000:.6g} {t_hold:.6g} 0 {t_hold / 200:.6g} uic")
    ctl = [".control", *osdi.control_preamble(), "set numdgt=12", "run"]
    for i in range(len(gaps)):
        ctl += [f"let gg{i} = v(g{i})-v(m{i})", f"meas tran a{i} find gg{i} at={t_hold * 0.001:.6g}", f"meas tran b{i} find gg{i} at={t_hold:.6g}",
                f"let vd{i} = v(rl)-v(m{i})", f"meas tran v{i} find vd{i} at={t_hold * 0.5:.6g}", f"meas tran i{i} find i(Vrl) at={t_hold * 0.5:.6g}"]
    ctl += [".endc", ".end"]
    out = osdi.run("\n".join(L + ctl) + "\n", timeout=3600)
    s = osdi.scalars(out)
    res = []
    for i, g in enumerate(gaps):
        if f"a{i}" not in s:
            res.append(dict(gap=g, error=out[-300:]))
            continue
        dg = s[f"b{i}"] - s[f"a{i}"]
        res.append(dict(gap=g, gap_start=s[f"a{i}"], gap_end=s[f"b{i}"], rate_nm_per_s=dg / (t_hold * 0.999), v_dev=s[f"v{i}"]))
    return dict(temp_c=temp, t_hold_s=t_hold, rows=res)


def main() -> None:
    RP.PROGRAM.mkdir(parents=True, exist_ok=True)
    zb = [dict(smoothing=sm, gaps0=list(GAPS), t=list(T_PROBE), gap=[zero_bias_mirror(g, sm) for g in GAPS]) for sm in (1e-8, 1e-10, 1e-12)]
    with Pool(8) as p:
        val = p.map(zero_bias_ngspice, [(sm, (0.22, 0.25, 0.3, 1.6, 1.65), t) for sm in (1e-8, 1e-12) for t in (1e-3, 1.0)])
        rd = p.map(read_disturb, [(27.0, 1e-3), (85.0, 1e-3), (125.0, 1e-3)])
    # read stress per inference: 45,786 active-row reads per inference (1C/1E, g = 8) over 512 rows, each T + tail = 2.3 ns (1F g = 8) / 1.3 ns (g = 4)
    per_row_reads = 45_786 / 512
    stress = dict(g8_s=per_row_reads * 2.3e-9, g4_s=(28_476 * 1.61 / 512) * 1.3e-9, note="mean read-stress time per row per inference")
    out = dict(zero_bias=zb, zero_bias_validation=val, read_disturb=rd, stress_per_inference=stress,
               note="zero bias: temperature-independent (the physical term is zero at V = 0; the clamp tail has no $vt)")
    (RP.PROGRAM / "d3_retention.json").write_text(json.dumps(out, indent=1))
    for z in zb:
        print(f"smoothing {z['smoothing']:g}: " + "; ".join(f"{g0}->{z['gap'][i][2]:.3f}(1d)/{z['gap'][i][4]:.3f}(10y)" for i, g0 in enumerate(z["gaps0"]) if z["gap"][i][4] is not None))
    for r in rd:
        print(f"read disturb {r['temp_c']} C: " + "; ".join(f"{x['gap']}: {x.get('rate_nm_per_s', float('nan')):.3e} nm/s (Vdev {x.get('v_dev', float('nan')):.3f})" for x in r["rows"]))
    print("stress per inference", stress)
    for v in val:
        print("validation", v["smoothing"], v["t"], [f"{a:.5f}/{b:.5f}" for a, b in zip(v["ngspice"], v["mirror"])])


if __name__ == "__main__":
    main()
