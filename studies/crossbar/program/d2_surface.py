"""1D-ii D2: sigma_lnG as a measured function of program effort - the surface that replaces 1A-1F's assumed 0.10.

Two write devices, both on the compiled model's pulse maps (program/tables.py):
  A  'in-envelope'  : the 1D-i array (20 F^2, bitline-side transistor, word line 1.1 V, far row), amplitudes inside the 1.1 V transistor rating (SET <= 1.3 V, RESET <= 1.1 V);
                      millisecond pulses (1D-i: the array holds a level indefinitely, the cost is time), because nothing shorter moves the device (D1).
  B  'design-capable': OUT OF ENVELOPE - a 200 F^2 thick-oxide access transistor at a 3 V word line on a near-row bitline (d1_characterise: the smallest device that reaches
                      the design-adjacent states within 1 us). A different array; run to show what short pulses would buy.
Targets: the design-adjacent states 0.35 nm (LRS, 987 ohm) and 1.55 nm (HRS, 120 kohm) (1A's 0.2 / 1.7 nm sit on the model's clamps: a target there measures the clamp, not
placement; D1). LRS devices start from HRS (U(1.55, 1.7) nm, after the RESET phase); HRS devices start from the LRS (0.35 +/- 0.025 nm, the previous weight).
Axes: pulses allowed n_max; window +/- w on the conductance; pulse width and ISPP step; verify accuracy (1F's single read at T = 1 ns: 1.416 uA, at 2 ns: 0.870 uA, averaged
over n_avg reads); imposed switching variability sigma_c2c / sigma_d2d [ASSUM, the model has none].
Usage: python -m program.d2_surface"""
from __future__ import annotations

import itertools
import json
from multiprocessing import Pool

import numpy as np

import paths as RP
from program import tables as T, verify as V

SIG_READ = {"1ns": 1.416e-6, "2ns": 0.870e-6}       # [SIM, 1F pareto_raw: vb 0.50, tail 0.3 ns, thermal + comparator]
G_LRS, G_HRS = 0.35, 1.55
N_MAX = (1, 2, 3, 5, 8, 12, 20, 30, 50, 80)
WINDOWS = (0.02, 0.05, 0.1, 0.2)
N_AVG = (1, 4, 16, 64)
C2C = (0.0, 0.1, 0.3)
D2D = (0.0, 0.3)
N_DEV = 4000

SCEN = {
    "A": dict(lrs=dict(widths=(1e-3, 3.162e-3, 1e-2, 3.162e-2), corr=1e-2, v0_set=1.0, v0_reset=0.8, v_max_set=1.3, v_max_reset=1.1, dvs=(0.05, 0.1)),
              hrs=dict(widths=(1e-2, 3.162e-2, 1e-1), corr=1e-6, v0_set=1.0, v0_reset=0.8, v_max_set=1.3, v_max_reset=1.1, dvs=(0.05, 0.1))),
    "B": dict(lrs=dict(widths=(1e-7, 3.162e-7, 1e-6), corr=1e-7, v0_set=1.0, v0_reset=0.8, v_max_set=2.4, v_max_reset=2.4, dvs=(0.05, 0.1)),
              hrs=dict(widths=(1e-7, 3.162e-7, 1e-6), corr=1e-8, v0_set=0.8, v0_reset=1.0, v_max_set=2.4, v_max_reset=2.4, dvs=(0.05, 0.1))),
}
_MAPS: dict = {}


def maps(scen: str) -> V.Maps:
    if scen not in _MAPS:
        t = T.main_tables() if scen == "A" else T.design_tables()
        _MAPS[scen] = V.Maps(t["set"], t["reset"])
    return _MAPS[scen]


def _one(a):
    scen, state, tw, dv, w, n_max, rd, n_avg, c2c, d2d = a[:10]
    one_sided = len(a) > 10 and a[10]
    sp = SCEN[scen][state]
    L = V.Loop(g_target=G_LRS if state == "lrs" else G_HRS, w=w, n_max=n_max, t_w=tw, t_w_corr=sp["corr"], v0_set=sp["v0_set"], v0_reset=sp["v0_reset"], dv=dv,
               v_max_set=sp["v_max_set"], v_max_reset=sp["v_max_reset"], sigma_read_a=SIG_READ[rd], n_avg=n_avg, sigma_c2c=c2c, sigma_d2d=d2d,
               start="hrs" if state == "lrs" else G_LRS, start_spread=0.15 if state == "lrs" else 0.05, one_sided=bool(one_sided))
    r = V.run(L, maps(scen), n=N_DEV, seed=hash((tw, dv, w, n_max, rd, n_avg, c2c, d2d)) % 2**31)
    return dict(scen=scen, state=state, t_w=tw, dv=dv, w=w, n_max=n_max, read=rd, n_avg=n_avg, c2c=c2c, d2d=d2d, one_sided=bool(one_sided), **r)


def jobs(scen: str) -> list:
    J = []
    for state in ("lrs", "hrs"):
        sp = SCEN[scen][state]
        # the full surface at no imposed variability
        for tw, dv, w, n_max, rd, n_avg in itertools.product(sp["widths"], sp["dvs"], WINDOWS, N_MAX, SIG_READ, N_AVG):
            J.append((scen, state, tw, dv, w, n_max, rd, n_avg, 0.0, 0.0))
        # imposed variability on a slice
        for tw, w, n_max, rd, n_avg, (c2c, d2d) in itertools.product(sp["widths"], (0.05, 0.1), N_MAX, SIG_READ, N_AVG, ((0.1, 0.0), (0.3, 0.0), (0.0, 0.3), (0.3, 0.3))):
            J.append((scen, state, tw, sp["dvs"][0], w, n_max, rd, n_avg, c2c, d2d))
    # HRS one-sided verify (G below a ceiling): what the read actually needs of an HRS
    sp = SCEN[scen]["hrs"]
    for tw, w, n_max, rd, n_avg, (c2c, d2d) in itertools.product(sp["widths"], (0.0, 0.2, 0.5, 1.0), N_MAX, SIG_READ, N_AVG, ((0.0, 0.0), (0.3, 0.3))):
        J.append((scen, "hrs", tw, sp["dvs"][0], w, n_max, rd, n_avg, c2c, d2d, True))
    return J


def _round(x):
    """6 significant digits: the surface has ~20,000 runs; full precision would only bloat the file."""
    if isinstance(x, float):
        return float(f"{x:.6g}")
    if isinstance(x, dict):
        return {k: _round(v) for k, v in x.items()}
    if isinstance(x, list):
        return [_round(v) for v in x]
    return x


def floor_model(sig_read_a: float, n_avg: int, i_t: float, beta: float, w: float) -> float:
    """[MODEL] what an accept-on-first-in-window-read loop converges to when the pulses are fine: the accepted devices are the read-noise-smeared window. A device is accepted
    when I_meas = I_true + e lands in the window; with many small steps the true values of accepted devices spread over the window convolved with the read error:
    sigma_lnG^2 ~ (w_lnI^2 / 3 + s_r^2) / beta^2, s_r = sig_read / sqrt(n_avg) / I_t (relative read error), w_lnI = beta w the window in ln I, beta = dlnI/dlnG (ballast)."""
    s_r = sig_read_a / np.sqrt(n_avg) / i_t
    return float(np.sqrt(((beta * w) ** 2 / 3 + s_r ** 2)) / beta)


def main(scens=("A", "B")) -> None:
    f = RP.PROGRAM / "d2_surface.json"
    out = json.loads(f.read_text()) if f.exists() else {}
    for scen in scens:
        J = jobs(scen)
        with Pool(30) as p:
            rows = p.map(_one, J, chunksize=4)
        out[scen] = rows
        print(scen, len(rows), "runs", flush=True)
    # ballast factor and signal at the targets (1F read bias, BSIM4 transistor)
    g = np.array([G_LRS, G_HRS])
    i_t = V.i_read(g)
    dg = 1e-4
    beta = (np.log(V.i_read(g - dg)) - np.log(V.i_read(g + dg))) / (2 * dg / 0.25)
    out["targets"] = dict(gaps=g.tolist(), i_read_a=i_t.tolist(), beta=beta.tolist(),
                          floor_model={f"{s}|{rd}|{na}|{w}": floor_model(SIG_READ[rd], na, i_t[k], beta[k], w) for k, s in enumerate(("lrs", "hrs"))
                                       for rd in SIG_READ for na in N_AVG for w in WINDOWS})
    (RP.PROGRAM / "d2_surface.json").write_text(json.dumps(_round(out), separators=(",", ":")))
    print("targets", out["targets"]["i_read_a"], out["targets"]["beta"])


if __name__ == "__main__":
    import sys
    main(tuple(sys.argv[1:]) or ("A", "B"))
